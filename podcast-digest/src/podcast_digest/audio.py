from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

from . import http
from .models import Episode

SAMPLE_RATE = 16000
SAFE_INPUT = ("-protocol_whitelist", "file,pipe")
TEXT_CONTAINER_MAGIC = (b"#EXTM3U", b"ffconcat", b"<", b"[playlist]")


class UnsupportedAudioError(ValueError):
    pass


def ensure_episode_audio(episode: Episode, workdir: Path) -> Path:
    dest = workdir / "episode.audio"
    if not dest.exists():
        http.download(episode.audio_url, dest)
        try:
            check_is_binary_audio(dest)
        except UnsupportedAudioError:
            dest.unlink()
            raise
    return dest


def check_is_binary_audio(path: Path) -> None:
    with path.open("rb") as fh:
        head = fh.read(64).lstrip()
    if head.startswith(TEXT_CONTAINER_MAGIC):
        raise UnsupportedAudioError(f"{path} looks like a playlist or text document, not audio")


def split_for_upload(source: Path, out_dir: Path, segment_seconds: int = 300) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("chunk_*.mp3"))
    if existing and (out_dir / ".complete").exists():
        return existing
    _ffmpeg(
        *SAFE_INPUT, "-i", str(source), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-b:a", "32k",
        "-f", "segment", "-segment_time", str(segment_seconds), str(out_dir / "chunk_%03d.mp3"),
    )
    (out_dir / ".complete").touch()
    return sorted(out_dir.glob("chunk_*.mp3"))


def iter_pcm_windows(path: Path, window_seconds: int = 1800) -> Iterator:
    """Yields float32 mono 16 kHz windows so memory stays bounded on long episodes."""
    import numpy as np

    bytes_per_window = window_seconds * SAMPLE_RATE * 2
    proc = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", *SAFE_INPUT, "-i", str(path),
         "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
        stdout=subprocess.PIPE,
    )
    try:
        while True:
            raw = proc.stdout.read(bytes_per_window)
            if not raw:
                break
            yield np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    finally:
        proc.stdout.close()
        if proc.wait() != 0:
            raise subprocess.CalledProcessError(proc.returncode, "ffmpeg decode")


def concat_and_normalize(parts: list[Path], dest: Path) -> Path:
    list_file = dest.with_name(dest.name + ".concat.txt")
    tmp = dest.with_name(dest.stem + ".tmp" + dest.suffix)
    try:
        list_file.write_text("".join(f"file '{_quote_concat(p)}'\n" for p in parts))
        _ffmpeg(
            *SAFE_INPUT, "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-b:a", "96k", str(tmp),
        )
        os.replace(tmp, dest)
    finally:
        list_file.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
    return dest


def duration_seconds(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", *SAFE_INPUT, "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def _quote_concat(path: Path) -> str:
    return str(path.resolve()).replace("'", "'\\''")


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)
