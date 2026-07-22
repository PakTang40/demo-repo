"""Which interface the phone mode is allowed to bind.

The distinction these tests protect is the whole security model of ADR-0007: an
address inside the tailnet is reachable only by devices signed in to the owner's
Tailscale account, while a LAN address is reachable by whoever else is on that
Wi-Fi. Confusing the two on a cafe network publishes tenant national ID numbers.
"""

import unittest

from apartment import net
from apartment.web import server


class TestTailnetMembership(unittest.TestCase):
    def test_tailscale_addresses_are_recognised(self):
        for address in ("100.64.0.1", "100.101.102.103", "100.127.255.254"):
            self.assertTrue(net.in_tailnet(address), address)

    def test_lan_and_loopback_are_not_tailnet(self):
        for address in ("192.168.0.171", "10.0.0.5", "172.16.4.9", "127.0.0.1", "0.0.0.0"):
            self.assertFalse(net.in_tailnet(address), address)

    def test_addresses_just_outside_the_range_are_rejected(self):
        """100.64.0.0/10 stops at 100.127.255.255 -- neighbours are public internet."""
        self.assertFalse(net.in_tailnet("100.63.255.255"))
        self.assertFalse(net.in_tailnet("100.128.0.0"))

    def test_nonsense_is_not_tailnet_and_does_not_raise(self):
        for value in ("", "tailscale", "not-an-ip", "999.1.1.1"):
            self.assertFalse(net.in_tailnet(value), value)


class TestLookup(unittest.TestCase):
    def test_lookup_returns_a_tailnet_address_or_nothing(self):
        """Runs on any machine: Tailscale may or may not be up. Never a LAN address."""
        found = net.tailscale_ip()
        if found is not None:
            self.assertTrue(net.in_tailnet(found), f"leaked a non-tailnet address: {found}")

    def test_failure_message_tells_the_owner_what_to_do(self):
        self.assertIn("Tailscale", net.NOT_READY)
        self.assertIn("เปิดระบบ.bat", net.NOT_READY)
        # Must not imply the whole system is broken -- the PC still works.
        self.assertIn("ยังใช้งานบนคอมเครื่องนี้ได้", net.NOT_READY)


class TestBrowserUrl(unittest.TestCase):
    def test_wildcard_and_loopback_open_localhost(self):
        for host in ("0.0.0.0", "127.0.0.1", "localhost"):
            self.assertEqual(server.browser_url(host, 8765), "http://localhost:8765")

    def test_tailnet_bind_opens_its_own_address(self):
        """localhost is not the bound interface here; opening it refuses to connect."""
        self.assertEqual(server.browser_url("100.101.102.103", 8765),
                         "http://100.101.102.103:8765")


if __name__ == "__main__":
    unittest.main()
