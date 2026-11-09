from __future__ import annotations

import subprocess
from pathlib import Path

from . import http
from .models import Episode


def ensure_episode_audio(episode: Episode, workdir: Path) -> Path:
    dest = workdir / "episode.mp3"
    if not dest.exists():
        http.download(episode.audio_url, dest)
    return dest


def split_for_upload(source: Path, out_dir: Path, segment_seconds: int = 600) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "chunk_%03d.mp3"
    _ffmpeg(
        "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k",
        "-f", "segment", "-segment_time", str(segment_seconds), str(pattern),
    )
    return sorted(out_dir.glob("chunk_*.mp3"))


def concat_and_normalize(parts: list[Path], dest: Path) -> Path:
    list_file = dest.with_suffix(".concat.txt")
    list_file.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    _ffmpeg(
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-b:a", "96k", str(dest),
    )
    list_file.unlink()
    return dest


def decode_mono_16k(path: Path):
    import numpy as np

    result = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
        check=True, capture_output=True,
    )
    return np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def duration_seconds(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)
