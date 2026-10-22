"""The Funnel watch: re-publishes Jar's public address when it drops, only when it is wanted."""

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from server.anywhere import AnywhereWatch, wanted


@dataclass
class TS:
    installed: bool = True
    running: bool = True
    dns_name: str = "pc.tail1.ts.net"
    funnel_url: str = ""
    problem: str = ""


class Watch(unittest.TestCase):
    def setUp(self):
        import server.anywhere as mod
        mod.public_ips = lambda host, timeout=8: ["185.40.234.1"]
        self.data = Path(tempfile.mkdtemp())
        self.ts = TS(funnel_url="https://pc.tail1.ts.net")
        self.up = True
        self.ran = []

        def run(args):
            self.ran.append(args)
            if args[-1] != "off":
                self.ts.funnel_url, self.up = "https://pc.tail1.ts.net", True
            return 0
        self.w = AnywhereWatch(self.data, 8080, status_fn=lambda: self.ts, health_fn=lambda url: self.up,
                               run_fn=run, sleep_fn=lambda s: None)

    def want(self, on=True):
        (self.data / "anywhere.json").write_text(json.dumps({"on": on}), encoding="utf-8")

    def test_does_nothing_unless_wanted(self):
        self.ts.funnel_url = ""
        self.assertFalse(wanted(self.data))
        self.assertEqual(self.w.check()["wanted"], False)
        self.assertEqual(self.ran, [])

    def test_healthy(self):
        self.want()
        st = self.w.check()
        self.assertEqual((st["ok"], st["url"]), (True, "https://pc.tail1.ts.net"))
        self.assertEqual(self.ran, [])

    def test_dropped_funnel_is_published_again(self):
        self.want()
        self.ts.funnel_url, self.up = "", False
        st = self.w.check()
        self.assertTrue(st["ok"])
        self.assertEqual(st["fixes"], 1)
        self.assertIn(["funnel", "--bg", "--set-path", "/v1", "http://127.0.0.1:8080/v1"], self.ran)

    def test_one_failed_health_check_waits_for_a_second(self):
        self.want()
        self.up = False
        st = self.w.check()
        self.assertFalse(st["ok"])
        self.assertEqual(self.ran, [])                  # could be a blip
        self.w.check()
        self.assertTrue(self.ran)                       # twice in a row: publish again

    def test_tailscale_signed_out_is_reported_not_fixed(self):
        self.want()
        self.ts = TS(running=False, problem="signed out — open Tailscale and sign in")
        st = self.w.check()
        self.assertEqual(st["ok"], False)
        self.assertIn("signed out", st["problem"])
        self.assertEqual(self.ran, [])

    def test_fix_that_doesnt_help_says_so(self):
        self.want()
        self.ts.funnel_url, self.up = "", False
        self.w.run_fn = lambda args: self.ran.append(args) or 0   # publishing changes nothing
        self.w._out = lambda args: '{"Self": {"CapMap": {}}}'
        import server.anywhere as mod
        mod.public_ips = lambda host, timeout=8: []
        st = self.w.check()
        self.assertFalse(st["ok"])
        self.assertIn("Funnel permission", st["problem"])
        self.assertEqual(len(self.ran), 4)                       # both mappings tried
        self.w.check()
        self.assertEqual(len(self.ran), 4)                       # no new attempt for 30 minutes


class Mapping(Watch):
    def test_waits_for_public_dns_before_judging_the_mapping(self):
        import server.anywhere as mod
        self.want()
        self.ts.funnel_url, self.up = "", False
        seen = {"n": 0}

        def ips(host, timeout=8):
            seen["n"] += 1
            return [] if seen["n"] < 3 else ["185.40.234.1"]          # appears after two polls
        mod.public_ips = ips
        st = self.w.check()
        self.assertTrue(st["ok"])
        self.assertEqual(self.ran[-1], ["funnel", "--bg", "--set-path", "/v1", "http://127.0.0.1:8080/v1"])
        self.assertGreaterEqual(seen["n"], 3)


class Health(unittest.TestCase):
    def test_server_says_how_a_request_came(self):
        import os
        os.environ.setdefault("JAR_DEVICE_TOKEN", "t")
        os.environ.setdefault("JAR_DATA_DIR", tempfile.mkdtemp())
        from fastapi.testclient import TestClient

        from server import server
        c = TestClient(server.app)
        self.assertEqual(c.get("/v1/health").json(), {"ok": True, "via": "direct"})
        self.assertEqual(c.get("/v1/health", headers={"Tailscale-Funnel-Request": "?1"}).json()["via"], "funnel")


if __name__ == "__main__":
    unittest.main()
