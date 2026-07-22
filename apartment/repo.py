"""Data access and the write operations that combine billing with persistence.

The split that matters: `billing.py` decides amounts, this module decides what gets
stored. Anything here that computes money delegates to `billing`, so there is exactly
one place where a rate is turned into an amount.
"""

from __future__ import annotations

import datetime as dt
import sqlite3

from . import billing, db
from .billing import BillingError, Line, Reading

# ---------------------------------------------------------------- rooms & tenants


def rooms(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """All rooms with their current tenant, ordered as they appear in the building."""
    return list(
        conn.execute(
            """
            SELECT r.*,
                   l.id        AS lease_id,
                   l.monthly_rent,
                   l.start_date,
                   t.id        AS tenant_id,
                   t.full_name AS tenant_name,
                   t.phone     AS tenant_phone
            FROM room r
            LEFT JOIN lease  l ON l.room_id = r.id AND l.status = 'active'
            LEFT JOIN tenant t ON t.id = l.tenant_id
            ORDER BY r.floor, r.code
            """
        )
    )


def room_by_code(conn: sqlite3.Connection, code: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM room WHERE code = ?", (code,)).fetchone()


def add_tenant(conn: sqlite3.Connection, full_name: str, **fields) -> int:
    cursor = conn.execute(
        "INSERT INTO tenant (full_name, phone, national_id, line_id, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            full_name,
            fields.get("phone", ""),
            fields.get("national_id", ""),
            fields.get("line_id", ""),
            fields.get("note", ""),
            fields.get("created_at", dt.date.today().isoformat()),
        ),
    )
    conn.commit()
    return cursor.lastrowid


# ---------------------------------------------------------------------- leases


def start_lease(
    conn: sqlite3.Connection,
    room_id: int,
    tenant_id: int,
    start_date: str,
    monthly_rent: int | None = None,
    deposit: int | None = None,
    **overrides,
) -> int:
    """Move a tenant in.

    Refuses if the room already has an active lease -- double-booking a room is the
    one mistake that silently corrupts a whole year of invoices.
    """
    existing = conn.execute(
        "SELECT id FROM lease WHERE room_id = ? AND status = 'active'", (room_id,)
    ).fetchone()
    if existing:
        raise BillingError(f"ห้องนี้มีสัญญาเช่าที่ยังไม่สิ้นสุดอยู่แล้ว (lease #{existing['id']})")

    room = conn.execute("SELECT * FROM room WHERE id = ?", (room_id,)).fetchone()
    if room is None:
        raise BillingError(f"ไม่พบห้อง id={room_id}")

    settings = db.get_settings(conn)
    rent = room["base_rent"] if monthly_rent is None else monthly_rent
    if deposit is None:
        deposit = rent * int(settings.get("deposit_months", 2))

    cursor = conn.execute(
        """
        INSERT INTO lease (room_id, tenant_id, start_date, end_date, monthly_rent,
                           deposit, water_rate, electric_rate, common_fee, status, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """,
        (
            room_id,
            tenant_id,
            start_date,
            overrides.get("end_date"),
            rent,
            deposit,
            overrides.get("water_rate"),
            overrides.get("electric_rate"),
            overrides.get("common_fee"),
            overrides.get("note", ""),
        ),
    )
    conn.execute("UPDATE room SET status = 'occupied' WHERE id = ?", (room_id,))
    conn.commit()
    return cursor.lastrowid


def end_lease(conn: sqlite3.Connection, lease_id: int, ended_on: str, deposit_refunded: int = 0) -> None:
    """Move a tenant out and return the room to the vacant pool."""
    lease = conn.execute("SELECT * FROM lease WHERE id = ?", (lease_id,)).fetchone()
    if lease is None:
        raise BillingError(f"ไม่พบสัญญาเช่า id={lease_id}")
    conn.execute(
        "UPDATE lease SET status = 'ended', ended_on = ?, deposit_refunded = ? WHERE id = ?",
        (ended_on, deposit_refunded, lease_id),
    )
    conn.execute("UPDATE room SET status = 'vacant' WHERE id = ?", (lease["room_id"],))
    conn.commit()


def active_leases(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT l.*, r.code AS room_code, r.floor, t.full_name AS tenant_name
            FROM lease l
            JOIN room r   ON r.id = l.room_id
            JOIN tenant t ON t.id = l.tenant_id
            WHERE l.status = 'active'
            ORDER BY r.floor, r.code
            """
        )
    )


# --------------------------------------------------------------- meter readings


def save_reading(
    conn: sqlite3.Connection,
    room_id: int,
    period: str,
    water_curr: float,
    electric_curr: float,
    read_date: str | None = None,
    water_prev: float | None = None,
    electric_prev: float | None = None,
    note: str = "",
) -> int:
    """Record this month's meter numbers for one room.

    `prev` defaults to last month's `curr`, which is what the owner wants 11 months
    out of 12. When there is *no* prior month, prev defaults to `curr` -- i.e. the
    first reading for a room is treated as an opening reading and bills zero units.
    Defaulting to 0 instead would bill the tenant for every unit the meter has
    counted since it was installed, so the safe direction is to under-bill once and
    let the owner enter the real opening number (the meter sheet exposes a field
    for exactly that).

    Re-saving the same period updates in place rather than creating a duplicate.
    """
    if water_prev is None or electric_prev is None:
        previous = conn.execute(
            "SELECT water_curr, electric_curr FROM meter_reading WHERE room_id = ? AND period = ?",
            (room_id, billing.prev_period(period)),
        ).fetchone()
        if water_prev is None:
            water_prev = previous["water_curr"] if previous else water_curr
        if electric_prev is None:
            electric_prev = previous["electric_curr"] if previous else electric_curr

    # Validate before writing so a typo never lands in the table.
    billing.units(water_prev, water_curr, "น้ำ")
    billing.units(electric_prev, electric_curr, "ไฟฟ้า")

    cursor = conn.execute(
        """
        INSERT INTO meter_reading (room_id, period, read_date, water_prev, water_curr,
                                   electric_prev, electric_curr, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(room_id, period) DO UPDATE SET
            read_date     = excluded.read_date,
            water_prev    = excluded.water_prev,
            water_curr    = excluded.water_curr,
            electric_prev = excluded.electric_prev,
            electric_curr = excluded.electric_curr,
            note          = excluded.note
        """,
        (
            room_id,
            period,
            read_date or dt.date.today().isoformat(),
            water_prev,
            water_curr,
            electric_prev,
            electric_curr,
            note,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def readings_for(conn: sqlite3.Connection, period: str) -> dict[int, sqlite3.Row]:
    """{room_id: reading} for one period."""
    return {
        row["room_id"]: row
        for row in conn.execute("SELECT * FROM meter_reading WHERE period = ?", (period,))
    }


# --------------------------------------------------------------------- invoices


def generate_invoices(conn: sqlite3.Connection, period: str, issue_date: str | None = None) -> dict:
    """Issue the monthly invoice for every occupied room that has a meter reading.

    Idempotent: a room already invoiced for this period is skipped, not duplicated
    (the UNIQUE(lease_id, period) constraint is the backstop). Rooms missing a
    reading are reported as skipped rather than billed at zero usage -- billing a
    tenant ฿0 for water is worse than telling the owner to go read the meter.
    """
    issue_date = issue_date or dt.date.today().isoformat()
    settings = db.get_settings(conn)
    due = billing.due_date_for(period, int(settings.get("due_day", 5)))
    readings = readings_for(conn, period)

    created: list[str] = []
    skipped: list[str] = []

    for lease in active_leases(conn):
        room_code = lease["room_code"]
        already = conn.execute(
            "SELECT id FROM invoice WHERE lease_id = ? AND period = ?", (lease["id"], period)
        ).fetchone()
        if already:
            skipped.append(f"{room_code}: ออกบิลแล้ว")
            continue

        reading = readings.get(lease["room_id"])
        if reading is None:
            skipped.append(f"{room_code}: ยังไม่ได้จดมิเตอร์")
            continue

        rates = billing.resolve_rates(dict(lease), settings)
        try:
            draft = billing.build_draft(
                period=period,
                monthly_rent=lease["monthly_rent"],
                reading=Reading(
                    water_prev=reading["water_prev"],
                    water_curr=reading["water_curr"],
                    electric_prev=reading["electric_prev"],
                    electric_curr=reading["electric_curr"],
                ),
                rates=rates,
            )
        except BillingError as exc:
            skipped.append(f"{room_code}: {exc}")
            continue

        save_draft(conn, lease, draft, issue_date=issue_date, due_date=due)
        created.append(room_code)

    return {"period": period, "created": created, "skipped": skipped}


def save_draft(
    conn: sqlite3.Connection,
    lease: sqlite3.Row,
    draft: billing.Draft,
    issue_date: str,
    due_date: str,
) -> int:
    """Persist a draft as an issued invoice plus its lines, in one transaction."""
    number = billing.invoice_number(draft.period, lease["room_code"])
    with conn:  # rolls back both statements if the lines fail to insert
        cursor = conn.execute(
            """
            INSERT INTO invoice (number, lease_id, room_id, period, issue_date, due_date,
                                 total, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'issued')
            """,
            (
                number,
                lease["id"],
                lease["room_id"],
                draft.period,
                issue_date,
                due_date,
                draft.total,
            ),
        )
        invoice_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO invoice_line (invoice_id, kind, description, quantity, unit_price, amount) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (invoice_id, l.kind, l.description, l.quantity, l.unit_price, l.amount)
                for l in draft.lines
            ],
        )
    return invoice_id


def invoices(conn: sqlite3.Connection, period: str | None = None) -> list[sqlite3.Row]:
    """Invoices with their settled amount joined in, newest period first."""
    sql = """
        SELECT i.*,
               r.code AS room_code,
               r.floor,
               t.full_name AS tenant_name,
               COALESCE((SELECT SUM(p.amount) FROM payment p WHERE p.invoice_id = i.id), 0) AS paid
        FROM invoice i
        JOIN room r   ON r.id = i.room_id
        JOIN lease l  ON l.id = i.lease_id
        JOIN tenant t ON t.id = l.tenant_id
        WHERE i.status = 'issued'
    """
    params: tuple = ()
    if period:
        sql += " AND i.period = ?"
        params = (period,)
    sql += " ORDER BY i.period DESC, r.floor, r.code"
    return list(conn.execute(sql, params))


def invoice_detail(conn: sqlite3.Connection, invoice_id: int) -> dict | None:
    """One invoice with everything needed to print it."""
    header = conn.execute(
        """
        SELECT i.*, r.code AS room_code, r.floor,
               t.full_name AS tenant_name, t.phone AS tenant_phone
        FROM invoice i
        JOIN room r   ON r.id = i.room_id
        JOIN lease l  ON l.id = i.lease_id
        JOIN tenant t ON t.id = l.tenant_id
        WHERE i.id = ?
        """,
        (invoice_id,),
    ).fetchone()
    if header is None:
        return None
    lines = list(
        conn.execute("SELECT * FROM invoice_line WHERE invoice_id = ? ORDER BY id", (invoice_id,))
    )
    payments = list(
        conn.execute("SELECT * FROM payment WHERE invoice_id = ? ORDER BY paid_on", (invoice_id,))
    )
    return {
        "invoice": header,
        "lines": lines,
        "payments": payments,
        "settlement": billing.settlement(header["total"], [p["amount"] for p in payments]),
    }


def void_invoice(conn: sqlite3.Connection, invoice_id: int, reason: str) -> None:
    """Cancel an invoice. Never delete -- the number stays taken and auditable."""
    paid = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM payment WHERE invoice_id = ?", (invoice_id,)
    ).fetchone()["total"]
    if paid:
        raise BillingError("ยกเลิกบิลที่มีการชำระเงินแล้วไม่ได้ — ให้บันทึกการคืนเงินแทน")
    conn.execute("UPDATE invoice SET status = 'void', note = ? WHERE id = ?", (reason, invoice_id))
    conn.commit()


def apply_late_fees(conn: sqlite3.Connection, as_of: str | None = None) -> list[str]:
    """Add a late-fee line to every overdue invoice that does not have one yet.

    Run on demand, not automatically -- whether to actually charge a late fee is a
    landlord's judgement call, so the system computes it and waits to be told.
    """
    as_of = as_of or dt.date.today().isoformat()
    settings = db.get_settings(conn)
    touched: list[str] = []

    for inv in invoices(conn):
        settled = billing.settlement(inv["total"], [inv["paid"]])
        if settled.outstanding <= 0:
            continue
        has_fee = conn.execute(
            "SELECT 1 FROM invoice_line WHERE invoice_id = ? AND kind = 'late_fee'", (inv["id"],)
        ).fetchone()
        if has_fee:
            continue

        lease = conn.execute("SELECT * FROM lease WHERE id = ?", (inv["lease_id"],)).fetchone()
        rates = billing.resolve_rates(dict(lease), settings)
        line = billing.late_fee(inv["total"], inv["due_date"], as_of, rates)
        if line is None:
            continue
        with conn:
            conn.execute(
                "INSERT INTO invoice_line (invoice_id, kind, description, quantity, unit_price, amount) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (inv["id"], line.kind, line.description, line.quantity, line.unit_price, line.amount),
            )
            conn.execute(
                "UPDATE invoice SET total = total + ? WHERE id = ?", (line.amount, inv["id"])
            )
        touched.append(f"{inv['room_code']} +{line.amount}")
    return touched


# --------------------------------------------------------------------- payments


def record_payment(
    conn: sqlite3.Connection,
    invoice_id: int,
    amount: int,
    paid_on: str | None = None,
    method: str = "transfer",
    reference: str = "",
    note: str = "",
) -> int:
    if amount <= 0:
        raise BillingError("จำนวนเงินที่ชำระต้องมากกว่า 0")
    invoice = conn.execute("SELECT id FROM invoice WHERE id = ?", (invoice_id,)).fetchone()
    if invoice is None:
        raise BillingError(f"ไม่พบใบแจ้งหนี้ id={invoice_id}")
    cursor = conn.execute(
        "INSERT INTO payment (invoice_id, paid_on, amount, method, reference, note) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (invoice_id, paid_on or dt.date.today().isoformat(), amount, method, reference, note),
    )
    conn.commit()
    return cursor.lastrowid


# --------------------------------------------------------------------- expenses


def record_expense(
    conn: sqlite3.Connection,
    spent_on: str,
    category: str,
    description: str,
    amount: int,
    room_id: int | None = None,
    vendor: str = "",
    note: str = "",
) -> int:
    cursor = conn.execute(
        "INSERT INTO expense (spent_on, category, description, amount, room_id, vendor, note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (spent_on, category, description, amount, room_id, vendor, note),
    )
    conn.commit()
    return cursor.lastrowid


def expenses(conn: sqlite3.Connection, period: str | None = None) -> list[sqlite3.Row]:
    sql = """
        SELECT e.*, r.code AS room_code
        FROM expense e
        LEFT JOIN room r ON r.id = e.room_id
    """
    params: tuple = ()
    if period:
        sql += " WHERE substr(e.spent_on, 1, 7) = ?"
        params = (period,)
    sql += " ORDER BY e.spent_on DESC, e.id DESC"
    return list(conn.execute(sql, params))
