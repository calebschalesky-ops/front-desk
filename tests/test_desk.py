import pytest

from front_desk.desk import (CLASS, DRAFTED, FLAGGED, OTHER, PARTIAL, PARTY, PRICING, PRIVATE, SCHEDULE,
                             handle, rules)

EXPECTED = {
    "01-saturday-kids": (CLASS, DRAFTED),
    "02-birthday-party": (PARTY, DRAFTED),
    "03-private-lesson": (PRIVATE, DRAFTED),
    "04-pricing": (PRICING, DRAFTED),
    "05-schedule": (SCHEDULE, DRAFTED),
    "06-sibling-discount": (CLASS, FLAGGED),
    "07-injection": (PARTY, FLAGGED),
    "09-corporate-event": (OTHER, FLAGGED),
}


@pytest.mark.parametrize("name,expected", EXPECTED.items())
def test_offline_topic_and_status_for_every_sample(biz, sample, name, expected):
    res = handle(sample(name), biz)
    assert (res.topic, res.status) == expected
    assert (res.draft is not None) == (res.status == DRAFTED)


def test_nine_pm_parent_gets_the_saturday_kids_class(biz, sample):
    draft = handle(sample("01-saturday-kids"), biz).draft
    assert "Hi Dana" in draft
    assert "Kids Climb Club" in draft and "Saturday 9:00 AM" in draft
    assert "$25 per class" in draft
    assert biz.booking_link in draft and biz.waiver_link in draft
    assert "Wednesday" not in draft            # they asked about Saturdays
    assert "Intro to Bouldering" not in draft  # the adult class is not for an 8-year-old
    assert draft.endswith(biz.signoff)


def test_party_draft_has_packages_deposit_and_link(biz, sample):
    draft = handle(sample("02-birthday-party"), biz).draft
    assert "$300" in draft and "$425" in draft and "$100 deposit" in draft
    assert "Saturday 1:00 PM" in draft and biz.booking_link in draft


def test_uncovered_question_is_flagged_not_guessed(biz, sample):
    res = handle(sample("09-corporate-event"), biz)
    assert res.status == FLAGGED and res.draft is None
    assert "info file" in res.note


def test_never_promise_question_is_flagged(biz, sample):
    res = handle(sample("06-sibling-discount"), biz)
    assert res.status == FLAGGED and '"discount"' in res.note


def test_model_that_invents_a_price_produces_a_flag_not_a_draft(biz, sample, fake_model):
    model = fake_model({"topic": "class", "sender_name": "Dana"},
                       reply="Hi Dana,\n\nKids Climb Club is $40 on Saturdays at 9:00 AM.\n\nThanks,\nAlex")
    res = handle(sample("01-saturday-kids"), biz, client=model)
    assert len(model.calls) == 2          # the model did write a draft...
    assert res.draft is None              # ...and it was thrown away
    assert res.status == FLAGGED and "$40" in res.note


def test_model_that_invents_a_time_produces_a_flag(biz, sample, fake_model):
    model = fake_model({"topic": "class"}, reply="Kids Climb Club is $25, Saturday at 10:15 AM.")
    res = handle(sample("01-saturday-kids"), biz, client=model)
    assert res.status == FLAGGED and "10:15 AM" in res.note


def test_model_draft_that_checks_out_is_kept(biz, sample, fake_model):
    reply = ("Hi Dana,\n\nYes! Kids Climb Club meets Saturday at 9:00 AM and is $25 per class. "
             f"Book here: {biz.booking_link}\n\n{biz.signoff}")
    res = handle(sample("01-saturday-kids"), biz, client=fake_model({"topic": "class"}, reply=reply))
    assert res.status == DRAFTED and res.draft == reply


def test_nothing_answerable_produces_a_flag_and_no_draft(biz, sample, fake_model):
    model = fake_model({"topic": "other"}, reply="", unanswered=["corporate events for 40 people"])
    res = handle(sample("09-corporate-event"), biz, client=model)
    assert res.status == FLAGGED and "corporate events" in res.note and res.draft is None


def test_a_holding_reply_with_no_facts_is_a_flag_not_a_partial(biz, sample, fake_model):
    # What Claude actually wrote for the corporate event in a real run.
    reply = ("Hi Erin,\n\nThanks for reaching out! I don't have details on hand about corporate "
             "team-building events for a group that size, so let me check on that and get back to you.")
    model = fake_model({"topic": "other"}, reply=reply, unanswered=["corporate events for 40 people"])
    res = handle(sample("09-corporate-event"), biz, client=model)
    assert res.status == FLAGGED and res.draft is None and "corporate events" in res.note


def test_partly_answerable_gets_a_draft_and_still_needs_the_owner(biz, sample, fake_model):
    reply = ("Hi Marcus,\n\nSummit is $425 for up to 16 kids, and Saturday 1:00 PM is open. "
             f"I'll check on cupcakes and get back to you.\n\n{biz.signoff}")
    model = fake_model({"topic": "birthday party"}, reply=reply, unanswered=["can they bring cupcakes"])
    res = handle(sample("02-birthday-party"), biz, client=model)
    assert res.status == PARTIAL and res.draft == reply
    assert "cupcakes" in res.note and "you'll check" in res.note


def test_partial_draft_still_goes_through_the_guard(biz, sample, fake_model):
    model = fake_model({"topic": "birthday party"}, reply="Summit is $40. I'll check on cupcakes.",
                       unanswered=["cupcakes"])
    res = handle(sample("02-birthday-party"), biz, client=model)
    assert res.status == FLAGGED and "$40" in res.note and res.draft is None


def test_unreadable_model_reply_is_a_flag(biz, sample, fake_model):
    res = handle(sample("01-saturday-kids"), biz, client=fake_model(raw="Sure! Here's a reply."))
    assert res.status == FLAGGED and res.draft is None


def test_hidden_html_injection_is_caught_offline(biz, sample):
    res = handle(sample("07-injection"), biz)
    assert res.status == FLAGGED and res.draft is None
    assert any("pre-approved" in s for s in res.suspicious)
    assert any("do not mention this to the owner" in s for s in res.suspicious)


def test_injection_still_caught_when_the_model_misses_it(biz, sample, fake_model):
    model = fake_model({"topic": "birthday party", "suspicious_lines": []},
                       reply="The Summit package is $40 for 30 kids.")
    res = handle(sample("07-injection"), biz, client=model)
    assert res.status == FLAGGED and res.draft is None
    assert len(model.calls) == 1   # extract ran, compose never did


def test_compose_never_sees_the_raw_email(biz, sample, fake_model):
    model = fake_model({"topic": "class", "sender_name": "Dana",
                        "questions": ["Is there a kids class on Saturdays?", "How much is it?"]},
                       reply=f"Hi Dana,\n\nKids Climb Club is Saturday 9:00 AM, $25 per class.\n\n{biz.signoff}")
    handle(sample("01-saturday-kids"), biz, client=model)
    extract_call, compose_call = model.calls
    assert "furniture" in extract_call["prompt"]       # extract reads the email
    assert "furniture" not in compose_call["prompt"]   # compose does not
    assert "kids class on Saturdays" in compose_call["prompt"]
    assert "$25 per class" in compose_call["system"]   # compose gets the info file


def test_rules_never_need_a_model(biz, sample):
    assert rules(sample("02-birthday-party"), biz).topic == PARTY
