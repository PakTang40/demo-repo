"""The `export` command and the /excel launcher route.

This is the one output that leaves the building: a workbook mailed to an
accountant or opened on a phone. It has to be a real Excel file, and it has to
fail in a way the owner can act on when Excel is sitting on the previous one.
"""

import io
import contextlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from apartment import db
from apartment.__main__ import main

PROJECT = Path(__file__).resolve().parent.parent
LAUNCHER = PROJECT / "เปิดระบบ.bat"


class TestExportCommand(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.db_path = Path(self.dir.name) / "apartment.db"
        conn = db.connect(self.db_path)
        db.init_db(conn)
        db.seed_rooms(conn)
        conn.close()
        self.target = Path(self.dir.name) / "out.xlsx"

    def run_export(self, *extra):
        argv = ["--db", str(self.db_path), "export", "--out", str(self.target), *extra]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(argv)
        return code, out.getvalue()

    def test_writes_a_real_excel_workbook(self):
        code, _ = self.run_export()
        self.assertEqual(code, 0)
        self.assertTrue(zipfile.is_zipfile(self.target), "an .xlsx is an OOXML zip")
        with zipfile.ZipFile(self.target) as archive:
            names = archive.namelist()
        self.assertIn("xl/workbook.xml", names)
        self.assertTrue([n for n in names if n.startswith("xl/worksheets/")])

    def test_does_not_open_anything_unless_asked(self):
        with mock.patch("apartment.__main__.open_in_default_app") as opener:
            self.run_export()
        opener.assert_not_called()

    def test_open_flag_hands_the_file_to_excel(self):
        with mock.patch("apartment.__main__.open_in_default_app") as opener:
            self.run_export("--open")
        opener.assert_called_once()
        self.assertEqual(Path(opener.call_args[0][0]), self.target)

    def test_a_file_locked_by_excel_fails_with_advice_not_a_traceback(self):
        """The second export of the day, with the first still open in Excel."""
        with mock.patch.object(Path, "write_bytes", side_effect=PermissionError(13, "locked")):
            code, printed = self.run_export()
        self.assertEqual(code, 1)
        self.assertIn("Excel", printed)
        self.assertIn(self.target.name, printed)

    def test_a_locked_file_is_not_opened_afterwards(self):
        """Opening the stale workbook would show last month's numbers as current."""
        with mock.patch.object(Path, "write_bytes", side_effect=PermissionError(13, "locked")), \
                mock.patch("apartment.__main__.open_in_default_app") as opener:
            self.run_export("--open")
        opener.assert_not_called()


class TestExcelLauncherRoute(unittest.TestCase):
    def setUp(self):
        self.text = LAUNCHER.read_bytes().decode("ascii")

    def test_excel_argument_is_routed(self):
        self.assertIn('if /i "%~1"=="/excel" goto excel', self.text)
        self.assertIn(":excel", self.text)

    def test_excel_route_exports_rather_than_serving(self):
        tail = self.text[self.text.index(":excel"):]
        self.assertIn("apartment export --open", tail)
        self.assertNotIn("apartment serve", tail)

    def test_excel_route_does_not_kill_a_server_the_owner_is_using(self):
        """It is a separate errand; stopping the running system would be rude.

        Anchored on the invocation, not the script name -- the header comment
        mentions stop-server.ps1 too, and matching that compares nothing useful.
        """
        call = "powershell -NoProfile"
        self.assertIn(call, self.text)
        self.assertLess(
            self.text.index('if /i "%~1"=="/excel" goto excel'),
            self.text.index(call),
            "the /excel jump must come before the stop-server call",
        )


if __name__ == "__main__":
    unittest.main()
