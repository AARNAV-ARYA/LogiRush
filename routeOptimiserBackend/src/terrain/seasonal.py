# src/terrain/seasonal.py
"""
Seasonal closure windows and the Indian seasonal calendar.

Some Indian corridors are not "risky" in winter — they are shut. Zojila and the Manali-Leh
road close under snow every year, and a router that offers them in January is not being
optimistic, it is wrong. So a corridor may declare a typical closure window (MM-MM, inclusive,
may wrap the year) and, inside it, the corridor is treated as impassable with the closure type
`seasonal_typical`.

Honesty about what this is: the windows are the historically usual ones. Actual opening and
closing dates are announced every year by the Border Roads Organisation or the state and have
been moving (BRO has been opening Zojila earlier). A deployment should replace the window with
the announced dates; a caller can plan for a specific date with `travel_date`.
"""

from __future__ import annotations

from datetime import date

MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Broad Indian seasons, used to describe context in explanations — never to score.
SEASONS = {
    1: "winter", 2: "winter", 3: "pre-monsoon", 4: "pre-monsoon", 5: "pre-monsoon",
    6: "south-west monsoon", 7: "south-west monsoon", 8: "south-west monsoon",
    9: "south-west monsoon", 10: "post-monsoon", 11: "post-monsoon", 12: "winter",
}


def parse_window(text: str | None):
    """'11-05' -> (11, 5). Empty or malformed -> None."""
    if not text:
        return None
    try:
        start, end = (int(part) for part in str(text).split("-", 1))
    except (TypeError, ValueError):
        return None
    if not (1 <= start <= 12 and 1 <= end <= 12):
        return None
    return start, end


def months_in_window(window) -> list:
    if window is None:
        return []
    start, end = window
    months, m = [], start
    for _ in range(12):
        months.append(m)
        if m == end:
            break
        m = m % 12 + 1
    return months


def is_closed(window_text: str | None, month: int) -> bool:
    return month in months_in_window(parse_window(window_text))


def describe_window(window_text: str | None) -> str | None:
    window = parse_window(window_text)
    if window is None:
        return None
    return f"{MONTH_NAMES[window[0] - 1]}-{MONTH_NAMES[window[1] - 1]} (typical)"


def season_of(month: int) -> str:
    return SEASONS.get(int(month), "unknown")


def resolve_month(value=None) -> int:
    """Month to evaluate closures for: an int, a date/ISO string, or today."""
    if value is None or value == "":
        return date.today().month
    if isinstance(value, int):
        if 1 <= value <= 12:
            return value
        raise ValueError("month must be 1-12")
    if hasattr(value, "month"):
        return int(value.month)
    text = str(value).strip()
    if text.isdigit():
        return resolve_month(int(text))
    return date.fromisoformat(text[:10]).month
