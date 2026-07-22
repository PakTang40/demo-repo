# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A management system for **one apartment building: 3 floors × 10 rooms = 30 rooms**,
operated by its owner alone. It covers the monthly cycle — read meters, issue
invoices, collect rent, record expenses, report what the building earned.

Read **`CONTEXT.md`** before touching domain logic. It holds the glossary (the Thai
term for every code identifier), the terms this project deliberately avoids, and the
five invariants that hold everywhere. `docs/adr/` holds the four decisions that
explain why the code looks the way it does.

## Commands

```powershell
python -m unittest discover -s tests -t .              # full suite (89 tests, ~0.2s)
python -m unittest tests.test_billing                  # one module
python -m unittest tests.test_web.TestFormHandlers     # one class
python -m unittest tests.test_billing.TestLateFee.test_within_grace_period_is_free  # one test
python -m unittest discover -s tests -t . -v           # verbose

python -m apartment serve                # run the app -> http://localhost:8765
python -m apartment serve --host 0.0.0.0 # also reachable from a phone on the LAN
python -m apartment --db path\to.db serve   # any command can target another database
python -m apartment init                 # create schema + the 30 rooms
python -m apartment invoice 2026-07      # generate a period's invoices
python -m apartment report --period 2026-07
python -m apartment export --year 2026   # xlsx
python -m apartment backup
```

There is no build, no lint config, and no package manager step — see ADR-0001.
`เปิดระบบ.bat` is the owner's double-click launcher; it force-stops any running
`apartment serve` process first, because a second instance used to bind the same port
silently on Windows and leave the *old* process answering (ADR-0006). If a change
appears not to take effect, check for a stale server before suspecting the code.

Tests run against `:memory:` databases and never touch `data/apartment.db`. When
running the server manually, prefer `--db` with a scratch path so you never write to
the owner's live data.

## Architecture

The layering is the important thing, and it is enforced by what each module is
allowed to import:

```
billing.py   pure functions + dataclasses. No DB, no clock, no settings lookup.
             Decides *amounts*: units(), resolve_rates(), build_draft(),
             late_fee(), settlement(). This is the part that must be correct.
     ↑
repo.py      decides *what gets stored*. Owns all SQL writes and the multi-step
             operations (start_lease, generate_invoices, apply_late_fees).
             Every amount it writes comes from billing — it never does arithmetic
             on money itself.
     ↑
reports.py   read-only aggregation. Returns dataclasses/dicts, never HTML.
             `room_board()` is the one to reach for when a view needs per-room
             state — it resolves occupancy, arrears and this month's settlement
             into a single honest `state`/`label` per room, so views never
             re-derive that from joins.
     ↑
web/         pages.py + finance.py render HTML strings; server.py is routing,
             form parsing, and POST/Redirect/GET. Pages take (conn, params) and
             know nothing about the request object.
```

`money.py` sits under everything: **all money is `int` satang**, converted only at
the edges (ADR-0003). `db.py` owns the connection, `schema.sql`, and the settings
defaults. `excel.py` is the only consumer of a third-party library (`openpyxl`).

Adding a feature usually means touching one layer. Adding a new charge type, for
example, is a `Line` with a new `kind` in `billing.py`, the `CHECK` constraint in
`schema.sql`, and a column in the Excel export — not a change to the web layer.

### The three things that are easy to get wrong

1. **Never recalculate an issued invoice.** `invoice_line` stores the `unit_price`
   used at issue time; changing a rate in settings must not alter history. Corrections
   are void-and-reissue. (ADR-0002)
2. **`invoiced` and `collected` are different numbers and must stay side by side.**
   Income is cash-basis (`payment.paid_on`), so a June invoice paid in July is July
   income. Any report that merges them into one "revenue" figure hides arrears.
3. **Settlement status is derived, never stored.** `invoice.status` is only
   `issued`/`void`; paid/partial/unpaid comes from summing payments via
   `billing.settlement`.

### Request flow

`server.Handler._dispatch` looks up `(method, path)` in `ROUTES`, opens a fresh
connection per request, and calls the handler. Handlers return either an HTML string
or a `Redirect`. `AppError` and `BillingError` are caught and bounced back to the
referring page as a flash message in the query string — they are messages for the
owner, so they are written in Thai. Anything else renders a traceback page.

Every route is covered by `tests/test_web.py`, which calls handlers directly rather
than over a socket; `TestRouteTable` asserts every nav link has a matching GET route.

## Conventions

- **Thai in the UI, English in the code.** Every string the owner or a tenant reads
  is Thai — including error messages and CLI output. Identifiers, table names, and
  comments are English. Use the glossary in `CONTEXT.md`, not a synonym.
- **No template engine.** Pages are f-strings; `layout.esc()` on every interpolated
  value is the whole XSS story. `layout.py` holds the CSS and the shared components
  (`page`, `tile`, `flash`, `baht_cell`, `status_pill`, `eyebrow`).
- **Visual language is ADR-0005** — warm ivory ground, brass as the only accent,
  serif for headings and headline figures, hairlines, generous space. Build pages
  from the shared components rather than adding inline styles, or it decays one page
  at a time. Any money column needs `lining-nums tabular-nums`; the serif stack
  defaults to old-style figures that wreck a number column.
- **Status is words plus colour, never colour alone** (ADR-0005, amended). On an
  operational screen legibility beats refinement every time — this was learned the
  hard way on the floor plan.
- **Fail toward under-billing.** A room with no reading is skipped with a reason
  rather than billed at zero usage; a first-ever reading is an opening reading and
  bills zero units rather than the meter's lifetime. Never invent a number a tenant
  will be charged for.
- Money on screen goes through `money.fmt`; money out of a form goes through
  `server.money_field`.

## Workspace conventions (inherited from `../CLAUDE.md`)

- Issues and PRDs are local markdown under `.scratch/<feature-slug>/`; there is no git
  remote. See `../docs/agents/issue-tracker.md`.
- Triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`,
  `wontfix`.
- Single-context layout: one `CONTEXT.md` + `docs/adr/` at this project's root.

## Live data

`data/apartment.db` is the business's real records and is gitignored along with the
whole `data/` directory. Back it up by copying that one file. Never delete or
overwrite it while testing.
