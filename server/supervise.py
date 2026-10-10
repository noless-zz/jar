"""Jar supervisor: runs the server and the worker, and keeps them current.

    python -m server.supervise          (start-jar.ps1 starts this, hidden)

- Restarts both when code (server/, worker/), config.toml or requirements.txt changes.
  It waits for a memo in progress to finish first, and installs new packages when needed.
- Restarts either one if it crashes, with back-off.
- When this folder is a git clone of the GitHub repo, it pulls new commits every few minutes
  (fast-forward only, never over local edits), so a push to GitHub reaches this PC by itself.
- Writes data/supervisor.json for the dashboard: code version, update status, restarts.

config.toml (all optional):
    [supervisor]
    auto_restart = true      # restart on code/config changes
    github_pull = true       # pull from GitHub when this folder is a git clone
    pull_minutes = 10
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import tomllib
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
        self.update = "not checked yet"
        self.checked_at = 0.0
        self.restarts = 0
        self.code = self.git.head()
        self.last_reason = ""
        self.started = time.time()

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

                if self.opt("github_pull", True):
                    every = max(2, int(self.opt("pull_minutes", 10))) * 60
                    if time.time() - self.checked_at > every:
                        self.update = self.git.pull()
                        self.checked_at = time.time()
                        self.code = self.git.head()

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
