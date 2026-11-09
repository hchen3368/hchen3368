from __future__ import annotations

from pathlib import Path

import requests

from . import __version__

USER_AGENT = f"podcast-digest/{__version__}"
TIMEOUT = 60


def _session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def get_text(url: str) -> str:
    response = _session().get(url, timeout=TIMEOUT)
    response.raise_for_status()
    if response.encoding is None or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding
    return response.text


def get_json(url: str, params: dict | None = None) -> dict:
    response = _session().get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    with _session().get(url, stream=True, timeout=TIMEOUT) as response:
        response.raise_for_status()
        with partial.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    partial.replace(dest)
    return dest
