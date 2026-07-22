"""The billing engine: turns a lease + a meter reading into invoice lines.

Everything here is a pure function over plain dataclasses -- no database, no clock,
no config lookups. That is deliberate: this is the part that must be right, so it
must be testable without fixtures. `repo.py` is what reads/writes rows; this module
only decides amounts.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import money

# Line kinds, in the order they should appear on a printed invoice.
KIND_ORDER = ("rent", "water", "electric", "common", "late_fee", "other")

KIND_LABEL_TH = {
    "rent": "ค่าเช่าห้อง",
    "water": "ค่าน้ำ",
    "electric": "ค่าไฟฟ้า",
    "common": "ค่าส่วนกลาง",
    "late_fee": "ค่าปรับชำระล่าช้า",
    "other": "อื่น ๆ",
}


class BillingError(ValueError):
    """Raised when the inputs cannot produce a defensible invoice."""


@dataclass(frozen=True)
class Rates:
    """The rates in force for one lease in one period, already resolved.

    `resolve_rates` produces this from a lease row plus the settings defaults, so
    the rest of the engine never has to know that a NULL means "use the default".
    """

    water_rate: int  # satang per unit
    electric_rate: int  # satang per unit
    common_fee: int  # satang per month
    late_fee_per_day: int = 0  # satang per day overdue
    late_fee_grace_days: int = 0


@dataclass(frozen=True)
class Reading:
    """One month of meter readings for one room."""

    water_prev: float
    water_curr: float
    electric_prev: float
    electric_curr: float

    @property
    def water_units(self) -> float:
        return units(self.water_prev, self.water_curr, "น้ำ")

    @property
    def electric_units(self) -> float:
        return units(self.electric_prev, self.electric_curr, "ไฟฟ้า")


@dataclass
class Line:
    kind: str
    description: str
    quantity: float
    unit_price: int  # satang
    amount: int  # satang


@dataclass
class Draft:
    """An invoice before it is persisted."""

    period: str
    lines: list[Line] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(line.amount for line in self.lines)


def units(prev: float, curr: float, what: str = "มิเตอร์") -> float:
    """Consumption between two meter readings.

    A meter running backwards is always a data-entry mistake, so it raises rather
    than quietly billing a negative amount. A meter that has rolled over past its
    maximum is rare enough at this scale that we want a human to look at it.
    """
    if curr < prev:
        raise BillingError(
            f"ค่า{what}เดือนนี้ ({curr:g}) น้อยกว่าเดือนก่อน ({prev:g}) — "
            "ตรวจสอบเลขมิเตอร์อีกครั้ง"
        )
    return round(curr - prev, 3)


def resolve_rates(lease: dict, defaults: dict) -> Rates:
    """Combine per-lease overrides with the building defaults.

    A lease column of NULL means "whatever the building charges today"; a value
    means this tenant negotiated something and must keep it.
    """

    def pick(key: str) -> int:
        value = lease.get(key)
        return int(defaults[key]) if value is None else int(value)

    return Rates(
        water_rate=pick("water_rate"),
        electric_rate=pick("electric_rate"),
        common_fee=pick("common_fee"),
        late_fee_per_day=int(defaults.get("late_fee_per_day", 0)),
        late_fee_grace_days=int(defaults.get("late_fee_grace_days", 0)),
    )


def build_draft(
    period: str,
    monthly_rent: int,
    reading: Reading,
    rates: Rates,
    extras: list[Line] | None = None,
) -> Draft:
    """The monthly bill for one occupied room.

    Zero-amount lines are still included (a month with no water used should show
    ค่าน้ำ ฿0.00 rather than vanish) except for the common fee, which is omitted
    entirely when the building does not charge one.
    """
    water_units = reading.water_units
    electric_units = reading.electric_units

    lines = [
        Line("rent", KIND_LABEL_TH["rent"], 1, monthly_rent, monthly_rent),
        Line(
            "water",
            f"{KIND_LABEL_TH['water']} ({water_units:g} หน่วย x {money.fmt(rates.water_rate)})",
            water_units,
            rates.water_rate,
            money.multiply(rates.water_rate, water_units),
        ),
        Line(
            "electric",
            f"{KIND_LABEL_TH['electric']} ({electric_units:g} หน่วย x {money.fmt(rates.electric_rate)})",
            electric_units,
            rates.electric_rate,
            money.multiply(rates.electric_rate, electric_units),
        ),
    ]
    if rates.common_fee:
        lines.append(
            Line("common", KIND_LABEL_TH["common"], 1, rates.common_fee, rates.common_fee)
        )
    lines.extend(extras or [])
    return Draft(period=period, lines=lines)


def late_fee(total: int, due_date: str, as_of: str, rates: Rates) -> Line | None:
    """The penalty line for an invoice still unpaid after its grace period.

    Returns None when nothing is owed, so the caller can `if line:` append it.
    """
    if rates.late_fee_per_day <= 0:
        return None
    days = days_overdue(due_date, as_of)
    billable = days - rates.late_fee_grace_days
    if billable <= 0:
        return None
    amount = rates.late_fee_per_day * billable
    return Line(
        "late_fee",
        f"{KIND_LABEL_TH['late_fee']} ({billable} วัน x {money.fmt(rates.late_fee_per_day)})",
        billable,
        rates.late_fee_per_day,
        amount,
    )


def days_overdue(due_date: str, as_of: str) -> int:
    """Whole days past the due date; 0 if not yet due."""
    due = dt.date.fromisoformat(due_date)
    now = dt.date.fromisoformat(as_of)
    return max(0, (now - due).days)


@dataclass(frozen=True)
class Settlement:
    """How much of an invoice is actually settled, derived from its payments."""

    total: int
    paid: int

    @property
    def outstanding(self) -> int:
        return max(0, self.total - self.paid)

    @property
    def overpaid(self) -> int:
        return max(0, self.paid - self.total)

    @property
    def status(self) -> str:
        """unpaid | partial | paid -- never stored, always recomputed."""
        if self.paid <= 0:
            return "unpaid"
        if self.paid < self.total:
            return "partial"
        return "paid"


def settlement(total: int, payments: list[int]) -> Settlement:
    return Settlement(total=total, paid=sum(payments))


def invoice_number(period: str, room_code: str) -> str:
    """'2026-07' + '101' -> 'INV-2026-07-101'. Stable and sortable."""
    return f"INV-{period}-{room_code}"


def period_of(date: str) -> str:
    """'2026-07-15' -> '2026-07'."""
    return date[:7]


def next_period(period: str) -> str:
    year, month = (int(p) for p in period.split("-"))
    return f"{year + 1}-01" if month == 12 else f"{year}-{month + 1:02d}"


def prev_period(period: str) -> str:
    year, month = (int(p) for p in period.split("-"))
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def due_date_for(period: str, due_day: int) -> str:
    """The day rent for `period` must be in hand.

    Rent for a period is due inside that same month; a due_day past the end of a
    short month clamps to the last day rather than rolling into the next one.
    """
    year, month = (int(p) for p in period.split("-"))
    last_day = _days_in_month(year, month)
    return f"{year}-{month:02d}-{min(due_day, last_day):02d}"


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (dt.date(year, month + 1, 1) - dt.timedelta(days=1)).day
