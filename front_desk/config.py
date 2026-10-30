"""The business info file: one page of classes, times, prices and policies.

Secrets never go in this file. The Gmail app password and the Anthropic API
key are read from environment variables (see README).
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Business:
    name: str = "Your Business"
    about: str = ""
    address: str = ""
    hours: str = ""
    booking_link: str = ""
    waiver_link: str = ""
    waiver_note: str = ""
    tone: str = "friendly, plain, short"
    signoff: str = "Thanks,\nThe team"
    never_promise: list[str] = field(default_factory=lambda: ["discount", "refund", "guarantee"])
    booking_notices_from: set[str] = field(default_factory=set)
    classes: list[dict] = field(default_factory=list)
    pricing: dict = field(default_factory=dict)
    parties: dict = field(default_factory=dict)
    private_lessons: dict = field(default_factory=dict)
    policies: dict = field(default_factory=dict)
    # agent settings
    model: str = "claude-sonnet-5-5"
    gmail_folder: str = "INBOX"
    lookback_days: int = 2
    log_file: str = "inquiries.csv"
    follow_up_days: list[int] = field(default_factory=lambda: [2, 5])
    labels: dict[str, str] = field(default_factory=lambda: {
        "drafted": "AI/Draft ready", "flagged": "AI/Needs you"})
    max_body_chars: int = 6000
    source_text: str = ""   # the raw file, which is what every draft is checked against

    @property
    def gmail_user(self) -> str | None:
        return os.environ.get("FRONT_DESK_GMAIL_USER")

    @property
    def facts_text(self) -> str:
        """The info file minus agent settings and the never-promise list.

        This is the text a draft's prices, times and links must come from.
        """
        keep, skip = [], False
        for line in self.source_text.splitlines():
            s = line.strip()
            if s.startswith("["):
                skip = s.startswith("[agent")
            if skip or s.startswith("#") or s.startswith(("never_promise", "booking_notices_from", "tone")):
                continue
            keep.append(line)
        return "\n".join(keep)


def load(path: str | Path) -> Business:
    text = Path(path).read_text(encoding="utf-8")
    data = tomllib.loads(text)
    biz = Business(source_text=text)
    for k, v in data.get("business", {}).items():
        if hasattr(biz, k):
            setattr(biz, k, v)
    biz.booking_notices_from = {s.lower() for s in data.get("business", {}).get("booking_notices_from", [])}
    biz.classes = data.get("classes", [])
    for k in ("pricing", "parties", "private_lessons", "policies"):
        setattr(biz, k, data.get(k, {}))
    agent = data.get("agent", {})
    biz.labels.update(agent.get("labels", {}))
    for k in ("model", "gmail_folder", "lookback_days", "log_file", "follow_up_days", "max_body_chars"):
        if k in agent:
            setattr(biz, k, agent[k])
    return biz
