"""Money handling: every amount in this system is an integer number of satang.

Rationale in docs/adr/0003-money-as-integer-satang.md. The short version: floats
lose baht over a year of 30 rooms, and SQLite has no decimal type, so we keep the
smallest unit as an int and only format at the edges.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

SATANG_PER_BAHT = 100


def baht(amount) -> int:
    """Convert a baht amount (str/int/float/Decimal) to satang.

    Rounds half-up to the satang, the convention Thai invoices are read with.
    """
    return int((Decimal(str(amount)) * SATANG_PER_BAHT).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_baht(satang: int) -> Decimal:
    """Exact baht value of a satang amount, for display or export."""
    return (Decimal(satang) / SATANG_PER_BAHT).quantize(Decimal("0.01"))


def fmt(satang: int, symbol: bool = True) -> str:
    """Format satang as Thai baht: 1234567 -> '฿12,345.67'."""
    value = to_baht(satang)
    sign = "-" if value < 0 else ""
    text = f"{abs(value):,.2f}"
    return f"{sign}฿{text}" if symbol else f"{sign}{text}"


def multiply(unit_price: int, quantity: float) -> int:
    """unit_price (satang) x quantity (may be fractional, e.g. metered units).

    Rounds half-up so a 12.5-unit water reading never silently loses a satang.
    """
    product = Decimal(unit_price) * Decimal(str(quantity))
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
