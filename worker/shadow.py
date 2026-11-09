"""Shadow transcript: a second speech model runs on every memo next to the production one, and its text is saved in
the memo as meta["shadow"]. It never decides anything: filing always uses the production transcript. When people fix
memo texts (#26), the bench compares both against the fixed text on real use (worker/asr_bench.py).

    [transcribe]
    shadow = "parakeet-he"      # a runner candidate key from worker/asr_bench.py; "" = off
    shadow_device = "cpu"       # "cpu" (default: leaves the GPU to Whisper and the LLM) or "cuda"

The model runs in its own environment (data/asr-envs/<env>, set up by the bench the first time it runs that
candidate) as a long-lived process; it is started on the first memo and closed when the bench needs the machine.
Three failures in a row switch it off until the worker restarts.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

log = logging.getLogger("jar.shadow")

MAX_FAILS = 3


class Shadow:
    def __init__(self, data_dir: Path, key: str = "", device: str = "cpu", start=None):
        """start() -> an object with transcribe(wav) -> .text and close() (injectable for tests)."""
        self.data_dir = Path(data_dir)
        self.key = (key or "").strip()
        self.device = device or "cpu"
        self._start = start or self._start_runner
        self._tr = None
        self.fails = 0
        self.off = "" if self.key else "not configured"

    def _start_runner(self):
        from .asr_bench import CANDIDATES
        from .asr_extra import ExternalTranscriber, env_python
        c = next((c for c in CANDIDATES if c.key == self.key and c.runner), None)
        if c is None:
            raise LookupError(f"no runner candidate called {self.key!r} in worker/asr_bench.py")
        py = env_python(self.data_dir, c.env)
        if not (py.exists() and (py.parents[1] / ".jar-ready").exists()):
            raise FileNotFoundError(f"the {c.env} environment isn't set up: run the speech bench with "
                                    f'{{"candidates": ["{c.key}"]}} once')
        log.info("shadow transcript: starting %s on %s", c.model, self.device)
        return ExternalTranscriber(py, c.runner, c.model, c.language or "", self.data_dir / "logs" / "shadow.log",
                                   ready_timeout=900, memo_timeout=120, device=self.device)

    def transcribe(self, wav: Path) -> dict | None:
        """{"model", "text", "seconds"} or {"model", "error"}; None when off. Never raises."""
        if self.off:
            return None
        t0 = time.monotonic()
        try:
            if self._tr is None:
                self._tr = self._start()
            t1 = time.monotonic()
            text = self._tr.transcribe(Path(wav)).text
        except (LookupError, FileNotFoundError) as e:          # can't work at all: say so once, stop trying
            self.off = str(e)
            log.warning("shadow transcript off: %s", e)
            return None
        except Exception as e:  # noqa: BLE001
            self.fails += 1
            self.close()
            if self.fails >= MAX_FAILS:
                self.off = f"{MAX_FAILS} failures in a row: {e}"
            log.warning("shadow transcript failed (%d/%d): %s", self.fails, MAX_FAILS, e)
            return {"model": self.key, "error": f"{type(e).__name__}: {e}"[:300]}
        self.fails = 0
        return {"model": self.key, "text": text, "seconds": round(time.monotonic() - t1, 2),
                "load_seconds": round(t1 - t0, 1) if t1 - t0 > 0.5 else 0}

    def close(self) -> None:
        tr, self._tr = self._tr, None
        if tr is not None:
            try:
                tr.close()
            except Exception:  # noqa: BLE001
                pass
