import csv
import datetime as dt

from front_desk import ledger
from front_desk.desk import BOOKED, PARTIAL, handle


def _rows(biz, sample, *names):
    rows = []
    for n in names:
        ledger.add(rows, handle(sample(n), biz))
    return rows


def test_csv_has_one_readable_row_per_inquiry(biz, sample, tmp_path):
    rows = _rows(biz, sample, "01-saturday-kids", "07-injection")
    path = tmp_path / "inquiries.csv"
    ledger.save(path, rows)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # Excel opens it as UTF-8
    with open(path, newline="", encoding="utf-8-sig") as f:
        got = list(csv.DictReader(f))
    assert [r["name"] for r in got] == ["Dana Whitfield", "Party Planning"]
    assert got[0]["topic"] == "class" and got[0]["status"] == "draft ready"
    assert got[0]["date"] == "2026-10-29 21:04"
    assert got[1]["status"] == "needs you" and "instructions to an AI" in got[1]["note"]
    assert ledger.load(path) == got


def test_follow_ups_come_at_day_2_and_day_5_only(biz, sample):
    rows = _rows(biz, sample, "01-saturday-kids")       # arrived 2026-10-29
    day = lambda d: dt.date(2026, 10, 29) + dt.timedelta(days=d)
    assert ledger.due(rows, day(1), [2, 5]) == []
    assert [n for _, n in ledger.due(rows, day(2), [2, 5])] == [1]
    ledger.record_follow_up(rows[0], 1, day(2))
    assert ledger.due(rows, day(4), [2, 5]) == []
    assert [n for _, n in ledger.due(rows, day(5), [2, 5])] == [2]
    ledger.record_follow_up(rows[0], 2, day(5))
    assert ledger.due(rows, day(30), [2, 5]) == []      # two follow-ups, then it stops


def test_no_follow_ups_for_booked_or_flagged(biz, sample):
    rows = _rows(biz, sample, "03-private-lesson", "06-sibling-discount")
    notice = sample("08-booking-notice")
    assert [r["name"] for r in ledger.mark_booked(rows, notice.body, biz)] == ["Priya Nair"]
    assert rows[0]["status"] == BOOKED
    assert ledger.due(rows, dt.date(2026, 12, 1), [2, 5]) == []


def test_partial_drafts_get_follow_ups_and_can_be_booked(biz, sample):
    rows = _rows(biz, sample, "03-private-lesson")
    rows[0]["status"] = PARTIAL
    assert [n for _, n in ledger.due(rows, dt.date(2026, 10, 29), [2, 5])] == [1]
    assert ledger.mark_booked(rows, "Customer email: priya.nair@example.org", biz) == rows


def test_owner_can_stop_follow_ups_by_editing_the_sheet(biz, sample):
    rows = _rows(biz, sample, "01-saturday-kids")
    rows[0]["status"] = "closed"
    assert ledger.due(rows, dt.date(2026, 12, 1), [2, 5]) == []


def test_follow_up_text_passes_the_fact_check(biz, sample):
    row = _rows(biz, sample, "02-birthday-party")[0]
    for n in (1, 2):
        text = ledger.follow_up_text(row, n, biz)
        assert text.startswith("Hi Marcus") and biz.booking_link in text and "$" not in text
