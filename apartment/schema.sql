-- Schema for the apartment management system (3 floors x 10 rooms).
-- All money columns are INTEGER satang (1 baht = 100 satang). See apartment/money.py
-- and docs/adr/0003-money-as-integer-satang.md.
-- All date columns are TEXT 'YYYY-MM-DD'; all period columns are TEXT 'YYYY-MM'.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS room (
    id        INTEGER PRIMARY KEY,
    code      TEXT    NOT NULL UNIQUE,          -- '101' .. '310'
    floor     INTEGER NOT NULL,                 -- 1..3
    base_rent INTEGER NOT NULL,                 -- satang, the asking rent
    status    TEXT    NOT NULL DEFAULT 'vacant' -- vacant | occupied | maintenance
              CHECK (status IN ('vacant', 'occupied', 'maintenance')),
    note      TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tenant (
    id          INTEGER PRIMARY KEY,
    full_name   TEXT NOT NULL,
    phone       TEXT NOT NULL DEFAULT '',
    national_id TEXT NOT NULL DEFAULT '',
    line_id     TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

-- A lease freezes the commercial terms agreed with one tenant for one room.
-- Rates are nullable: NULL means "use the current default from settings".
CREATE TABLE IF NOT EXISTS lease (
    id               INTEGER PRIMARY KEY,
    room_id          INTEGER NOT NULL REFERENCES room(id),
    tenant_id        INTEGER NOT NULL REFERENCES tenant(id),
    start_date       TEXT    NOT NULL,
    end_date         TEXT,                          -- NULL = open ended
    monthly_rent     INTEGER NOT NULL,              -- snapshot of room.base_rent at signing
    deposit          INTEGER NOT NULL DEFAULT 0,
    deposit_refunded INTEGER NOT NULL DEFAULT 0,
    water_rate       INTEGER,                       -- satang per unit, NULL -> settings
    electric_rate    INTEGER,                       -- satang per unit, NULL -> settings
    common_fee       INTEGER,                       -- satang per month, NULL -> settings
    status           TEXT    NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active', 'ended')),
    ended_on         TEXT,
    note             TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_lease_room   ON lease(room_id, status);
CREATE INDEX IF NOT EXISTS ix_lease_tenant ON lease(tenant_id);

-- One row per room per month: the readings taken on the monthly walk-around.
-- prev is stored (not derived) so a meter swap or a first month stays representable.
CREATE TABLE IF NOT EXISTS meter_reading (
    id            INTEGER PRIMARY KEY,
    room_id       INTEGER NOT NULL REFERENCES room(id),
    period        TEXT    NOT NULL,            -- 'YYYY-MM'
    read_date     TEXT    NOT NULL,
    water_prev    REAL    NOT NULL,
    water_curr    REAL    NOT NULL,
    electric_prev REAL    NOT NULL,
    electric_curr REAL    NOT NULL,
    note          TEXT    NOT NULL DEFAULT '',
    UNIQUE (room_id, period)
);

-- An invoice is an immutable snapshot: once issued, the rates that produced it live
-- in invoice_line, so changing settings later never rewrites history.
-- See docs/adr/0002-invoice-is-an-immutable-snapshot.md.
CREATE TABLE IF NOT EXISTS invoice (
    id         INTEGER PRIMARY KEY,
    number     TEXT    NOT NULL UNIQUE,        -- 'INV-2026-07-101'
    lease_id   INTEGER NOT NULL REFERENCES lease(id),
    room_id    INTEGER NOT NULL REFERENCES room(id),
    period     TEXT    NOT NULL,
    issue_date TEXT    NOT NULL,
    due_date   TEXT    NOT NULL,
    total      INTEGER NOT NULL,               -- satang, always == sum(invoice_line.amount)
    status     TEXT    NOT NULL DEFAULT 'issued'
               CHECK (status IN ('issued', 'void')),
    note       TEXT    NOT NULL DEFAULT '',
    UNIQUE (lease_id, period)
);
CREATE INDEX IF NOT EXISTS ix_invoice_period ON invoice(period);
CREATE INDEX IF NOT EXISTS ix_invoice_room   ON invoice(room_id, period);

CREATE TABLE IF NOT EXISTS invoice_line (
    id          INTEGER PRIMARY KEY,
    invoice_id  INTEGER NOT NULL REFERENCES invoice(id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL               -- rent|water|electric|common|late_fee|other
                CHECK (kind IN ('rent','water','electric','common','late_fee','other')),
    description TEXT    NOT NULL,
    quantity    REAL    NOT NULL DEFAULT 1,
    unit_price  INTEGER NOT NULL,              -- satang
    amount      INTEGER NOT NULL               -- satang
);
CREATE INDEX IF NOT EXISTS ix_line_invoice ON invoice_line(invoice_id);

-- Partial payments are allowed; an invoice's paid state is always derived by summing
-- these rows, never stored on invoice. See apartment/billing.py:settlement.
CREATE TABLE IF NOT EXISTS payment (
    id         INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoice(id),
    paid_on    TEXT    NOT NULL,
    amount     INTEGER NOT NULL,
    method     TEXT    NOT NULL DEFAULT 'transfer'
               CHECK (method IN ('cash','transfer','promptpay','other')),
    reference  TEXT    NOT NULL DEFAULT '',
    note       TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_payment_invoice ON payment(invoice_id);
CREATE INDEX IF NOT EXISTS ix_payment_paid_on ON payment(paid_on);

-- Money going out. Without this the dashboard can only show revenue, not profit.
CREATE TABLE IF NOT EXISTS expense (
    id          INTEGER PRIMARY KEY,
    spent_on    TEXT    NOT NULL,
    category    TEXT    NOT NULL               -- utility|repair|salary|tax|supplies|other
                CHECK (category IN ('utility','repair','salary','tax','supplies','other')),
    description TEXT    NOT NULL,
    amount      INTEGER NOT NULL,
    room_id     INTEGER REFERENCES room(id),   -- NULL = building-wide
    vendor      TEXT    NOT NULL DEFAULT '',
    note        TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_expense_spent_on ON expense(spent_on);
