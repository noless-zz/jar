"""The memo store the server writes: data/memos/<date>/<id>.wav + <id>.json.

The worker moves each memo through statuses recorded in its .json:
    received -> transcribed -> done          (normal path)
                             -> failed       (gave up after max_attempts)
The .json is only rewritten atomically, so a crash never leaves it half-written.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

PENDING = ("received", "transcribed")


@dataclass
class MemoFile:
    meta_path: Path
    meta: dict

    @property
    def id(self) -> str:
        return self.meta["id"]

    @property
    def wav(self) -> Path:
        return self.meta_path.with_suffix(".wav")

    @property
    def status(self) -> str:
        return self.meta.get("status", "received")

    def save(self) -> None:
        tmp = self.meta_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.meta, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.meta_path)

    def update(self, **fields) -> None:
        self.meta.update(fields)
        self.save()


def pending(data_dir: Path) -> list[MemoFile]:
    """Memos still to process, oldest recording first."""
    out = []
    for meta_path in (data_dir / "memos").glob("*/*.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # being written right now; next poll will see it
        m = MemoFile(meta_path, meta)
        if m.status in PENDING and m.wav.exists():
            out.append(m)
    out.sort(key=lambda m: m.meta.get("recorded_at") or m.meta.get("received_at") or "")
    return out
