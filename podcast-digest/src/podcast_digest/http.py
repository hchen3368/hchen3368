from __future__ import annotations

import ipaddress
import os
import socket
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

from . import __version__

USER_AGENT = f"podcast-digest/{__version__}"
TIMEOUT = 60
MAX_REDIRECTS = 5
MAX_TEXT_BYTES = 20 * 1024 * 1024
MAX_AUDIO_BYTES = 1024 * 1024 * 1024
TEXT_DEADLINE_SECONDS = 120
AUDIO_DEADLINE_SECONDS = 1800
BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost")


class UnsafeURLError(ValueError):
    pass


class ResponseTooLargeError(IOError):
    pass


def check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeURLError(f"Only http(s) URLs are allowed: {url!r}")
    host = parts.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(BLOCKED_HOST_SUFFIXES):
        raise UnsafeURLError(f"Internal host not allowed: {host}")
    for address in _addresses(host):
        if not address.is_global:
            raise UnsafeURLError(f"Non-public address not allowed: {host} -> {address}")


def _addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []
    return [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]


def _session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def _open(url: str, params: dict | None = None) -> requests.Response:
    session = _session()
    for _ in range(MAX_REDIRECTS + 1):
        check_url(url)
        response = session.get(url, params=params, timeout=TIMEOUT, stream=True, allow_redirects=False)
        if not response.is_redirect:
            response.raise_for_status()
            return response
        url = urljoin(url, response.headers["Location"])
        params = None
        response.close()
    raise requests.TooManyRedirects(f"More than {MAX_REDIRECTS} redirects")


def _iter_limited(response: requests.Response, max_bytes: int, deadline_seconds: float):
    declared = int(response.headers.get("Content-Length") or 0)
    if declared > max_bytes:
        raise ResponseTooLargeError(f"{response.url} is {declared} bytes (limit {max_bytes})")
    deadline = time.monotonic() + deadline_seconds
    received = 0
    for chunk in response.iter_content(chunk_size=1 << 20):
        received += len(chunk)
        if received > max_bytes:
            raise ResponseTooLargeError(f"{response.url} exceeded {max_bytes} bytes")
        if time.monotonic() > deadline:
            raise TimeoutError(f"{response.url} took longer than {deadline_seconds}s")
        yield chunk


def get_bytes(url: str, params: dict | None = None) -> bytes:
    with _open(url, params) as response:
        return b"".join(_iter_limited(response, MAX_TEXT_BYTES, TEXT_DEADLINE_SECONDS))


def get_text(url: str) -> str:
    with _open(url) as response:
        body = b"".join(_iter_limited(response, MAX_TEXT_BYTES, TEXT_DEADLINE_SECONDS))
        encoding = response.encoding if response.encoding and response.encoding.lower() != "iso-8859-1" else "utf-8"
    return body.decode(encoding, errors="replace")


def get_json(url: str, params: dict | None = None) -> dict:
    import json

    return json.loads(get_bytes(url, params))


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")
    try:
        with _open(url) as response, partial.open("wb") as fh:
            for chunk in _iter_limited(response, MAX_AUDIO_BYTES, AUDIO_DEADLINE_SECONDS):
                fh.write(chunk)
        os.replace(partial, dest)
    finally:
        partial.unlink(missing_ok=True)
    return dest
