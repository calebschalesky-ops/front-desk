"""front-desk: draft replies to class, party and lesson inquiries. Never sends.

Usage:
  python -m front_desk demo  [--out DIR] [--llm MODE]                 run on ./samples, no account needed
  python -m front_desk run   [--info FILE] [--dry-run] [--llm MODE]   run on your Gmail inbox
  python -m front_desk ask   "QUESTION" [--name NAME] [--llm MODE]    answer one typed question, live

--llm is auto (default), api, cli or offline:
  api      Anthropic API, needs ANTHROPIC_API_KEY
  cli      the Claude Code command line (claude -p), no API key needed
  offline  no model; replies are built from the info file by templates
  auto     api if a key is set, else cli if claude is installed, else offline
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

from . import config as config_mod
from . import ledger, llm
from .desk import DRAFTED, handle
from .mail import FolderMailbox, ImapMailbox, Message, build_draft
from .report import render

ROOT = Path(__file__).resolve().parent.parent
# The demo replays the sample inbox as of the night the last sample arrived,
# then jumps ahead to the 2-day and 5-day follow-up checks.
DEMO_DAYS = [dt.date(2026, 10, 29), dt.date(2026, 10, 31), dt.date(2026, 11, 3)]


def intake(box, biz, client, rows, dry_run=False):
    results, booked = [], []
    for msg in box.fetch_new(ledger.seen_ids(rows)):
        if msg.sender_address in biz.booking_notices_from:
            booked += ledger.mark_booked(rows, msg.body, biz)
            continue
        res = handle(msg, biz, client)
        if not dry_run:
            box.add_label(msg, biz.labels["drafted" if res.status == DRAFTED else "flagged"])
            if res.draft:
                res.draft_location = box.save_draft(build_draft(msg, res.draft, from_addr(biz)), msg)
        ledger.add(rows, res)
        results.append(res)
    return results, booked


def follow_ups(box, biz, rows, today: dt.date, dry_run=False):
    done = []
    for row, n in ledger.due(rows, today, biz.follow_up_days):
        text = ledger.follow_up_text(row, n, biz)
        if not dry_run:
            orig = Message(msg_id=row["message_id"], sender=f'{row["name"]} <{row["email"]}>',
                           subject=row["subject"], body="",
                           uid=f"follow-up-{n}-{re.sub(r'[^a-z0-9]+', '-', row['email'].split('@')[0])}")
            box.save_draft(build_draft(orig, text, from_addr(biz)), orig)
            ledger.record_follow_up(row, n, today)
        done.append((today, row, n))
    return done


def ask(question: str, name: str, biz, client, used: str) -> str:
    """One typed question through the full pipeline, for showing it off live. Saves nothing."""
    msg = Message(msg_id="<ask@example.com>", sender=f"{name} <customer@example.com>",
                  subject=question.split("?")[0][:60].strip() + ("?" if "?" in question else ""),
                  body=question, date=dt.datetime.now())
    res = handle(msg, biz, client)
    head = f"Topic: {res.topic}   Status: {res.status}   ({used})"
    if res.draft:
        note = f"\nFor the owner: {res.note}" if res.note else ""
        return (f"{head}{note}\nEvery price, time and link below was checked against the info file."
                f"\n\n{res.draft}")
    quoted = "".join(f"\n  > {s[:160]}" for s in res.suspicious)
    return f"{head}\n\nNo draft. Flagged for the owner: {res.note}{quoted}"


def from_addr(biz) -> str:
    return biz.gmail_user or f"{biz.name} <frontdesk@example.com>"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="front_desk", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["demo", "run", "ask"])
    p.add_argument("question", nargs="?", help="ask: the customer's message, in quotes")
    p.add_argument("--name", default="Sam Rivera", help="ask: who the message is from")
    p.add_argument("--info", default=str(ROOT / "business.example.toml"), help="your business info file")
    p.add_argument("--out", default="out", help="demo: where drafts, the log and the summary go")
    p.add_argument("--llm", default="auto", choices=["auto", "api", "cli", "offline"])
    p.add_argument("--offline", action="store_true", help="same as --llm offline")
    p.add_argument("--dry-run", action="store_true", help="run: summary only, no labels, drafts or log")
    a = p.parse_args(argv)

    biz = config_mod.load(a.info)
    client = llm.pick("offline" if a.offline else a.llm, biz.model)
    used = f"Claude via the {client.name}" if client else "offline templates (no model)"

    if a.mode == "ask":
        if not a.question:
            p.error('ask needs the question in quotes, e.g. ask "Do you do birthday parties?"')
        print(ask(a.question, a.name, biz, client, used))
        return 0
    if a.mode == "demo":
        out = Path(a.out)
        log_path = out / "inquiries.csv"
        if log_path.exists():
            log_path.unlink()   # the demo always starts from an empty log
        box = FolderMailbox(ROOT / "samples", out / "drafts")
        rows: list[dict] = []
        results, booked = intake(box, biz, client, rows)
        fus = []
        for day in DEMO_DAYS[1:]:
            fus += follow_ups(box, biz, rows, day)
        ledger.save(log_path, rows)
        report = render(results, booked, fus, biz, used, DEMO_DAYS[0], log_path.as_posix())
        (out / "report.md").write_text(report, encoding="utf-8")
    else:
        user, pw = biz.gmail_user, os.environ.get("FRONT_DESK_GMAIL_APP_PASSWORD")
        if not user or not pw:
            sys.exit("Set FRONT_DESK_GMAIL_USER and FRONT_DESK_GMAIL_APP_PASSWORD first (see README).")
        log_path = Path(biz.log_file)
        rows = ledger.load(log_path)
        box = ImapMailbox(user, pw.replace(" ", ""), biz.gmail_folder, days=biz.lookback_days)
        today = dt.date.today()
        try:
            results, booked = intake(box, biz, client, rows, dry_run=a.dry_run)
            fus = follow_ups(box, biz, rows, today, dry_run=a.dry_run)
        finally:
            box.close()
        if not a.dry_run:
            ledger.save(log_path, rows)
        report = render(results, booked, fus, biz, used, today, log_path.as_posix())
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
