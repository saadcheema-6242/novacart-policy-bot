"""The NovaCart conventions engine.

Pure, deterministic helpers that implement file 00 (How Policies Work Together):
rounding, GST, date/day-counting, version-in-force, and scope precedence.

Design note: this module encodes only the *conventions* from file 00, never the
policy values themselves (return windows, fees, thresholds). Those live in the
policy files and reach the bot through retrieval. Keeping them separate means a
policy edit never requires a code change.

None of these functions reads the system clock. Every date comes from the
question or from a file's front matter (file 00, Section 1.4 / 3).
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

# Scope precedence, least to most specific (file 00, Section 4.3).
SCOPE_RANK = {"general": 0, "specific": 1, "regional": 2}


# --- Dates -----------------------------------------------------------------
def parse_date(value: str | date) -> date:
    """Parse a YYYY-MM-DD string (file 00, Section 1.4). Accepts a date as-is."""
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()


def days_from_delivery(delivery_date: str | date, n: int) -> date:
    """Last valid day of an 'N days from delivery' window (file 00, Section 1.6).

    The window ends on delivery date + N calendar days; a request made on that
    last day is in time, so the returned date is itself still valid.
    """
    return parse_date(delivery_date) + timedelta(days=n)


def within_days_from_delivery(
    delivery_date: str | date, n: int, contact_date: str | date
) -> bool:
    """True if contact_date is on or before the 'N days from delivery' deadline."""
    return parse_date(contact_date) <= days_from_delivery(delivery_date, n)


def _add_months_clamped(d: date, months: int) -> date:
    """d shifted by `months`, clamping the day to the last day of the target month."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    last_day = monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def full_months(a: str | date, b: str | date) -> int:
    """Whole calendar months elapsed from A to B (file 00, Section 1.7).

    A month is complete on the same day-of-month as A; if the later month has no
    such day, it completes on that month's last day.

    >>> full_months("2026-01-10", "2026-04-09")
    2
    >>> full_months("2026-01-10", "2026-04-10")
    3
    """
    a, b = parse_date(a), parse_date(b)
    months = (b.year - a.year) * 12 + (b.month - a.month)
    if _add_months_clamped(a, months) > b:
        months -= 1
    return max(months, 0)


def add_business_days(event_date: str | date, n: int) -> date:
    """The date N business days after an event (file 00, Section 1.5).

    Business days are Mon-Fri; holidays are not excluded; counting starts on the
    first business day after the event.
    """
    d = parse_date(event_date)
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:  # Monday=0 ... Friday=4
            added += 1
    return d


# --- Money -----------------------------------------------------------------
def round_half_up(amount: float | int | str | Decimal) -> int:
    """Round half up to the nearest whole rupee (file 00, Section 1.3).

    Call this at the moment each amount is computed; never carry decimals into a
    later step.
    """
    return int(Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def gst_in_price(gst_inclusive_price: float | int) -> int:
    """GST contained in a GST-inclusive price (file 00, Section 1.2).

    price * 18 / 118, rounded half up.
    """
    return round_half_up(Decimal(str(gst_inclusive_price)) * 18 / 118)


def percentage_discount(eligible_subtotal: float | int, rate_percent: float, cap: int | None = None) -> int:
    """A percentage discount, rounded half up then limited to `cap` (file 12, 3.2)."""
    discount = round_half_up(Decimal(str(eligible_subtotal)) * Decimal(str(rate_percent)) / 100)
    if cap is not None:
        discount = min(discount, cap)
    return discount


# --- Version in force & precedence (file 00, Section 3-4) ------------------
def is_in_force(effective_date: str | date, contact_date: str | date) -> bool:
    """A file is in force if its effective_date is on or before the contact date."""
    return parse_date(effective_date) <= parse_date(contact_date)


def filter_in_force(docs: list[dict], contact_date: str | date) -> list[dict]:
    """Keep only docs whose effective_date <= contact_date.

    `docs` are metadata dicts carrying at least an 'effective_date' key (as built
    by ingest.py). This is what stops the 2027 shipping file (file 21) from being
    applied to a 2026 question.
    """
    return [d for d in docs if is_in_force(d["effective_date"], contact_date)]


def scope_rank(scope: str) -> int:
    return SCOPE_RANK.get((scope or "").lower(), 0)


def resolve_precedence(docs: list[dict]) -> dict:
    """Pick the winning doc among candidates covering the same topic (file 00, 4).

    Rules applied, in order:
      4.1 regional overrides general/specific regardless of date (handled by rank).
      4.3 same effective_date, different scope -> more specific scope wins.
      4.2 same scope, different effective_date -> later effective_date wins.
      4.4 same effective_date AND same scope AND different rules -> unsettled.

    Returns a dict:
      {"winner": <doc>, "status": "resolved"|"unsettled"|"single",
       "differs": bool, "note": <str>, "considered": [docs]}
    The caller decides which docs genuinely cover the same topic; this only ranks
    the set it is given.
    """
    if not docs:
        return {"winner": None, "status": "none", "differs": False,
                "note": "No in-force file covers this.", "considered": []}
    if len(docs) == 1:
        return {"winner": docs[0], "status": "single", "differs": False,
                "note": "", "considered": docs}

    # Sort by (scope rank, effective_date) descending -> most specific & newest first.
    ordered = sorted(
        docs,
        key=lambda d: (scope_rank(d.get("scope", "")), parse_date(d["effective_date"])),
        reverse=True,
    )
    top = ordered[0]
    runner = ordered[1]

    top_key = (scope_rank(top.get("scope", "")), parse_date(top["effective_date"]))
    run_key = (scope_rank(runner.get("scope", "")), parse_date(runner["effective_date"]))

    if top_key == run_key:
        # Same scope and same effective_date: the files do not settle it (4.4).
        return {
            "winner": None,
            "status": "unsettled",
            "differs": True,
            "note": ("Two in-force files share the same scope and effective_date; "
                     "they do not settle this. Tell the customer what each says and "
                     "that NovaCart support must confirm."),
            "considered": ordered,
        }

    differs = any(
        parse_date(d["effective_date"]) != parse_date(top["effective_date"])
        or d.get("scope") != top.get("scope")
        for d in ordered[1:]
    )
    note = ""
    if differs:
        note = (f"Files differ; used {top.get('file', top.get('doc_id', '?'))} "
                f"(scope={top.get('scope')}, effective_date={top['effective_date']}). "
                f"Tell the customer the files differ and which was used (file 00, 4.2).")
    return {"winner": top, "status": "resolved", "differs": differs,
            "note": note, "considered": ordered}


if __name__ == "__main__":
    # Quick self-check of the file-00 examples.
    assert full_months("2026-01-10", "2026-04-09") == 2
    assert full_months("2026-01-10", "2026-04-10") == 3
    assert gst_in_price(118) == 18
    assert round_half_up("0.5") == 1
    assert days_from_delivery("2026-03-01", 10) == date(2026, 3, 11)
    assert add_business_days("2026-01-02", 1) == date(2026, 1, 5)  # Fri -> next Mon
    assert is_in_force("2027-02-01", "2026-06-01") is False
    print("rules.py self-check passed")
