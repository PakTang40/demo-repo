# CONTEXT — ธุรกิจหอพัก (Apartment Management)

The bounded context is **one building**: 3 floors × 10 rooms = 30 rooms, owned and
operated by one person. Everything here serves the monthly cycle of *read meters →
issue bills → collect rent → know what the building earned*.

## Glossary

Code identifiers are English; everything the owner or a tenant reads is Thai. The
right-hand column is the term that must appear in the UI.

| Term (code)     | Thai (UI)       | Meaning |
| --------------- | --------------- | ------- |
| `room`          | ห้องพัก          | A physical room. Identified by `code`: floor digit + 2-digit index, `101`–`310`. Never renumbered. |
| `tenant`        | ผู้เช่า          | A person. Survives their lease — a returning tenant is the same tenant row. |
| `lease`         | สัญญาเช่า        | The agreement binding one tenant to one room, freezing `monthly_rent` and any negotiated rates. A room has **at most one** `active` lease. |
| `meter_reading` | การจดมิเตอร์      | One room's water and electricity numbers for one `period`. Stores both `prev` and `curr`. |
| `period`        | งวด             | A billing month, `'YYYY-MM'`. The unit everything is grouped by. |
| `invoice`       | ใบแจ้งหนี้        | What a tenant owes for one lease in one period. Immutable once issued (ADR-0002). |
| `invoice_line`  | รายการในบิล      | One charge on an invoice, carrying the `unit_price` used at issue time. |
| `payment`       | การชำระเงิน      | Money received against an invoice. Many payments per invoice are allowed. |
| `expense`       | รายจ่าย          | Money the building spent. Without it the system reports revenue, not profit. |
| `arrears`       | ค้างชำระ         | Outstanding balance on issued invoices, aged in 30/60/90-day buckets. |
| `settlement`    | สถานะการชำระ     | `unpaid` / `partial` / `paid`. **Derived** by summing payments — never a stored column. |
| `satang`        | สตางค์           | The unit every money value is stored in. 1 baht = 100 satang (ADR-0003). |

## Terms deliberately avoided

- **"revenue"** on its own — always say **`invoiced`** (billed) or **`collected`**
  (received). Collapsing the two hides arrears, which is the number that actually
  tells the owner whether the building is healthy.
- **"balance"** — ambiguous between a tenant's and the building's. Use `outstanding`.
- **"unit"** — means a metered unit of water/electricity here, never a room.

## Rules that hold everywhere

1. **Income is cash-basis.** `collected` counts `payment.paid_on` falling in the
   period. An invoice issued in June and paid in July is *July* income, matching the
   bank statement. `invoiced` is the accrual view, reported alongside, never merged.
2. **A room is never double-let.** `repo.start_lease` refuses a second active lease;
   this is the one mistake that silently corrupts a year of invoices.
3. **Never bill a guess.** A room with no meter reading is *skipped* with a reason,
   not billed at zero usage. A first-ever reading is an *opening* reading and bills
   zero units rather than the meter's whole lifetime.
4. **A meter never runs backwards.** `billing.units` raises rather than accept it —
   it is always a typo.
5. **Rates resolve late.** `lease.water_rate` etc. are nullable; `NULL` means "use the
   building default at issue time", a value means this tenant negotiated it.
   `billing.resolve_rates` is the only place that decides.

## Where the decisions are written down

- ADR-0001 — stdlib only, one SQLite file
- ADR-0002 — an issued invoice is an immutable snapshot
- ADR-0003 — money is integer satang
- ADR-0004 — local-first, no authentication
- ADR-0005 — the visual language (ivory/brass/serif, print as a first-class target)
- ADR-0006 — one instance only; restarting must actually restart
