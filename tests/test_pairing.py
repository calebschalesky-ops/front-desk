"""The price has to belong to the thing it is quoted for, not just be somewhere on the page."""
import email
from pathlib import Path

import pytest

from front_desk.guard import check

DOCS = Path(__file__).resolve().parent.parent / "docs"


def _check(biz, draft, customer=""):
    return check(draft, biz.facts_text, customer, biz.never_promise, biz.items)


@pytest.mark.parametrize("draft,wrong", [
    ("Kids Climb Club is $30 per class.", "$30"),                  # the adult class's price
    ("Summit is $300 for up to 10 kids.", "$300"),                  # Base Camp's price
    ("Yoga is Sunday at 9:00 AM.", "9:00 AM"),                      # the kids class's time
    ("Private lessons are $25 an hour.", "$25"),                    # a class price
    ("A day pass is $90.", "$90"),                                  # the 4-class pack
])
def test_a_real_price_on_the_wrong_item_is_caught(biz, draft, wrong):
    v = _check(biz, draft)
    assert not v.ok and wrong in v.problems[0] and "something else" in v.problems[0]


def test_the_item_carries_to_the_next_sentence_in_the_paragraph(biz):
    v = _check(biz, "Kids Climb Club meets Saturday at 9:00 AM. It costs $30.")
    assert not v.ok and "Kids Climb Club the price $30" in v.problems[0]


def test_a_new_paragraph_starts_fresh(biz):
    # "$30" after a blank line is not about the kids class any more.
    assert _check(biz, "Kids Climb Club meets Saturday at 9:00 AM.\n\nIntro to Bouldering is $30.").ok


def test_naming_two_items_allows_either_items_prices(biz):
    assert _check(biz, "Summit fits 16 kids, or Base Camp plus extra kids at $20 each.", "16 kids").ok


def test_correct_pairings_pass(biz):
    good = ("Kids Climb Club is $25 per class, Saturday at 9:00 AM. Intro to Bouldering is $30 "
            "on Monday at 7:00 PM. Summit is $425 and Base Camp is $300. A day pass is $22.")
    assert _check(biz, good).ok, _check(biz, good).problems


@pytest.mark.parametrize("name", ["draft-claude-01-saturday-kids.txt", "draft-claude-02-birthday-party.txt",
                                  "draft-follow-up-1.txt"])
def test_real_claude_drafts_from_the_test_run_still_pass(biz, sample, name):
    """No false alarms on the drafts Claude actually wrote in the recorded run."""
    body = (DOCS / name).read_text(encoding="utf-8").split("\n\n", 1)[1]
    customer = {"draft-claude-01-saturday-kids.txt": "01-saturday-kids",
                "draft-claude-02-birthday-party.txt": "02-birthday-party"}.get(name)
    text = sample(customer).body if customer else ""
    v = _check(biz, body, text)
    assert v.ok, v.problems
