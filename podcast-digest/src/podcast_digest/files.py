from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def write_text_atomic(path: Path, text: str) -> Path:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
    return path


def fingerprint(*parts: object) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(repr(part).encode())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


class Stamps:
    """Records which inputs produced each cached output, so changed options invalidate it."""

    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, str] = json.loads(path.read_text()) if path.exists() else {}

    def is_fresh(self, output: Path, fp: str) -> bool:
        return output.exists() and self._data.get(output.name) == fp

    def record(self, output: Path, fp: str) -> None:
        self._data[output.name] = fp
        write_text_atomic(self.path, json.dumps(self._data, indent=2))
