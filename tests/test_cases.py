"""Tests for the deterministic layer (rules engine + parser).

These run WITHOUT a Groq key or network — they cover the file-00 conventions and
the chunking, which is where most scoring mistakes come from.

Run from the project root:
    python -m pytest tests/ -v
(or simply: python tests/test_cases.py)
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import rules  # noqa: E402
import ingest  # noqa: E402
import config  # noqa: E402


# --- file 00, Section 1.7: full months ------------------------------------
def test_full_months_examples_from_file_00():
    assert rules.full_months("2026-01-10", "2026-04-09") == 2
    assert rules.full_months("2026-01-10", "2026-04-10") == 3


def test_full_months_month_end_clamp():
    # Jan 31 -> Feb has no 31st; one month completes on the last day of Feb.
    assert rules.full_months("2026-01-31", "2026-02-28") == 1
    assert rules.full_months("2026-01-31", "2026-02-27") == 0


# --- file 00, Section 1.6: days from delivery -----------------------------
def test_days_from_delivery_inclusive_last_day():
    assert rules.days_from_delivery("2026-03-01", 10) == date(2026, 3, 11)
    assert rules.within_days_from_delivery("2026-03-01", 10, "2026-03-11") is True
    assert rules.within_days_from_delivery("2026-03-01", 10, "2026-03-12") is False


# --- file 00, Section 1.5: business days ----------------------------------
def test_business_days_skip_weekend():
    # Friday 2026-01-02 + 1 business day -> Monday 2026-01-05.
    assert rules.add_business_days("2026-01-02", 1) == date(2026, 1, 5)
    assert rules.add_business_days("2026-01-02", 3) == date(2026, 1, 7)


# --- file 00, Section 1.2 / 1.3: GST and rounding -------------------------
def test_gst_inclusive():
    assert rules.gst_in_price(118) == 18
    assert rules.gst_in_price(1000) == 153  # 1000*18/118 = 152.54 -> 153


def test_round_half_up():
    assert rules.round_half_up("0.5") == 1
    assert rules.round_half_up("2.49") == 2
    assert rules.round_half_up("2.5") == 3


def test_percentage_discount_with_cap():
    # WELCOME10 on Rs. 5,200 = 520, below the Rs. 1,000 cap (file 06 example).
    assert rules.percentage_discount(5200, 10, cap=1000) == 520
    # 10% of 12,000 = 1,200 -> capped at 1,000.
    assert rules.percentage_discount(12000, 10, cap=1000) == 1000


# --- file 00, Section 3: version in force ---------------------------------
def test_in_force_future_file_excluded():
    # The 2027 shipping file must not apply to a 2026 question.
    assert rules.is_in_force("2027-02-01", "2026-06-01") is False
    assert rules.is_in_force("2026-01-15", "2026-06-01") is True


def test_filter_in_force_drops_future_file():
    docs = [
        {"file": "06", "effective_date": "2026-01-15", "scope": "general"},
        {"file": "21", "effective_date": "2027-02-01", "scope": "general"},
    ]
    kept = rules.filter_in_force(docs, "2026-06-01")
    assert [d["file"] for d in kept] == ["06"]


# --- file 00, Section 4: precedence ---------------------------------------
def test_precedence_later_effective_date_wins():
    docs = [
        {"file": "02", "scope": "general", "effective_date": "2025-06-01"},
        {"file": "01", "scope": "general", "effective_date": "2026-01-01"},
    ]
    res = rules.resolve_precedence(docs)
    assert res["winner"]["file"] == "01"
    assert res["differs"] is True


def test_precedence_regional_beats_general():
    docs = [
        {"file": "06", "scope": "general", "effective_date": "2026-01-15"},
        {"file": "19", "scope": "regional", "effective_date": "2026-01-01"},
    ]
    res = rules.resolve_precedence(docs)
    assert res["winner"]["file"] == "19"


def test_precedence_unsettled_when_same_scope_and_date():
    docs = [
        {"file": "A", "scope": "general", "effective_date": "2026-01-01"},
        {"file": "B", "scope": "general", "effective_date": "2026-01-01"},
    ]
    res = rules.resolve_precedence(docs)
    assert res["status"] == "unsettled"
    assert res["winner"] is None


# --- parser ----------------------------------------------------------------
def test_parser_reads_front_matter_and_items():
    path = config.POLICIES_DIR / "06_shipping_fees_and_free_shipping.md"
    chunks = ingest.parse_file(path)
    sections = {c.section for c in chunks}
    # Known items exist.
    assert "1.1" in sections
    assert "2.2" in sections
    one_one = next(c for c in chunks if c.section == "1.1")
    assert one_one.doc_id == "NC-POL-06"
    assert one_one.effective_date == "2026-01-15"
    assert one_one.scope == "general"
    # The table under 1.1 is kept with item 1.1.
    assert "Metro cities" in one_one.text()


def test_parser_covers_all_22_files():
    files = sorted(config.POLICIES_DIR.glob("*.md"))
    assert len(files) == 22
    for path in files:
        chunks = ingest.parse_file(path)
        assert chunks, f"no chunks parsed from {path.name}"


# --- rag & api input validation -------------------------------------------
def test_contact_date_regex_variants():
    import rag

    cases = [
        ("Today is 2026-02-10, can I return this?", "2026-02-10"),
        ("Today: 2026-02-10, can I return this?", "2026-02-10"),
        ("Contact date is 2026-03-01", "2026-03-01"),
        ("Contact date: 2026-03-01", "2026-03-01"),
        ("contact date 2026-03-01", "2026-03-01"),
        ("Customer contacted on 2026-02-15 regarding order", "2026-02-15"),
        ("As of 2026-04-01 what is the return window?", "2026-04-01"),
        ("What is the return window for electronics?", None),
    ]
    for q, expected in cases:
        assert rag.extract_contact_date(q) == expected, f"Failed on: {q}"


def test_ask_request_validation():
    from pydantic import ValidationError
    from app import AskRequest

    # Valid request
    req = AskRequest(question="What is the shipping fee?", k=5)
    assert req.question == "What is the shipping fee?"
    assert req.k == 5

    # Empty question rejected
    try:
        AskRequest(question="")
        assert False, "Empty question should raise ValidationError"
    except ValidationError:
        pass

    # Excessively long question rejected (>1500 chars)
    try:
        AskRequest(question="A" * 1501)
        assert False, "Question > 1500 chars should raise ValidationError"
    except ValidationError:
        pass

    # Negative or 0 k rejected
    try:
        AskRequest(question="test", k=0)
        assert False, "k=0 should raise ValidationError"
    except ValidationError:
        pass


if __name__ == "__main__":
    import traceback

    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
                passed += 1
            except Exception:
                print(f"FAIL  {name}")
                traceback.print_exc()
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
