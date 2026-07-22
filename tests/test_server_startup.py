"""Startup guards for the HTTP server.

These exist because of a bug that cost real confusion: on Windows a second instance
could bind a port that was already being listened on, start with no error, and leave
the *original* process answering the browser with whatever code it had loaded. The
app looked like it simply refused to update. See docs/adr/0006-single-instance.md.
"""

import contextlib
import io
import socket
import threading
import unittest
import urllib.request

from apartment import db
from apartment.web import server
from apartment.web.server import Handler


class TestPortGuard(unittest.TestCase):
    def test_address_reuse_is_disabled(self):
        """Python defaults this to True; on Windows that is what allowed the bug."""
        self.assertFalse(server._Server.allow_reuse_address)

    def test_second_instance_exits_instead_of_pretending_to_start(self):
        holder = socket.socket()
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        previous = Handler.db_path
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as caught:
                server.serve(host="127.0.0.1", port=port)
            printed = out.getvalue()
            self.assertEqual(caught.exception.code, 1)
            # The failure must be loud, in Thai, and actionable...
            self.assertIn("ถูกใช้งานอยู่แล้ว", printed)
            self.assertIn("เปิดระบบ.bat", printed)
            # ...and must never claim success, which is what made this invisible.
            self.assertNotIn("พร้อมใช้งานแล้ว", printed)
        finally:
            Handler.db_path = previous
            holder.close()


class TestLiveResponses(unittest.TestCase):
    """One real socket, to cover the bits that only exist over HTTP."""

    @classmethod
    def setUpClass(cls):
        cls.previous_db = Handler.db_path
        cls.previous_log = Handler.log_message
        Handler.log_message = lambda self, fmt, *args: None  # keep test output clean
        cls.server = server._Server(("127.0.0.1", 0), Handler)
        Handler.db_path = None  # uses the default DB; these are read-only GETs
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        Handler.db_path = cls.previous_db
        Handler.log_message = cls.previous_log

    def get(self, path):
        return urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5)

    def test_pages_are_never_cached(self):
        """A cached page is stale financial data, and looks exactly like a failed update."""
        with self.get("/") as response:
            self.assertEqual(response.status, 200)
            self.assertIn("no-store", response.headers.get("Cache-Control", ""))

    def test_html_is_served_as_utf8(self):
        with self.get("/rooms") as response:
            self.assertIn("charset=utf-8", response.headers.get("Content-Type", "").lower())
            self.assertIn("ห้องพัก", response.read().decode("utf-8"))

    def test_unknown_path_is_a_404_not_a_crash(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/no-such-page")
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()


if __name__ == "__main__":
    unittest.main()
