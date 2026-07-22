"""Database connection and bootstrap.

One SQLite file, no ORM. `sqlite3.Row` everywhere so callers get dict-like rows and
the SQL stays visible -- the owner of this building can open the same file in any
SQL tool and get identical answers to what the web UI shows.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import money

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
DEFAULT_DB = PROJECT_DIR / "data" / "apartment.db"
SCHEMA_PATH = PACKAGE_DIR / "schema.sql"

FLOORS = 3
ROOMS_PER_FLOOR = 10

# Building defaults. Editable at runtime via the settings table; these are only the
# values a brand-new database starts with.
DEFAULT_SETTINGS = {
    "building_name": "หอพัก",
    "building_address": "",
    "water_rate": str(money.baht(18)),  # per unit
    "electric_rate": str(money.baht(8)),  # per unit
    "common_fee": str(money.baht(0)),  # per month
    "base_rent": str(money.baht(3500)),  # per month, asking rent for a new room
    "deposit_months": "2",
    "due_day": "5",  # rent due on the 5th
    "late_fee_per_day": str(money.baht(50)),
    "late_fee_grace_days": "3",
    "promptpay_id": "",
}


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection with the pragmas this app assumes.

    `check_same_thread=False` because the stdlib HTTP server handles each request on
    a worker thread; every handler opens and closes its own connection, so no
    connection is ever shared across threads in practice.
    """
    path = Path(db_path) if db_path else DEFAULT_DB
    if path != Path(":memory:"):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables and seed the settings row set. Safe to run repeatedly."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO NOTHING",
            (key, value),
        )
    conn.commit()


def seed_rooms(conn: sqlite3.Connection, floors: int = FLOORS, per_floor: int = ROOMS_PER_FLOOR) -> int:
    """Create the room grid: floor 1 -> 101..110, floor 2 -> 201..210, and so on.

    Returns how many rooms were newly created; existing codes are left untouched so
    re-running never overwrites a room whose rent has since been changed.
    """
    base_rent = int(get_settings(conn)["base_rent"])
    created = 0
    for floor in range(1, floors + 1):
        for index in range(1, per_floor + 1):
            code = f"{floor}{index:02d}"
            cursor = conn.execute(
                "INSERT INTO room (code, floor, base_rent, status) VALUES (?, ?, ?, 'vacant') "
                "ON CONFLICT(code) DO NOTHING",
                (code, floor, base_rent),
            )
            created += cursor.rowcount
    conn.commit()
    return created


def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM settings")}


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()
