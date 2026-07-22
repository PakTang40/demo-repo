# ADR-0006: One instance only, and restarting must actually restart

Status: accepted · 2026-07-22

## Context

The owner reported that after the interface was redesigned, double-clicking
`เปิดระบบ.bat` still showed the old version — with no error message of any kind.

The cause was a Windows-specific socket behaviour interacting with a Python default:

- `http.server.HTTPServer` sets **`allow_reuse_address = True`**.
- On Linux, `SO_REUSEADDR` only permits binding a port left in `TIME_WAIT`.
- On **Windows** it also permits binding a port that is *actively being listened on*.
  The second process binds successfully; the original keeps accepting connections.

So each double-click started another server that printed "พร้อมใช้งานแล้ว" and then
served nobody, while the browser talked to the first process launched — running
whatever code was on disk at that moment. Four such processes were found running.
The launcher also opened the browser *before* starting Python, so there was nothing
to notice even if the bind had failed.

The symptom is the worst possible shape: the app appears to ignore every change, and
no error is produced anywhere to point at the cause.

## Decision

1. **`_Server.allow_reuse_address = False`.** A port already in use must be a hard,
   immediate failure. Restart correctness is worth far more here than the
   convenience of skipping `TIME_WAIT`, on a server one person restarts by hand.
2. **Catch `EADDRINUSE` and explain it in Thai**, naming the likely cause (a server
   left running), the fix, and the `--port` escape hatch. Exit non-zero. Never print
   a success banner on a failed start.
3. **`เปิดระบบ.bat` stops any existing `apartment serve` process before starting.**
   For a single-operator local app, a double-click means "give me the app, now" —
   not "add a second one". Auto-restart is the correct semantics.
4. **Python opens the browser** (`serve --open`), after the socket is bound. The
   launcher no longer races the server.
5. **All HTML is sent `Cache-Control: no-store`.** Every page is live financial data
   with the CSS inlined, so a cached copy is always both stale and wrong — and
   produces this same "it didn't update" symptom by a different route.

## Consequences

- A stale server now announces itself instead of hiding; `tests/test_server_startup.py`
  asserts the failure is loud, in Thai, actionable, and never claims success.
- Running two buildings side by side requires explicit `--port`, which is correct —
  it should be a deliberate act, not something that happens by accident.
- **Cost:** the launcher force-stops processes matched by command line. The match
  lives in `tools/stop-server.ps1` and is the regex `-m\s+apartment\b.*\bserve\b` —
  narrow enough never to touch unrelated Python work, but tolerant of global flags
  sitting between the two words (`python -m apartment --db other.db serve`). The
  first attempt used the wildcard `*apartment serve*`, which required the words to be
  adjacent: it silently matched nothing and reported success. **A cleanup step that
  cannot find its target must not be able to report success** — verify a kill by PID,
  never by re-running the same query that selected it.
- **Cost:** the stop script must be saved as **UTF-8 with BOM**. Windows PowerShell
  5.1 reads a BOM-less `.ps1` as ANSI, which turns every Thai message into mojibake.
  Re-check the first three bytes are `EF BB BF` after editing that file.
- **Cost:** `เปิดระบบ.bat` must be **ASCII with no BOM** — the exact opposite rule,
  for the file sitting next to it. cmd.exe re-reads a batch file by byte offset while
  `chcp 65001` changes how those bytes decode, so one Thai character anywhere (a REM
  comment counts) desynchronises the parser: `set "HOST=127.0.0.1"` silently does not
  run, the launcher calls `--host ""`, and argparse rejects it. Putting friendly Thai
  text in the launcher is exactly what broke it. **All Thai output belongs in the
  `.ps1` or in Python.**

`tests/test_launcher.py` asserts both encoding rules, so the next edit to either file
fails the suite instead of failing on the owner's screen.
- **General lesson:** when a user says "it looks like nothing updated", check whether
  the code in memory is the code on disk *before* touching the code. Process state
  and browser cache are both able to fake a broken deploy.
