"""Jar supervisor: runs the server and the worker, and keeps them current.

    python -m server.supervise          (start-jar.ps1 starts this, hidden)

- Restarts both when code (server/, worker/), config.toml or requirements.txt changes.
  It waits for a memo in progress to finish first, and installs new packages when needed.
- Restarts either one if it crashes, with back-off.
- Pulls new code from GitHub every few minutes, so a push reaches this PC by itself:
  with git when this folder is a clone (fast-forward only, never over local edits), otherwise by
  downloading the repo's zip and copying changed files (a file edited here since is left alone).
- Takes orders from the admin's phone (data/supervisor-cmd.json, written by the server):
  "update" checks GitHub now, "restart" restarts the server and the worker.
- Writes data/supervisor.json for the dashboard: code version, update status, restarts.

config.toml (all optional):
    [supervisor]
    auto_restart = true      # restart on code/config changes
    github_pull = true       # pull from GitHub when this folder is a git clone
    pull_minutes = 10
    repo = "noless-zz/jar"   # where the zip updates come from
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.request
import zipfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("jar.supervise")
WIN = sys.platform == "win32"
NO_WINDOW = 0x08000000 if WIN else 0          # CREATE_NO_WINDOW: children stay hidden


def load_config() -> dict:
    for name in ("config.toml", "config.example.toml"):
        p = ROOT / name
        if p.exists():
            try:
                with open(p, "rb") as f:
                    return tomllib.load(f)
            except (OSError, tomllib.TOMLDecodeError) as e:
                log.error("can't read %s: %s (keeping the old settings)", name, e)
                return {}
    return {}


def watched_files() -> list[Path]:
    files = [ROOT / "config.toml", ROOT / "requirements.txt"]
    for d in ("server", "worker"):
        files += sorted(p for p in (ROOT / d).glob("*") if p.suffix in (".py", ".html"))
    return files


def signature(files: list[Path]) -> dict[str, tuple]:
    sig = {}
    for p in files:
        try:
            st = p.stat()
            sig[str(p.relative_to(ROOT))] = (st.st_mtime_ns, st.st_size)
        except OSError:
            sig[str(p.relative_to(ROOT))] = None
    return sig


def changed(old: dict, new: dict) -> list[str]:
    return sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if WIN:
        # The .venv python.exe is a launcher with a child: kill the whole tree.
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                       creationflags=NO_WINDOW)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


class Child:
    def __init__(self, name: str, args: list[str], out: Path, err: Path):
        self.name, self.args, self.out, self.err = name, args, out, err
        self.proc: subprocess.Popen | None = None
        self.started = 0.0
        self.crashes = 0

    def start(self) -> None:
        self.out.parent.mkdir(parents=True, exist_ok=True)
        with open(self.out, "ab") as o, open(self.err, "ab") as e:
            self.proc = subprocess.Popen(self.args, cwd=ROOT, stdout=o, stderr=e, stdin=subprocess.DEVNULL,
                                         creationflags=NO_WINDOW)
        self.started = time.time()
        log.info("%s started (pid %s)", self.name, self.proc.pid)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.proc is not None:
            kill_tree(self.proc)
            log.info("%s stopped", self.name)
        self.proc = None


class Git:
    """Fast-forward pulls from GitHub. Never touches local edits or local commits."""

    def __init__(self):
        self.exe = shutil.which("git")
        self.env = dict(os.environ, GIT_TERMINAL_PROMPT="0")

    def available(self) -> str | None:
        if not (ROOT / ".git").exists():
            return "this folder isn't linked to GitHub yet (VS Code: More -> Link this folder to GitHub)"
        if not self.exe:
            return "git isn't installed (winget install Git.Git)"
        return None

    def run(self, *args: str, timeout: int = 90) -> subprocess.CompletedProcess:
        return subprocess.run([self.exe, *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                              env=self.env, creationflags=NO_WINDOW)

    def head(self) -> str:
        if self.available():
            return ""
        r = self.run("rev-parse", "--short", "HEAD")
        return r.stdout.strip() if r.returncode == 0 else ""

    def pull(self) -> str:
        """One check. Returns a status line for the dashboard."""
        problem = self.available()
        if problem:
            return problem
        try:
            r = self.run("fetch", "--quiet", "origin", "main")
            if r.returncode != 0:
                return "can't reach GitHub: " + (r.stderr.strip().splitlines() or ["?"])[-1][:200]
            local = self.run("rev-parse", "HEAD").stdout.strip()
            remote = self.run("rev-parse", "origin/main").stdout.strip()
            if local == remote:
                return f"up to date ({local[:7]})"
            if self.run("merge-base", "--is-ancestor", "HEAD", "origin/main").returncode != 0:
                return "this PC has commits GitHub doesn't: not pulling (push or reset them)"
            dirty = [ln for ln in self.run("status", "--porcelain", "--untracked-files=no").stdout.splitlines()
                     if ln.strip()]
            # Files changed here that already match GitHub (copied over by hand or by a zip update)
            # lose nothing when reset: put them back to HEAD so the fast-forward can go ahead.
            same = [ln[3:] for ln in dirty
                    if self.run("diff", "--quiet", "origin/main", "--", ln[3:]).returncode == 0]
            if same and len(same) == len(dirty):
                self.run("checkout", "--", *same)
                dirty = []
            if dirty:
                files = ", ".join(ln[3:] for ln in dirty[:3])
                return f"local edits ({files}): not pulling until they're committed or reverted"
            m = self.run("merge", "--ff-only", "--quiet", "origin/main")
            if m.returncode != 0:
                return "pull failed: " + (m.stderr.strip().splitlines() or ["?"])[-1][:200]
            log.info("pulled %s -> %s from GitHub", local[:7], remote[:7])
            return f"updated {local[:7]} -> {remote[:7]}"
        except (OSError, subprocess.TimeoutExpired) as e:
            return f"git error: {e}"


class ZipUpdate:
    """Updates without git: GitHub's zip of main, copied over the files that changed.
    data/update-state.json remembers the commit and each file's hash as written, so a file
    edited on this PC afterwards is never overwritten (it is reported instead)."""

    SKIP = (".github/", "android/")

    def __init__(self, repo: str = "noless-zz/jar"):
        self.repo = repo
        self.state_path = ROOT / "data" / "update-state.json"

    def state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def head(self) -> str:
        return self.state().get("sha", "")[:7]

    def _get(self, url: str, accept: str = "") -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "jar-supervisor", **({"Accept": accept} if accept else {})})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()

    def latest(self) -> str:
        return self._get(f"https://api.github.com/repos/{self.repo}/commits/main",
                         "application/vnd.github.sha").decode().strip()

    def download(self, sha: str) -> bytes:
        return self._get(f"https://codeload.github.com/{self.repo}/zip/{sha}")

    @staticmethod
    def _hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def apply(self, sha: str, blob: bytes) -> tuple[int, list[str]]:
        """Write the changed files; returns (files written, files kept because they were edited here)."""
        known = self.state().get("files", {})
        files, written, kept, later = {}, 0, [], []
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for info in z.infolist():
                rel = info.filename.split("/", 1)[1] if "/" in info.filename else ""
                if not rel or info.is_dir() or rel.startswith(self.SKIP) or ".." in rel.split("/"):
                    continue
                new = z.read(info)
                h = self._hash(new)
                path = ROOT / rel
                try:
                    cur = self._hash(path.read_bytes())
                except OSError:
                    cur = None
                if cur == h:
                    files[rel] = h
                    continue
                if cur is not None and rel in known and cur != known[rel]:
                    kept.append(rel)                     # changed on this PC since the last update
                    files[rel] = known[rel]              # still guarded next time
                    continue
                files[rel] = h
                if rel == "server/supervise.py":
                    later.append((path, new))
                else:
                    self._write(path, new)
                    written += 1
        for path, new in later:                          # last: writing it hands over to a new supervisor
            self._write(path, new)
            written += 1
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({"sha": sha, "at": time.time(), "files": files}), encoding="utf-8")
        return written, kept

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".jar-new")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def pull(self) -> str:
        try:
            sha = self.latest()
            old = self.state().get("sha", "")
            if sha == old:
                return f"up to date ({sha[:7]})"
            written, kept = self.apply(sha, self.download(sha))
        except Exception as e:  # noqa: BLE001
            return f"can't update from GitHub: {type(e).__name__}: {str(e)[:150]}"
        msg = (f"updated {old[:7] or 'first time'} -> {sha[:7]} ({written} file{'s' * (written != 1)})"
               if written else f"up to date ({sha[:7]})")
        if kept:
            msg += f"; kept {len(kept)} file(s) edited on this PC: {', '.join(kept[:3])}"
        log.info("zip update: %s", msg)
        return msg


class Supervisor:
    def __init__(self):
        self.data = ROOT / "data"
        self.logs = self.data / "logs"
        self.cfg = load_config()
        self.py = sys.executable
        port = str(self.cfg.get("server", {}).get("port", 8080))
        self.server = Child("server", [self.py, "-m", "uvicorn", "server.server:app", "--host", "0.0.0.0",
                                       "--port", port], self.logs / "server.out.log", self.logs / "server.log")
        self.worker = Child("worker", [self.py, "-m", "worker"], self.logs / "worker.out.log",
                            self.logs / "worker.err.log")
        self.git = Git()
        self.zip = ZipUpdate(self.opt("repo", "noless-zz/jar"))
        self.update = "not checked yet"
        self.last_command = ""
        self.checked_at = 0.0
        self.restarts = 0
        self.code = self.code_version()
        self.last_reason = ""
        self.started = time.time()

    def updater(self):
        """git when this folder is a clone and git is installed, else the zip download."""
        return self.git if self.git.available() is None else self.zip

    def code_version(self) -> str:
        return self.updater().head()

    def pull(self) -> None:
        self.update = self.updater().pull()
        self.checked_at = time.time()
        self.code = self.code_version()

    def take_command(self) -> None:
        """An order from the admin's phone, left by the server in data/supervisor-cmd.json."""
        p = self.data / "supervisor-cmd.json"
        if not p.exists():
            return
        try:
            cmd = json.loads(p.read_text(encoding="utf-8")).get("cmd", "")
        except (OSError, ValueError):
            cmd = ""
        try:
            p.unlink()
        except OSError:
            return
        log.info("command from the phone: %s", cmd)
        if cmd == "update":
            self.pull()
            self.last_command = f"update: {self.update}"
        elif cmd == "restart":
            self.last_command = "restart"
            self.restart("asked from the phone")

    def opt(self, key: str, default):
        return self.cfg.get("supervisor", {}).get(key, default)

    # ---- lifecycle ----
    def start_all(self) -> None:
        self.server.start()
        self.worker.start()

    def stop_all(self) -> None:
        self.worker.stop()
        self.server.stop()

    def worker_busy(self) -> bool:
        try:
            hb = json.loads((self.data / "worker.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return hb.get("doing", "idle") != "idle" and time.time() - hb.get("epoch", 0) < 600

    def install_requirements(self) -> None:
        log.info("requirements.txt changed: installing packages")
        r = subprocess.run([self.py, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"], cwd=ROOT,
                           capture_output=True, text=True, creationflags=NO_WINDOW)
        if r.returncode == 0:
            stamp = ROOT / ".venv" / ".requirements-installed"
            if stamp.parent.exists():
                stamp.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
        else:
            log.error("pip install failed: %s", (r.stderr or r.stdout)[-500:])

    def restart(self, reason: str) -> None:
        deadline = time.time() + 180
        while self.worker_busy() and time.time() < deadline:
            time.sleep(2)                     # let the memo in progress finish
        log.info("restarting server and worker: %s", reason)
        self.stop_all()
        self.cfg = load_config()
        self.start_all()
        self.restarts += 1
        self.last_reason = reason

    def replace_myself(self) -> None:
        """The supervisor's own code changed: start a fresh supervisor and step aside."""
        log.info("supervisor code changed: handing over to a new supervisor")
        while self.worker_busy():
            time.sleep(2)
        self.stop_all()
        flags = (0x00000008 | NO_WINDOW) if WIN else 0        # DETACHED_PROCESS: outlives this one
        subprocess.Popen([self.py, "-m", "server.supervise"], cwd=ROOT, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=not WIN)

    def keep_alive(self, child: Child) -> None:
        if child.alive():
            if time.time() - child.started > 300:
                child.crashes = 0
            return
        code = child.proc.returncode if child.proc else None
        child.crashes += 1
        wait = min(60, 5 * 2 ** min(child.crashes - 1, 4))
        log.warning("%s exited (code %s); restarting in %d s", child.name, code, wait)
        time.sleep(wait)
        child.start()

    def heartbeat(self) -> None:
        hb = {"pid": os.getpid(), "epoch": time.time(), "started": self.started, "code": self.code,
              "update": self.update, "checked_epoch": self.checked_at,
              "update_mode": "git" if self.updater() is self.git else "zip",
              "last_command": self.last_command,
              "auto_restart": bool(self.opt("auto_restart", True)),
              "github_pull": bool(self.opt("github_pull", True)),
              "restarts": self.restarts, "last_reason": self.last_reason}
        tmp = self.data / "supervisor.json.tmp"
        try:
            tmp.write_text(json.dumps(hb), encoding="utf-8")
            os.replace(tmp, self.data / "supervisor.json")
        except OSError:
            pass

    def run(self) -> None:
        log.info("Jar supervisor started in %s", ROOT)
        files = watched_files()
        sig = signature(files)
        self.start_all()
        try:
            while True:
                time.sleep(2)
                self.keep_alive(self.server)
                self.keep_alive(self.worker)

                self.take_command()
                if self.opt("github_pull", True):
                    every = max(2, int(self.opt("pull_minutes", 10))) * 60
                    if time.time() - self.checked_at > every:
                        self.pull()

                if self.opt("auto_restart", True):
                    files = watched_files()
                    new = signature(files)
                    diff = changed(sig, new)
                    if diff:
                        time.sleep(2)               # an editor or git may still be writing
                        new = signature(watched_files())
                        diff = changed(sig, new)
                        sig = new
                        if "requirements.txt" in diff:
                            self.install_requirements()
                        if any(f.replace("\\", "/") == "server/supervise.py" for f in diff):
                            self.replace_myself()
                            return
                        self.restart("changed: " + ", ".join(diff[:5]) + (" …" if len(diff) > 5 else ""))
                self.heartbeat()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop_all()
            log.info("supervisor stopped")


def main() -> None:
    logs = ROOT / "data" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(logs / "supervisor.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
    logging.getLogger().handlers[:] = [fh]
    if sys.stdout and sys.stdout.isatty():
        logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))
    logging.getLogger().setLevel(logging.INFO)
    Supervisor().run()


if __name__ == "__main__":
    main()
