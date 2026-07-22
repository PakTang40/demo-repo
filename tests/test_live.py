"""The live-refresh token and the endpoint that serves it.

A phone showing last hour's numbers is worse than a phone showing nothing, because
nothing about the page says it is old. These tests pin the property the whole
feature rests on: the token moves whenever the data moves, including when the
writer was not the web server.
"""

import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from apartment import db, repo
from apartment.web import layout, live, server
from apartment.web.server import Handler


class TestDataVersion(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.db_path = Path(self.dir.name) / "apartment.db"
        self.conn = db.connect(self.db_path)
        self.addCleanup(self.conn.close)
        db.init_db(self.conn)
        db.seed_rooms(self.conn)

    def test_token_is_stable_when_nothing_changes(self):
        self.assertEqual(live.data_version(self.db_path), live.data_version(self.db_path))

    def test_token_moves_when_a_row_is_written(self):
        before = live.data_version(self.db_path)
        repo.add_tenant(self.conn, "ทดสอบ", phone="081-000-0000")
        self.assertNotEqual(before, live.data_version(self.db_path),
                            "a committed write must be visible to every open page")

    def test_missing_database_does_not_raise(self):
        """The token is read before the first run has created anything."""
        self.assertIsInstance(live.data_version(Path(self.dir.name) / "absent.db"), str)


class TestVersionEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.dir.name) / "apartment.db"
        conn = db.connect(cls.db_path)
        db.init_db(conn)
        db.seed_rooms(conn)
        conn.close()

        cls.previous_db = Handler.db_path
        cls.previous_log = Handler.log_message
        Handler.log_message = lambda self, fmt, *args: None
        Handler.db_path = cls.db_path
        cls.server = server._Server(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        Handler.db_path = cls.previous_db
        Handler.log_message = cls.previous_log
        cls.dir.cleanup()

    def get(self, path):
        return urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5)

    def test_endpoint_returns_the_current_token(self):
        with self.get("/api/version") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read().decode("utf-8"), live.data_version(self.db_path))

    def test_endpoint_is_never_cached(self):
        """A cached token would freeze every phone on the value it first saw."""
        with self.get("/api/version") as response:
            self.assertIn("no-store", response.headers.get("Cache-Control", ""))

    def test_endpoint_reflects_a_write_made_outside_the_server(self):
        """`python -m apartment invoice` must reach the phones too."""
        with self.get("/api/version") as response:
            before = response.read().decode("utf-8")
        conn = db.connect(self.db_path)
        repo.add_tenant(conn, "ผู้เช่าใหม่", phone="081-999-9999")
        conn.close()
        with self.get("/api/version") as response:
            self.assertNotEqual(before, response.read().decode("utf-8"))

    def test_every_page_carries_the_poller(self):
        with self.get("/") as response:
            self.assertIn("/api/version", response.read().decode("utf-8"))


class TestPollerMarkup(unittest.TestCase):
    def test_poller_is_injected_inside_the_document(self):
        html = layout.page("หน้าทดสอบ", "<p>เนื้อหา</p>")
        self.assertIn("/api/version", html)
        self.assertLess(html.index("/api/version"), html.index("</body>"))

    def test_poller_refuses_to_discard_a_half_filled_form(self):
        """The meter sheet is 30 rooms of typing; a silent reload would erase it."""
        self.assertIn("dirty", live.LIVE_HTML)
        self.assertIn("offerReload", live.LIVE_HTML)

    def test_poller_sleeps_while_the_tab_is_hidden(self):
        self.assertIn("document.hidden", live.LIVE_HTML)


if __name__ == "__main__":
    unittest.main()
