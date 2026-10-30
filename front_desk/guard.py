"""The check that stops a made-up price from reaching a customer.

Every draft, whoever wrote it, passes through check() before it is saved:

- every dollar amount must appear in the business info file,
- every clock time must appear in the business info file,
- every link must appear in the business info file,
- every other number must appear in the info file or in the customer's own email
  (so "your party on the 12th" is fine, "up to 30 kids" is not),
- no word from the never-promise list (discount, refund, ...) may appear,
- a price or time in a sentence that names a class, package or pass must
  belong to that item. "Kids Climb Club is $30" fails even though $30 is on
  the page, because $30 is the adult class's price. A sentence that names
  nothing inherits the last item named earlier in the same paragraph.

If anything fails, the draft is not saved. The inquiry is flagged for the owner
with a note saying exactly what the draft got wrong. This runs in plain Python
after the model is done, so it holds even when the model gets it wrong.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MONEY_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?")
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\b\.?", re.I)
URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\")\]]+", re.I)
PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s?%")
NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


def money(text: str) -> set[float]:
    return {float(m.group(1).replace(",", "") + "." + (m.group(2) or "00")) for m in MONEY_RE.finditer(text)}


def times(text: str) -> set[int]:
    out = set()
    for m in TIME_RE.finditer(text):
        h, mins, ap = int(m.group(1)) % 12, int(m.group(2) or 0), m.group(3).lower()
        out.add((h + (12 if ap == "p" else 0)) * 60 + mins)
    return out


def urls(text: str) -> set[str]:
    return {u.rstrip(".,;:!?").lower().removeprefix("https://").removeprefix("http://").rstrip("/")
            for u in URL_RE.findall(text)}


def numbers(text: str) -> set[str]:
    """Bare numbers left over once prices, times, links and percentages are removed."""
    for rx in (URL_RE, MONEY_RE, TIME_RE, PERCENT_RE):
        text = rx.sub(" ", text)
    return {n.rstrip("0").rstrip(".") if "." in n else n for n in NUMBER_RE.findall(text)}


def _fmt_time(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{(h % 12) or 12}:{m:02d} {'PM' if h >= 12 else 'AM'}"


@dataclass
class Item:
    """One thing on the info page (a class, the party packages, the passes) and its own facts."""
    name: str
    aliases: list[str]
    text: str

    def named_in(self, sentence: str) -> bool:
        low = sentence.lower()
        return any(re.search(rf"\b{re.escape(a.lower())}\b", low) for a in self.aliases)


SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])|\n")


def _pairing(draft: str, items, file_money: set, file_times: set) -> list[str]:
    problems = []
    for para in re.split(r"\n\s*\n", draft):
        current = None
        for sentence in SENTENCE_RE.split(para):
            named = [it for it in items if it.named_in(sentence)]
            scope = named or ([current] if current else [])
            current = named[0] if len(named) == 1 else (None if named else current)
            if not scope:
                continue
            label = " / ".join(it.name for it in scope)
            for amount in sorted((money(sentence) & file_money) - set().union(*(money(it.text) for it in scope))):
                problems.append(f"the draft gives {label} the price ${amount:,.2f}".replace(".00", "")
                                + ", which the info file lists for something else")
            for t in sorted((times(sentence) & file_times) - set().union(*(times(it.text) for it in scope))):
                problems.append(f"the draft gives {label} the time {_fmt_time(t)}, "
                                "which the info file lists for something else")
    return problems


@dataclass
class Verdict:
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def check(draft: str, facts: str, customer_text: str = "", never_promise=(), items=()) -> Verdict:
    """Compare a draft against the info file. Returns every problem found."""
    v = Verdict()
    for amount in sorted(money(draft) - money(facts)):
        v.problems.append(f"the draft quotes ${amount:,.2f}".replace(".00", "") + ", which is not in the info file")
    for t in sorted(times(draft) - times(facts)):
        v.problems.append(f"the draft gives the time {_fmt_time(t)}, which is not in the info file")
    for u in sorted(urls(draft) - urls(facts)):
        v.problems.append(f"the draft links to {u}, which is not in the info file")
    for p in sorted(set(PERCENT_RE.findall(draft)) - set(PERCENT_RE.findall(facts))):
        v.problems.append(f"the draft mentions {p}, which is not in the info file")
    allowed = numbers(facts) | numbers(customer_text)
    for n in sorted(numbers(draft) - allowed, key=lambda x: float(x)):
        v.problems.append(f'the draft uses the number "{n}", which is not in the info file or the email')
    low = draft.lower()
    for term in never_promise:
        if term.lower() in low:
            v.problems.append(f'the draft mentions "{term}", which is on the never-promise list')
    v.problems += _pairing(draft, items, money(facts), times(facts))
    return v
