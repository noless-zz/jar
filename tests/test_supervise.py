"""Supervisor: change detection and the git fast-forward guard."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from server import supervise


class Changes(unittest.TestCase):
    def test_changed_files_are_reported(self):
        a = {"server/x.py": (1, 10), "config.toml": (5, 3)}
        b = {"server/x.py": (2, 10), "config.toml": (5, 3), "worker/new.py": (1, 1)}
        self.assertEqual(supervise.changed(a, b), ["server/x.py", "worker/new.py"])
        self.assertEqual(supervise.changed(a, dict(a)), [])

    def test_watches_code_and_config(self):
        names = [str(p.relative_to(supervise.ROOT)).replace("\\\\", "/") for p in supervise.watched_files()]
        self.assertIn("config.toml", names)
        self.assertIn("server/server.py", names)
        self.assertIn("worker/agent.py", names)
        self.assertIn("server/dashboard.html", names)


@unittest.skipUnless(supervise.shutil.which("git"), "git not installed")
class Pull(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        g = lambda *a, cwd=self.tmp: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)  # noqa: E731
        self.g = g
        g("init", "-q", "--bare", "-b", "main", "origin.git")
        g("clone", "-q", "origin.git", "dev")
        dev = self.tmp / "dev"
        g("config", "user.email", "t@t", cwd=dev); g("config", "user.name", "t", cwd=dev)  # noqa: E702
        (dev / "a.txt").write_text("1\n")
        g("add", ".", cwd=dev); g("commit", "-qm", "one", cwd=dev); g("push", "-q", "origin", "main", cwd=dev)  # noqa: E702
        g("clone", "-q", "origin.git", "pc")
        self.dev, self.pc = dev, self.tmp / "pc"
        self.old_root = supervise.ROOT
        supervise.ROOT = self.pc

    def tearDown(self):
        supervise.ROOT = self.old_root

    def push(self, text):
        (self.dev / "a.txt").write_text(text)
        self.g("commit", "-qam", text.strip(), cwd=self.dev)
        self.g("push", "-q", "origin", "main", cwd=self.dev)

    def test_fast_forward_and_guard(self):
        git = supervise.Git()
        self.assertTrue(git.pull().startswith("up to date"))
        self.push("2\n")
        self.assertTrue(git.pull().startswith("updated"))
        self.assertEqual((self.pc / "a.txt").read_text(), "2\n")
        (self.pc / "a.txt").write_text("3\n")                    # copied by hand, same as GitHub's next commit
        self.push("3\n")
        self.assertTrue(git.pull().startswith("updated"))
        self.assertEqual((self.pc / "a.txt").read_text(), "3\n")
        (self.pc / "a.txt").write_text("4\n")                    # copied ahead, plus a new file copied too
        (self.pc / "b.txt").write_text("new\n")
        (self.dev / "b.txt").write_text("new\n")
        self.g("add", "b.txt", cwd=self.dev)
        self.push("4\n")
        self.assertTrue(git.pull().startswith("updated"), git.pull())
        self.assertEqual((self.pc / "b.txt").read_text(), "new\n")
        (self.pc / "c.txt").write_text("mine\n")                 # untracked, different from GitHub's
        (self.dev / "c.txt").write_text("theirs\n")
        self.g("add", "c.txt", cwd=self.dev)
        self.push("5\n")
        self.assertIn("would be replaced (c.txt)", git.pull())
        (self.pc / "c.txt").unlink()
        self.assertTrue(git.pull().startswith("updated"))
        (self.pc / "a.txt").write_text("my edit\n")              # local edit: never overwritten
        self.push("6\n")
        status = git.pull()
        self.assertIn("local edits (a.txt)", status)
        self.assertEqual((self.pc / "a.txt").read_text(), "my edit\n")

    def test_not_linked(self):
        supervise.ROOT = self.tmp
        self.assertIn("isn't linked", supervise.Git().pull())


class ZipPull(unittest.TestCase):
    """Updates without git: zip from GitHub, never over a file edited on this PC."""

    def setUp(self):
        self.pc = Path(tempfile.mkdtemp())
        self.old_root = supervise.ROOT
        supervise.ROOT = self.pc
        self.up = supervise.ZipUpdate()
        self.sha = "a" * 40

    def tearDown(self):
        supervise.ROOT = self.old_root

    def zipped(self, files: dict) -> bytes:
        import io
        import zipfile
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            for k, v in files.items():
                z.writestr(f"jar-{self.sha}/{k}", v)
        return b.getvalue()

    def test_update_and_local_edit_guard(self):
        self.up.latest = lambda: self.sha
        self.up.download = lambda sha: self.zipped({"worker/a.py": "1\n", "android/x.java": "x", "README.md": "r"})
        self.assertIn("updated first time", self.up.pull())
        self.assertEqual((self.pc / "worker/a.py").read_text(), "1\n")
        self.assertFalse((self.pc / "android").exists())
        self.assertTrue(self.up.pull().startswith("up to date"))
        (self.pc / "worker/a.py").write_text("my edit\n")               # edited on the PC
        self.sha = "b" * 40
        self.up.download = lambda sha: self.zipped({"worker/a.py": "2\n", "README.md": "r2"})
        msg = self.up.pull()
        self.assertIn("kept 1 file(s) edited on this PC: worker/a.py", msg)
        self.assertEqual((self.pc / "worker/a.py").read_text(), "my edit\n")
        self.assertEqual((self.pc / "README.md").read_text(), "r2")
        self.sha = "c" * 40
        self.up.download = lambda sha: self.zipped({"worker/a.py": "3\n", "README.md": "r2"})
        self.assertIn("kept 1 file", self.up.pull())                    # still guarded

    def test_network_error_is_a_status(self):
        def boom():
            raise OSError("offline")
        self.up.latest = boom
        self.assertIn("can't update from GitHub", self.up.pull())

    def test_command_file_from_the_phone(self):
        (self.pc / "data").mkdir()
        s = supervise.Supervisor()
        s.updater = lambda: self.up
        self.up.latest = lambda: self.sha
        self.up.download = lambda sha: self.zipped({"README.md": "r"})
        (self.pc / "data" / "supervisor-cmd.json").write_text('{"cmd": "update"}')
        s.take_command()
        self.assertIn("update: updated", s.last_command)
        self.assertFalse((self.pc / "data" / "supervisor-cmd.json").exists())


class Watchdog(unittest.TestCase):
    def test_stale_only_when_every_sign_is_old(self):
        import os
        import time

        from server.server import supervisor_stale
        d = Path(tempfile.mkdtemp())
        self.assertFalse(supervisor_stale(d, time.time()))          # never ran here: not our business
        (d / "supervisor.json").write_text("{}")
        (d / "supervisor.alive").write_text("x")
        old = time.time() - 600
        os.utime(d / "supervisor.json", (old, old))
        self.assertFalse(supervisor_stale(d, time.time()))          # alive file is fresh
        os.utime(d / "supervisor.alive", (old, old))
        self.assertTrue(supervisor_stale(d, time.time()))

    def test_heartbeat_does_not_block_and_records_children(self):
        import json
        import time
        tmp = Path(tempfile.mkdtemp())
        old_root = supervise.ROOT
        supervise.ROOT = tmp
        try:
            (tmp / "data").mkdir()
            s = supervise.Supervisor()
            s.heartbeat()
            for _ in range(50):
                if (tmp / "data" / "supervisor.json").exists() and not s._writing.is_set():
                    break
                time.sleep(0.02)
            hb = json.loads((tmp / "data" / "supervisor.json").read_text())
            self.assertIn("children", hb)
            self.assertTrue((tmp / "data" / "supervisor.alive").exists())
        finally:
            supervise.ROOT = old_root

    def test_command_runs_once_even_if_the_file_stays(self):
        tmp = Path(tempfile.mkdtemp())
        old_root = supervise.ROOT
        supervise.ROOT = tmp
        try:
            (tmp / "data").mkdir()
            s = supervise.Supervisor()
            calls = []
            s.restart = lambda reason: calls.append(reason)
            (tmp / "data" / "supervisor-cmd.json").write_text('{"cmd": "restart", "at": 100}')
            orig = Path.unlink
            Path.unlink = lambda self, *a, **k: (_ for _ in ()).throw(PermissionError("held"))
            try:
                s.take_command()
                s.take_command()
            finally:
                Path.unlink = orig
            self.assertEqual(len(calls), 1)
        finally:
            supervise.ROOT = old_root
