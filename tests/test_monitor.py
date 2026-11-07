"""GET /v1/monitor: read-only status for the home status board."""
import json
import os
import tempfile
import time
import unittest


class Monitor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("JAR_DEVICE_TOKEN", "admin-token-123")
        os.environ.setdefault("JAR_DATA_DIR", tempfile.mkdtemp())
        from fastapi.testclient import TestClient

        from server import server
        cls.s = server
        cls.c = TestClient(server.app)

    def setUp(self):
        self.old_key = self.s.MONITOR_KEY
        self.s.MONITOR_KEY = "board-key-456"
        root = self.s.DATA_ROOT
        root.mkdir(parents=True, exist_ok=True)
        now = time.time()
        (root / "supervisor.json").write_text(json.dumps({
            "epoch": now, "code": "abc1234", "update": None, "started": now - 60, "restarts": 2,
            "last_reason": "update", "checked_epoch": now - 30,
            "anywhere": {"wanted": True, "ok": True, "checked": now, "url": "https://secret-host.example"}}),
            encoding="utf-8")
        (root / "worker.json").write_text(json.dumps({"epoch": now, "doing": "idle", "llm": "qwen", "whisper": "turbo"}),
                                          encoding="utf-8")

    def tearDown(self):
        self.s.MONITOR_KEY = self.old_key

    def test_off_without_a_key(self):
        self.s.MONITOR_KEY = ""
        self.assertEqual(self.c.get("/v1/monitor", headers={"X-Monitor-Key": ""}).status_code, 404)

    def test_wrong_or_missing_key(self):
        self.assertEqual(self.c.get("/v1/monitor").status_code, 403)
        self.assertEqual(self.c.get("/v1/monitor", headers={"X-Monitor-Key": "nope"}).status_code, 403)

    def test_admin_token_is_not_a_monitor_key(self):
        r = self.c.get("/v1/monitor", headers={"Authorization": "Bearer admin-token-123"})
        self.assertEqual(r.status_code, 403)

    def test_status(self):
        r = self.c.get("/v1/monitor", headers={"X-Monitor-Key": "board-key-456"})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertTrue(d["supervisor"]["alive"])
        self.assertEqual(d["supervisor"]["code"], "abc1234")
        self.assertEqual(d["supervisor"]["restarts"], 2)
        self.assertTrue(d["worker"]["alive"])
        self.assertEqual(d["worker"]["llm"], "qwen")
        self.assertTrue(d["funnel"]["ok"])
        self.assertIn("up", d["ollama"])
        self.assertRegex(d["app_version"], r"^\d+\.\d+\.\d+$")

    def test_nothing_private(self):
        text = self.c.get("/v1/monitor", headers={"X-Monitor-Key": "board-key-456"}).text
        for secret in ("secret-host", "admin-token-123", "board-key-456", "token"):
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
