"""Display formatting shared by every module and template.

Decision D10 requires every value to be computed at full precision and
rounded only here, at render time -- never earlier, and never with Python's
built-in round() (which rounds half-to-even and would display the PDF's own
0.7 x 19.5 = 13.65 worked example as 13.6 instead of the stated 13.7). Every
formatting function in this file rounds half up instead.
"""

from decimal import ROUND_HALF_UP, Decimal


def round_half_up(value, ndigits=0):
    """Round value to ndigits decimal places, rounding an exact .5 up
    instead of Python's default round-half-to-even."""
    quantum = Decimal("1").scaleb(-ndigits)
    rounded = float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))
    return rounded + 0.0  # normalise -0.0 (e.g. from a tiny negative float) to 0.0


def format_number(value, ndigits=1):
    """A plain rounded number with no unit suffix (e.g. rider productivity,
    pi_r/day) -- 1 decimal place by default."""
    return f"{round_half_up(value, ndigits):.{ndigits}f}"


def format_percent(value):
    """Percentages in M1, M2, M3 and reports R1-R4: 1 decimal place."""
    return f"{round_half_up(value, 1):.1f}%"


def format_hours(value):
    """Delivery-time hours: 1 decimal place."""
    return f"{round_half_up(value, 1):.1f} h"


def format_similarity_percent(value):
    """Similarity percentages in M4 and R5: integer (the PDF shows 80%, 91%,
    42%, 16%). value is a fraction in [0, 1], e.g. 0.80, not 80."""
    return f"{round_half_up(value * 100, 0):.0f}%"


def format_currency(value):
    """BDT currency: thousands separators, no decimal places."""
    return f"{round_half_up(value, 0):,.0f}"


def format_date_long(date_str):
    """'2026-07-08' -> '08 July 2026', matching the PDF's report headers."""
    from datetime import datetime
    parsed = datetime.strptime(date_str, "%Y-%m-%d")
    return parsed.strftime("%d %B %Y")


def format_month_long(month_str):
    """'2026-06' -> 'June 2026', matching R3's report header."""
    from datetime import datetime
    parsed = datetime.strptime(month_str, "%Y-%m")
    return parsed.strftime("%B %Y")
