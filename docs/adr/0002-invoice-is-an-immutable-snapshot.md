# ADR-0002: An issued invoice is an immutable snapshot

Status: accepted · 2026-07-22

## Context

Rates change. The building may charge ฿18/unit for water this year and ฿20 next
year; one tenant may have negotiated ฿15 and kept it. If invoices stored only a
foreign key to "the current water rate", then editing the rate in settings would
silently rewrite every invoice ever issued — including ones already printed, handed
to a tenant, and paid.

That failure is invisible: the totals just quietly stop matching the paper.

## Decision

`invoice_line` stores `quantity`, `unit_price`, and `amount` as literal values at the
moment of issue. `invoice.total` is the sum of its lines, written once.

Nothing in the system recalculates an issued invoice from current settings. Changing
a rate in `/settings` affects only invoices generated afterwards.

Corrections are made by **voiding** (`status = 'void'`, number retained) and issuing a
new invoice — never by editing an issued one. An invoice with any payment against it
cannot be voided at all; that path requires recording a refund.

## Consequences

- A printed invoice and the database always agree, permanently.
- `UNIQUE(lease_id, period)` plus the void-instead-of-delete rule means invoice
  numbers are never reused and the audit trail has no holes.
- Re-running invoice generation for a period is safe and idempotent.
- **Cost:** fixing a typo costs two rows instead of an `UPDATE`. This is the point.
- **Cost:** a rate correction cannot be applied retroactively in bulk. If that is ever
  needed, it must be a deliberate, logged migration — not a settings edit.
