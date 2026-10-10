"""Pairing: Tailscale status parsing, address filtering and the jar://pair link."""

import json
import unittest
from urllib.parse import parse_qs, urlparse

from server.pairing import (Addresses, Tailscale, is_lan, pairing_link, pairing_urls,
                            parse_tailscale_status, qr_svg)

STATUS = {
    "BackendState": "Running",
    "Self": {"DNSName": "my-pc.tail1234.ts.net.",
             "TailscaleIPs": ["100.101.102.103", "fd7a:115c:a1e0::1234"]},
}


class TailscaleStatusTest(unittest.TestCase):
    def test_running(self):
        ts = parse_tailscale_status(json.dumps(STATUS))
        self.assertTrue(ts.running)
        self.assertEqual(ts.ip, "100.101.102.103")                    # IPv4 only
        self.assertEqual(ts.dns_name, "my-pc.tail1234.ts.net")  # trailing dot removed
        self.assertEqual(ts.problem, "")

    def test_signed_out(self):
        ts = parse_tailscale_status(json.dumps({"BackendState": "NeedsLogin", "Self": {}}))
        self.assertFalse(ts.running)
        self.assertIn("sign in", ts.problem)

    def test_garbage(self):
        self.assertTrue(parse_tailscale_status("not json").problem)


class AddressTest(unittest.TestCase):
    def test_lan_filter(self):
        self.assertTrue(is_lan("192.168.1.87"))
        self.assertTrue(is_lan("10.0.0.5"))
        self.assertFalse(is_lan("100.101.102.103"))   # Tailscale range is not "home network"
        self.assertFalse(is_lan("127.0.0.1"))
        self.assertFalse(is_lan("169.254.3.4"))
        self.assertFalse(is_lan("8.8.8.8"))
        self.assertFalse(is_lan("nonsense"))

    def test_url_order_home_first_then_tailscale(self):
        a = Addresses(lan=["192.168.1.87"],
                      tailscale=Tailscale(True, True, "100.101.102.103", "my-pc.tail1234.ts.net"))
        self.assertEqual(pairing_urls(a, 8080), [
            "http://192.168.1.87:8080",
            "http://100.101.102.103:8080",
            "http://my-pc.tail1234.ts.net:8080",
        ])

    def test_no_tailscale(self):
        self.assertEqual(pairing_urls(Addresses(lan=["192.168.1.87"]), 8080), ["http://192.168.1.87:8080"])


class LinkTest(unittest.TestCase):
    def test_link_round_trip(self):
        urls = ["http://192.168.1.87:8080", "http://100.101.102.103:8080"]
        link = pairing_link("tok en&x", urls)
        p = urlparse(link)
        self.assertEqual((p.scheme, p.netloc), ("jar", "pair"))
        q = parse_qs(p.query)
        self.assertEqual(q["v"], ["1"])
        self.assertEqual(q["t"], ["tok en&x"])     # special characters survive
        self.assertEqual(q["u"], urls)              # order kept

    def test_qr_is_svg(self):
        svg = qr_svg("jar://pair?v=1&t=x")
        self.assertTrue(svg.startswith("<svg"))


if __name__ == "__main__":
    unittest.main()


class DashboardAccess(unittest.TestCase):
    def test_who_may_open_the_dashboard(self):
        from server.dashboard import allowed
        self.assertTrue(allowed("127.0.0.1", False))
        self.assertTrue(allowed("100.101.102.103", True))
        self.assertTrue(allowed("fd7a:115c:a1e0::1234", True))
        self.assertTrue(allowed("::ffff:100.101.102.103", True))
        self.assertFalse(allowed("100.101.102.103", False))
        self.assertFalse(allowed("192.168.1.20", True))
        self.assertFalse(allowed("100.128.0.1", True))   # just outside 100.64.0.0/10
        self.assertFalse(allowed(None, True))


class DashboardLogin(unittest.TestCase):
    def test_one_time_codes_and_cookie(self):
        from server.dashboard import LoginLinks
        L = LoginLinks("tok")
        code = L.issue()
        self.assertTrue(L.redeem(code))
        self.assertFalse(L.redeem(code))          # one use
        self.assertFalse(L.redeem("guess"))
        self.assertTrue(L.ok(L.cookie_value))
        self.assertFalse(L.ok("tok"))
        self.assertFalse(L.ok(None))
