# ADR-0001: SQLite in one file, and no third-party dependencies

Status: accepted · 2026-07-22

## Context

The system runs on the owner's own Windows PC and is operated by the owner alone.
The machine has Python 3.14.4 with `numpy`, `matplotlib`, `openpyxl`, `python-docx`
and a few document libraries already installed — but no web framework, no database
server, and no Node toolchain in use for this project.

Python 3.14 was newly released; several compiled web stacks (pydantic-core and the
frameworks built on it) could not be relied on to have wheels for `cp314`. Any stack
requiring `pip install` also introduces an upgrade path the owner has to maintain
forever, on a machine where a broken dependency means rent cannot be billed.

## Decision

Build on the standard library only:

- **`sqlite3`** for storage — one file at `data/apartment.db`.
- **`http.server.ThreadingHTTPServer`** for the local web UI.
- **`openpyxl`** for Excel export (already installed, pure Python).

No pip install step. No virtualenv required. `python -m apartment serve` is the
whole runtime.

## Consequences

- The system keeps working after an OS reinstall as long as Python is present.
- Backup is `copy data/apartment.db somewhere-else` — the owner can verify a backup
  by looking at one file's size and date.
- The same file opens in any SQL tool, so the owner (who works in SQL) can answer
  ad-hoc questions the UI does not cover, and always get numbers that agree with it.
- **Cost:** `http.server` is single-process and has no auth, sessions, or CSRF
  protection. That is acceptable only because of ADR-0004. If this ever needs to be
  reachable from the internet, this decision must be reopened, not patched.
- **Cost:** no ORM means the SQL is hand-written. At this schema size (8 tables) that
  is a feature — the queries in `reports.py` are readable as reports.
