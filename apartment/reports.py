"""Financial reporting: what the building actually earned.

Two rules hold everywhere in this module:

1. **Cash basis for income.** "รายรับ" always means money received in the period
   (payment.paid_on), never money invoiced. An invoice issued in June and paid in
   July is July income. This is what a landlord's bank statement agrees with.
2. **Invoiced vs collected are reported side by side.** The gap between them is the
   number that matters -- it is arrears, and hiding it inside one "revenue" figure
   is how a building looks profitable while nobody is paying.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from . import billing, money


@dataclass
class MonthlySummary:
    period: str
    invoiced: int = 0  # billed this period (accrual view)
    collected: int = 0  # cash actually received this period
    expenses: int = 0
    rooms_total: int = 0
    rooms_occupied: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)  # invoiced, split by line kind
    by_expense_category: dict[str, int] = field(default_factory=dict)

    @property
    def net(self) -> int:
        """Cash profit: what came in minus what went out."""
        return self.collected - self.expenses

    @property
    def occupancy_rate(self) -> float:
        return self.rooms_occupied / self.rooms_total if self.rooms_total else 0.0

    @property
    def collection_rate(self) -> float:
        """Collected as a share of invoiced. >1 means arrears from earlier months landed."""
        return self.collected / self.invoiced if self.invoiced else 0.0

    @property
    def gap(self) -> int:
        return self.invoiced - self.collected


def monthly_summary(conn: sqlite3.Connection, period: str) -> MonthlySummary:
    summary = MonthlySummary(period=period)

    row = conn.execute(
        "SELECT COALESCE(SUM(total), 0) AS total FROM invoice WHERE period = ? AND status = 'issued'",
        (period,),
    ).fetchone()
    summary.invoiced = row["total"]

    summary.by_kind = {
        r["kind"]: r["amount"]
        for r in conn.execute(
            """
            SELECT il.kind, COALESCE(SUM(il.amount), 0) AS amount
            FROM invoice_line il
            JOIN invoice i ON i.id = il.invoice_id
            WHERE i.period = ? AND i.status = 'issued'
            GROUP BY il.kind
            """,
            (period,),
        )
    }

    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM payment WHERE substr(paid_on, 1, 7) = ?",
        (period,),
    ).fetchone()
    summary.collected = row["total"]

    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM expense WHERE substr(spent_on, 1, 7) = ?",
        (period,),
    ).fetchone()
    summary.expenses = row["total"]

    summary.by_expense_category = {
        r["category"]: r["amount"]
        for r in conn.execute(
            """
            SELECT category, COALESCE(SUM(amount), 0) AS amount
            FROM expense WHERE substr(spent_on, 1, 7) = ?
            GROUP BY category
            """,
            (period,),
        )
    }

    counts = conn.execute(
        "SELECT COUNT(*) AS total, SUM(status = 'occupied') AS occupied FROM room"
    ).fetchone()
    summary.rooms_total = counts["total"] or 0
    summary.rooms_occupied = counts["occupied"] or 0

    return summary


def yearly_table(conn: sqlite3.Connection, year: int) -> list[MonthlySummary]:
    """Twelve rows, one per month -- the P&L view for a whole year."""
    return [monthly_summary(conn, f"{year}-{month:02d}") for month in range(1, 13)]


@dataclass
class ArrearsRow:
    room_code: str
    tenant_name: str
    period: str
    number: str
    due_date: str
    total: int
    paid: int
    days_overdue: int

    @property
    def outstanding(self) -> int:
        return self.total - self.paid

    @property
    def bucket(self) -> str:
        """Aging bucket, the standard 30/60/90 split."""
        if self.days_overdue <= 0:
            return "ยังไม่ครบกำหนด"
        if self.days_overdue <= 30:
            return "1-30 วัน"
        if self.days_overdue <= 60:
            return "31-60 วัน"
        if self.days_overdue <= 90:
            return "61-90 วัน"
        return "เกิน 90 วัน"


BUCKETS = ("ยังไม่ครบกำหนด", "1-30 วัน", "31-60 วัน", "61-90 วัน", "เกิน 90 วัน")


def arrears(conn: sqlite3.Connection, as_of: str) -> list[ArrearsRow]:
    """Every invoice with money still outstanding, worst first.

    This is the collection worklist: who to call today, in the order to call them.
    """
    rows = []
    for r in conn.execute(
        """
        SELECT i.number, i.period, i.due_date, i.total,
               r.code AS room_code, t.full_name AS tenant_name,
               COALESCE((SELECT SUM(p.amount) FROM payment p WHERE p.invoice_id = i.id), 0) AS paid
        FROM invoice i
        JOIN room r   ON r.id = i.room_id
        JOIN lease l  ON l.id = i.lease_id
        JOIN tenant t ON t.id = l.tenant_id
        WHERE i.status = 'issued'
        """
    ):
        if r["paid"] >= r["total"]:
            continue
        rows.append(
            ArrearsRow(
                room_code=r["room_code"],
                tenant_name=r["tenant_name"],
                period=r["period"],
                number=r["number"],
                due_date=r["due_date"],
                total=r["total"],
                paid=r["paid"],
                days_overdue=billing.days_overdue(r["due_date"], as_of),
            )
        )
    rows.sort(key=lambda row: (-row.days_overdue, -row.outstanding))
    return rows


def arrears_aging(conn: sqlite3.Connection, as_of: str) -> dict[str, int]:
    """Outstanding money grouped into aging buckets."""
    totals = {bucket: 0 for bucket in BUCKETS}
    for row in arrears(conn, as_of):
        totals[row.bucket] += row.outstanding
    return totals


def room_board(conn: sqlite3.Connection, period: str, as_of: str) -> list[dict]:
    """One row per room with everything the floor plan needs to be readable at a glance.

    The room grid has to answer three questions in the time it takes to scan it:
    which rooms are empty, who owes money and how much, and who is already settled
    for this month. Assembling that here keeps the view free of joins, and means the
    same numbers can be tested without rendering HTML.

    `outstanding` is every unpaid baht across *all* periods, not just `period` -- a
    tenant two months behind should not look settled because this month's bill has
    not been issued yet.
    """
    owed: dict[str, int] = {}
    overdue: dict[str, int] = {}
    for row in arrears(conn, as_of):
        owed[row.room_code] = owed.get(row.room_code, 0) + row.outstanding
        overdue[row.room_code] = max(overdue.get(row.room_code, 0), row.days_overdue)

    this_period: dict[str, str] = {}
    for r in conn.execute(
        """
        SELECT rm.code AS room_code, i.total,
               COALESCE((SELECT SUM(p.amount) FROM payment p WHERE p.invoice_id = i.id), 0) AS paid
        FROM invoice i
        JOIN room rm ON rm.id = i.room_id
        WHERE i.period = ? AND i.status = 'issued'
        """,
        (period,),
    ):
        this_period[r["room_code"]] = billing.settlement(r["total"], [r["paid"]]).status

    board = []
    for r in conn.execute(
        """
        SELECT rm.id, rm.code, rm.floor, rm.status, rm.base_rent,
               l.id AS lease_id, l.monthly_rent, l.start_date,
               t.full_name AS tenant_name, t.phone AS tenant_phone
        FROM room rm
        LEFT JOIN lease  l ON l.room_id = rm.id AND l.status = 'active'
        LEFT JOIN tenant t ON t.id = l.tenant_id
        ORDER BY rm.floor, rm.code
        """
    ):
        code = r["code"]
        outstanding = owed.get(code, 0)
        occupied = r["lease_id"] is not None

        # `state` drives the colour; `label` is the words. Both, always -- colour
        # alone fails anyone reading in sunlight or with colour-blindness.
        if r["status"] == "maintenance":
            state, label, detail = "maintenance", "ปิดซ่อม", ""
        elif not occupied:
            state, label, detail = "vacant", "ว่าง", "พร้อมให้เช่า"
        elif outstanding > 0:
            state = "owing"
            label = "ค้างชำระ"
            detail = money.fmt(outstanding)
        else:
            settled = this_period.get(code)
            if settled == "paid":
                state, label, detail = "paid", "ชำระแล้ว", ""
            elif settled in ("partial", "unpaid"):
                state, label, detail = "owing", "ค้างชำระ", money.fmt(outstanding)
            else:
                state, label, detail = "occupied", "รอออกบิล", ""

        board.append(
            {
                "code": code,
                "floor": r["floor"],
                "room_status": r["status"],
                "occupied": occupied,
                "tenant_name": r["tenant_name"],
                "tenant_phone": r["tenant_phone"],
                "rent": r["monthly_rent"] if occupied else r["base_rent"],
                "outstanding": outstanding,
                "days_overdue": overdue.get(code, 0),
                "state": state,
                "label": label,
                "detail": detail,
            }
        )
    return board


def room_performance(conn: sqlite3.Connection, year: int) -> list[dict]:
    """Per-room revenue for a year -- which rooms actually earn their keep.

    `months_billed` exposes vacancy: a room invoiced 8 of 12 months was empty for 4,
    and its annual total should be read against that, not against a full year.
    """
    results = []
    for room in conn.execute("SELECT * FROM room ORDER BY floor, code"):
        row = conn.execute(
            """
            SELECT COALESCE(SUM(i.total), 0) AS invoiced,
                   COUNT(i.id)               AS months_billed
            FROM invoice i
            WHERE i.room_id = ? AND i.status = 'issued' AND substr(i.period, 1, 4) = ?
            """,
            (room["id"], str(year)),
        ).fetchone()
        collected = conn.execute(
            """
            SELECT COALESCE(SUM(p.amount), 0) AS collected
            FROM payment p
            JOIN invoice i ON i.id = p.invoice_id
            WHERE i.room_id = ? AND substr(p.paid_on, 1, 4) = ?
            """,
            (room["id"], str(year)),
        ).fetchone()["collected"]
        results.append(
            {
                "room_code": room["code"],
                "floor": room["floor"],
                "status": room["status"],
                "invoiced": row["invoiced"],
                "collected": collected,
                "months_billed": row["months_billed"],
                "outstanding": row["invoiced"] - collected,
            }
        )
    return results


def utility_usage(conn: sqlite3.Connection, period: str) -> list[dict]:
    """Consumption per room, for spotting leaks and meter faults.

    A room whose water jumps far above the building median usually has a running
    toilet, not a thirsty tenant -- worth catching before the bill does.
    """
    rows = []
    for r in conn.execute(
        """
        SELECT m.*, rm.code AS room_code, rm.floor
        FROM meter_reading m
        JOIN room rm ON rm.id = m.room_id
        WHERE m.period = ?
        ORDER BY rm.floor, rm.code
        """,
        (period,),
    ):
        rows.append(
            {
                "room_code": r["room_code"],
                "floor": r["floor"],
                "water_units": round(r["water_curr"] - r["water_prev"], 3),
                "electric_units": round(r["electric_curr"] - r["electric_prev"], 3),
            }
        )
    return rows


def dashboard(conn: sqlite3.Connection, period: str, as_of: str) -> dict:
    """Everything the front page needs, in one call."""
    summary = monthly_summary(conn, period)
    overdue = arrears(conn, as_of)
    return {
        "summary": summary,
        "aging": arrears_aging(conn, as_of),
        "arrears": overdue,
        "arrears_total": sum(row.outstanding for row in overdue),
        "arrears_count": len(overdue),
        "unread_meters": unread_meters(conn, period),
        "uninvoiced": uninvoiced_rooms(conn, period),
    }


def unread_meters(conn: sqlite3.Connection, period: str) -> list[str]:
    """Occupied rooms with no meter reading yet this period."""
    return [
        r["code"]
        for r in conn.execute(
            """
            SELECT rm.code
            FROM lease l
            JOIN room rm ON rm.id = l.room_id
            WHERE l.status = 'active'
              AND NOT EXISTS (
                  SELECT 1 FROM meter_reading m
                  WHERE m.room_id = l.room_id AND m.period = ?
              )
            ORDER BY rm.floor, rm.code
            """,
            (period,),
        )
    ]


def uninvoiced_rooms(conn: sqlite3.Connection, period: str) -> list[str]:
    """Occupied rooms with a reading but no invoice yet this period."""
    return [
        r["code"]
        for r in conn.execute(
            """
            SELECT rm.code
            FROM lease l
            JOIN room rm ON rm.id = l.room_id
            WHERE l.status = 'active'
              AND EXISTS (
                  SELECT 1 FROM meter_reading m
                  WHERE m.room_id = l.room_id AND m.period = ?
              )
              AND NOT EXISTS (
                  SELECT 1 FROM invoice i
                  WHERE i.lease_id = l.id AND i.period = ? AND i.status = 'issued'
              )
            ORDER BY rm.floor, rm.code
            """,
            (period, period),
        )
    ]
