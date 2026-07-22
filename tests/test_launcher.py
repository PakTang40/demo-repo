"""Encoding invariants for the launcher scripts.

Both of these broke in real use, in opposite directions, and neither failure was
obvious from reading the file:

* `เปิดระบบ.bat` must be **ASCII with no BOM**. cmd.exe re-reads a batch file by
  byte offset while `chcp 65001` changes how those bytes decode, so a single Thai
  character anywhere -- even in a REM comment -- desynchronises the parser. The
  symptom was `set "HOST=127.0.0.1"` silently not running, so the launcher called
  `--host ""` and argparse rejected it.

* `tools/stop-server.ps1` must be **UTF-8 with a BOM**. Windows PowerShell 5.1
  reads a BOM-less .ps1 as ANSI, turning every Thai message into mojibake.

See docs/adr/0006-single-instance-restart.md.
"""

import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
LAUNCHER = PROJECT / "เปิดระบบ.bat"
STOP_SCRIPT = PROJECT / "tools" / "stop-server.ps1"
BOM = b"\xef\xbb\xbf"


class TestLauncherBatch(unittest.TestCase):
    def setUp(self):
        self.assertTrue(LAUNCHER.exists(), f"missing launcher: {LAUNCHER}")
        self.raw = LAUNCHER.read_bytes()

    def test_is_pure_ascii(self):
        offenders = [
            (index, byte) for index, byte in enumerate(self.raw) if byte > 127
        ]
        self.assertEqual(
            offenders,
            [],
            "เปิดระบบ.bat must be ASCII-only — non-ASCII bytes corrupt cmd.exe parsing "
            f"after chcp. First offender at byte {offenders[0][0] if offenders else '-'}",
        )

    def test_has_no_bom(self):
        self.assertFalse(self.raw.startswith(BOM), "cmd.exe cannot parse a BOM")

    def test_passes_the_host_as_a_quoted_argument(self):
        """The bug was an empty %HOST%; quoting makes argparse fail loudly, not oddly."""
        text = self.raw.decode("ascii")
        self.assertIn('--host "%HOST%"', text)
        self.assertIn('set "HOST=127.0.0.1"', text)

    def test_stops_a_stale_server_before_starting(self):
        text = self.raw.decode("ascii")
        self.assertIn("stop-server.ps1", text)
        self.assertLess(
            text.index("stop-server.ps1"),
            text.index("apartment serve"),
            "the stale server must be stopped before a new one starts",
        )

    def test_opens_the_browser_from_python_not_from_cmd(self):
        """cmd used to open the browser before the socket was bound — a race."""
        text = self.raw.decode("ascii")
        self.assertIn("--open", text)
        self.assertNotIn("start http", text)
        self.assertNotIn('start "" http', text)


class TestStopScript(unittest.TestCase):
    def setUp(self):
        self.assertTrue(STOP_SCRIPT.exists(), f"missing: {STOP_SCRIPT}")
        self.raw = STOP_SCRIPT.read_bytes()

    def test_has_a_utf8_bom(self):
        self.assertTrue(
            self.raw.startswith(BOM),
            "Windows PowerShell 5.1 reads a BOM-less .ps1 as ANSI and mangles Thai",
        )

    def test_decodes_as_utf8_with_thai_intact(self):
        text = self.raw.decode("utf-8-sig")
        self.assertIn("ปิดระบบเดิมแล้ว", text)

    def test_matches_the_process_by_regex_not_by_adjacent_words(self):
        """`-like '*apartment serve*'` missed `-m apartment --db X serve` and then
        cheerfully reported success.

        Checks the selection line itself, not the whole file -- the comment above it
        quotes the old broken pattern on purpose.
        """
        text = self.raw.decode("utf-8-sig")
        selectors = [
            line
            for line in text.splitlines()
            if "Where-Object" in line and not line.lstrip().startswith("#")
        ]
        self.assertEqual(len(selectors), 1, f"expected one selection line, got {selectors}")
        selector = selectors[0]
        self.assertIn("-match", selector)
        self.assertNotIn("-like", selector)


if __name__ == "__main__":
    unittest.main()
