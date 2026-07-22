# ADR-0003: Money is an integer number of satang

Status: accepted · 2026-07-22

## Context

SQLite has no decimal type. Storing baht as `REAL` means every amount goes through
binary floating point, where `0.1 + 0.2 != 0.3`. At 30 rooms × 12 months × several
line items, those errors accumulate into a year-end total that is off by a few baht
and cannot be reconciled against a bank statement — the worst kind of bug, because it
looks like an accounting mistake rather than a software one.

Metered utilities make it worse: a water reading can legitimately be fractional
(12.5 units), so amounts genuinely need rounding rather than truncation.

## Decision

Every money value in the database and in Python is an **`int` of satang**
(1 baht = 100 satang). Conversion happens only at the edges:

- `money.baht(x)` — baht in (from a form or a literal), satang out.
- `money.to_baht(satang)` — exact `Decimal` for display and Excel export.
- `money.fmt(satang)` — the display string, e.g. `฿3,500.00`.
- `money.multiply(unit_price, quantity)` — the only place a rate meets a quantity.

All rounding is `ROUND_HALF_UP` via `Decimal`, which is how a Thai invoice is read.
Banker's rounding would surprise the owner and the tenant.

## Consequences

- Totals are exact. `invoice.total == sum(invoice_line.amount)` holds as integer
  arithmetic, so it can be asserted in tests and trusted in reports.
- Excel export converts back to a real float in baht with a `#,##0.00` format, so the
  workbook sums correctly rather than shipping strings.
- **Cost:** every read of a money column needs formatting before display, and every
  form field needs `money_field()` on the way in. Forgetting either is visible
  immediately (a raw `350000` on screen), which is why it stays cheap.
