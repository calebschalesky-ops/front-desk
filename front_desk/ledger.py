"""The inquiry log (a CSV that opens in Sheets or Excel) and the follow-ups.

One row per inquiry. The owner can edit the status column by hand: set it to
"booked" or "closed" and that person gets no more follow-ups.

Follow-ups: when an inquiry got a reply draft but nobody has marked it booked,
a follow-up draft is written after 2 days and a second one after 5 (set in
follow_up_days). They go to Drafts like every other reply and wait for the
owner. Flagged inquiries get no follow-ups, because the owner is handling them.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from pathlib import Path

from . import guard
from .config import Business
from .desk import BOOKED, DRAFTED, Result

COLUMNS = ["date", "name", "email", "topic", "status", "note", "follow_ups", "last_follow_up",
           "subject", "message_id"]
DATE_FMT = "%Y-%m-%d %H:%M"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def load(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save(path: Path, rows: list[dict]) -> None:
    # utf-8-sig so Excel opens names with accents correctly; Sheets ignores the marker.
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def seen_ids(rows: list[dict]) -> set[str]:
    return {r["message_id"] for r in rows}


def add(rows: list[dict], res: Result) -> dict:
    when = res.msg.date or dt.datetime.now()
    row = {"date": when.strftime(DATE_FMT), "name": res.name, "email": res.msg.sender_address,
           "topic": res.topic, "status": res.status, "note": res.note, "follow_ups": "0",
           "last_follow_up": "", "subject": res.msg.subject, "message_id": res.msg.msg_id}
    rows.append(row)
    return row


def mark_booked(rows: list[dict], notice_body: str, biz: Business) -> list[dict]:
    """A booking-system email names the customer. Mark their open inquiries booked."""
    addrs = {a.lower() for a in EMAIL_RE.findall(notice_body)} - biz.booking_notices_from
    hit = [r for r in rows if r["email"].lower() in addrs and r["status"] == DRAFTED]
    for r in hit:
        r["status"] = BOOKED
    return hit


def due(rows: list[dict], today: dt.date, days: list[int]) -> list[tuple[dict, int]]:
    """Rows that need their next follow-up today, with which one (1, 2, ...)."""
    out = []
    for r in rows:
        if r["status"] != DRAFTED:
            continue
        done = int(r["follow_ups"] or 0)
        if done >= len(days):
            continue
        age = (today - dt.datetime.strptime(r["date"], DATE_FMT).date()).days
        if age >= days[done]:
            out.append((r, done + 1))
    return out


def follow_up_text(row: dict, n: int, biz: Business) -> str:
    name = row["name"].split(" ")[0] if row["name"] and "@" not in row["name"] else "there"
    what = {"birthday party": "the birthday party", "private lesson": "private lessons",
            "class": "our classes", "pricing": "passes and memberships",
            "schedule": "coming in to climb"}.get(row["topic"], "your question")
    if n == 1:
        body = (f"Just checking in about {what}. If you have any other questions, reply here "
                f"and I'll help. When you're ready, you can book here: {biz.booking_link}")
    else:
        body = (f"One last note about {what}, in case my earlier email got buried. "
                f"Spots are booked here: {biz.booking_link}. If the timing isn't right, no problem "
                f"at all, and we'd be glad to see you whenever it works.")
    text = f"Hi {name},\n\n{body}\n\n{biz.signoff}"
    v = guard.check(text, biz.facts_text, never_promise=biz.never_promise)
    if not v.ok:  # the info file changed under us; never save a follow-up that fails the check
        raise ValueError("; ".join(v.problems))
    return text


def record_follow_up(row: dict, n: int, today: dt.date) -> None:
    row["follow_ups"] = str(n)
    row["last_follow_up"] = today.isoformat()
