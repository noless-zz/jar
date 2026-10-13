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
        (self.pc / "a.txt").write_text("my edit\n")              # local edit: never overwritten
        self.push("3\n")
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
