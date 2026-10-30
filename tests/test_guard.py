"""The fact check on every draft: prices, times, links and numbers must come from the info file."""
from front_desk.guard import check


def test_price_from_the_file_passes(biz):
    assert check("Kids Climb Club is $25 per class.", biz.facts_text).ok


def test_invented_price_fails(biz):
    v = check("Kids Climb Club is $40 per class.", biz.facts_text)
    assert not v.ok and "$40" in v.problems[0]


def test_price_written_differently_still_matches(biz):
    assert check("A day pass is $22.00.", biz.facts_text).ok
    assert check("Base Camp is $ 300.", biz.facts_text).ok


def test_time_from_the_file_passes_in_any_format(biz):
    for t in ("9:00 AM", "9am", "9 a.m.", "9:00am"):
        assert check(f"Class starts Saturday at {t}.", biz.facts_text).ok, t


def test_invented_time_fails(biz):
    v = check("Class starts Saturday at 9:30 AM.", biz.facts_text)
    assert not v.ok and "9:30 AM" in v.problems[0]


def test_link_must_be_in_the_file(biz):
    assert check("Book at https://ridgeline-climbing.example.com/book.", biz.facts_text).ok
    v = check("Book at https://ridgeline-climbing.example.com/promo.", biz.facts_text)
    assert not v.ok and "promo" in v.problems[0]


def test_numbers_may_come_from_the_customer_but_not_from_nowhere(biz):
    email = "A party for 12 kids in December."
    assert check("A party for 12 kids works with the Summit package.", biz.facts_text, email).ok
    v = check("We can fit 50 kids.", biz.facts_text, email)
    assert not v.ok and '"50"' in v.problems[0]


def test_a_price_the_customer_wrote_is_still_not_allowed(biz):
    # "Is it still $35?" must not let the draft confirm $35.
    assert not check("Yes, it's $35.", biz.facts_text, "Is it still $35?").ok


def test_never_promise_words_fail(biz):
    v = check("We can offer a sibling discount.", biz.facts_text, never_promise=biz.never_promise)
    assert not v.ok and "discount" in v.problems[0]


def test_settings_are_not_facts(biz):
    # The [agent] section and the never-promise list are not things a reply may quote.
    assert "claude-sonnet" not in biz.facts_text and "never_promise" not in biz.facts_text
    assert "$79" in biz.facts_text and "9:00 AM" in biz.facts_text
