"""Live refresh: a cheap data-version token, and the poller that watches it.

The owner records a payment on the PC while someone else is looking at the same
numbers on a phone. Without this, the phone keeps showing whatever was true when
its page was opened -- and a stale rent figure looks exactly like a correct one.

Pushing changes (SSE, websockets) would mean holding a worker thread open for
every connected phone, and ThreadingHTTPServer has no thread budget to spare for
that. So each page polls instead. The token is derived from the database file's
size and mtime rather than from a counter in memory, which means it also catches
writes made outside the web server -- `python -m apartment invoice`, or a restore
performed by copying a backup over data/apartment.db.

WAL mode (see db.connect) is what makes the stat cheap and correct: a commit
appends frames to the -wal sidecar, so the sidecar's mtime moves on every write
even when the main file is untouched between checkpoints.
"""

from __future__ import annotations

from pathlib import Path

from .. import db

POLL_MS = 3000


def data_version(db_path: Path | str | None = None) -> str:
    """A token that changes whenever the database changes.

    Opaque by design: callers compare it for equality and never parse it. Missing
    files count as "0" so a database that has not been created yet still yields a
    stable token instead of raising.
    """
    path = Path(db_path) if db_path else db.DEFAULT_DB
    parts = []
    for candidate in (path, path.with_name(path.name + "-wal")):
        try:
            stat = candidate.stat()
        except OSError:
            parts.append("0")
        else:
            parts.append(f"{stat.st_size}.{stat.st_mtime_ns}")
    return "-".join(parts)


# Appended to every page by layout.page(). Two rules keep this from being
# infuriating in practice:
#
#   1. Never reload a form the user has started filling in. The meter sheet is 30
#      rooms of typing; throwing that away to show fresher numbers would be a
#      catastrophic trade. Those pages get an offer to reload instead.
#   2. Stop polling while the tab is hidden, and check once on the way back. A
#      phone left open on the dashboard overnight should not be waking its radio
#      every three seconds.
LIVE_HTML = """<style>
.live-banner{position:fixed;left:50%;bottom:1rem;transform:translateX(-50%);
 z-index:99;border:0;border-radius:999px;padding:.7rem 1.2rem;font:inherit;
 font-weight:600;color:#fff;background:#1f6feb;box-shadow:0 4px 14px rgba(0,0,0,.3);
 cursor:pointer;max-width:calc(100vw - 2rem)}
.live-banner:active{filter:brightness(.9)}
@media print{.live-banner{display:none}}
</style>
<script>
(function () {
  var seen = null, dirty = false, banner = null;

  // Capture phase: catches inputs inside anything, including future markup.
  document.addEventListener('input', function (event) {
    if (event.target && event.target.closest && event.target.closest('form')) dirty = true;
  }, true);
  document.addEventListener('submit', function () { dirty = false; }, true);

  function offerReload() {
    if (banner) return;
    banner = document.createElement('button');
    banner.type = 'button';
    banner.className = 'live-banner';
    banner.textContent = 'มีข้อมูลใหม่ — แตะเพื่อโหลดหน้านี้ใหม่';
    banner.addEventListener('click', function () { location.reload(); });
    document.body.appendChild(banner);
  }

  function check() {
    fetch('/api/version', { cache: 'no-store' })
      .then(function (response) { return response.ok ? response.text() : null; })
      .then(function (version) {
        if (!version) return;
        if (seen === null) { seen = version; return; }  // first poll: baseline only
        if (version === seen) return;
        seen = version;
        if (dirty) offerReload(); else location.reload();
      })
      .catch(function () { /* server restarting or Wi-Fi dropped; try again later */ });
  }

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) check();
  });

  (function tick() {
    if (!document.hidden) check();
    setTimeout(tick, __POLL_MS__);
  })();
})();
</script>"""

LIVE_HTML = LIVE_HTML.replace("__POLL_MS__", str(POLL_MS))
