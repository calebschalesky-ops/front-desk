import json
from pathlib import Path

import pytest

from front_desk import config as config_mod
from front_desk.mail import parse

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def biz():
    return config_mod.load(ROOT / "business.example.toml")


@pytest.fixture
def sample():
    def load(name):
        return parse((ROOT / "samples" / f"{name}.eml").read_bytes(), uid=f"{name}.eml")
    return load


class FakeModel:
    """Stands in for a Claude client. The first call is extract, the second compose.

    `form` is merged into the extract answer; `reply` and `unanswered` make the
    compose answer. Records every call so tests can see what the model was shown.
    """

    name = "fake model"

    def __init__(self, form=None, reply="Hi,\n\nThanks for writing.", unanswered=None, raw=None):
        self.form = {"topic": "class", "sender_name": "", "questions": [], "details": "",
                     "suspicious_lines": [], **(form or {})}
        self.reply, self.unanswered, self.raw = reply, unanswered or [], raw
        self.calls = []

    def complete(self, system, prompt, max_tokens=1200):
        self.calls.append({"system": system, "prompt": prompt})
        if self.raw is not None:
            return self.raw
        if len(self.calls) == 1:
            return json.dumps(self.form)
        return "```json\n" + json.dumps({"reply": self.reply, "unanswered": self.unanswered}) + "\n```"


@pytest.fixture
def fake_model():
    return FakeModel
