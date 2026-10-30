"""The summary printed after each run: what came in, what is drafted, what needs the owner."""
from __future__ import annotations

import datetime as dt

from .desk import DRAFTED, FLAGGED, PARTIAL


def _line(r) -> str:
    out = f"- **{r.msg.subject}** from {r.name} ({r.topic})"
    if r.status in (FLAGGED, PARTIAL):
        out += f"\n  - Why: {r.note}"
        out += "".join(f"\n    > {s[:160]}" for s in r.suspicious)
    if r.draft_location:
        out += "\n  - Reply draft is waiting for you"
    return out


def render(results, booked, follow_ups, biz, used: str, today: dt.date, log_path: str) -> str:
    drafted = [r for r in results if r.status == DRAFTED]
    flagged = [r for r in results if r.status in (FLAGGED, PARTIAL)]
    with_draft = sum(1 for r in results if r.draft)
    lines = [f"# Front Desk summary for {biz.name}, {today:%A %B %d}", "",
             f"{len(results)} new inquiries. {with_draft} reply drafts are waiting for you. "
             f"{len(flagged)} need you. {len(follow_ups)} follow-up drafts. "
             f"Nothing was sent.", ""]
    if flagged:
        lines += [f"## Needs you ({len(flagged)})", ""] + [_line(r) for r in flagged] + [""]
    if drafted:
        lines += [f"## Reply drafted ({len(drafted)})", ""] + [_line(r) for r in drafted] + [""]
    if booked:
        lines += [f"## Booked ({len(booked)})", "",
                  *[f"- {r['name']} ({r['topic']}): booking confirmed, no follow-ups" for r in booked], ""]
    if follow_ups:
        lines += [f"## Follow-ups drafted ({len(follow_ups)})", ""]
        for when, row, n in follow_ups:
            lines.append(f"- {when:%a %b %d}: follow-up {n} to {row['name']} ({row['topic']}), "
                         f"no booking since {row['date'][:10]}")
        lines.append("")
    lines.append(f"Every inquiry is logged in `{log_path}`. Drafts by {used}; every price, time and "
                 f"link in them was checked against the info file.")
    return "\n".join(lines)
