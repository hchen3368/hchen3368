from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .audio import SAFE_INPUT

SUBTITLE_STYLE = (
    "FontName=Noto Sans CJK SC,FontSize=15,PrimaryColour=&H00FFFFFF,"
    "BackColour=&H99000000,BorderStyle=4,Outline=0,Shadow=0,MarginV=28"
)


def render_video(frame: Path, audio_path: Path, subtitles: Path | None, dest: Path) -> Path:
    """Still frame + narration (+ burned-in subtitles) as an MP4 ready for Bilibili."""
    workdir = dest.parent
    tmp = dest.with_name(dest.stem + ".tmp" + dest.suffix)
    filters = ["scale=1920:1080"]
    if subtitles is not None:
        filters.append(f"subtitles={subtitles.name}:force_style='{SUBTITLE_STYLE}'")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", *SAFE_INPUT,
                "-loop", "1", "-framerate", "10", "-i", str(frame.resolve()),
                "-i", str(audio_path.resolve()),
                "-vf", ",".join(filters),
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "26",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                "-shortest", "-movflags", "+faststart", tmp.name,
            ],
            check=True, cwd=workdir,
        )
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest


def render_slideshow(slides: list[tuple[Path, float]], audio_path: Path, subtitles: Path | None,
                     dest: Path) -> Path:
    """Shows each (image, start_seconds) slide from its start until the next one, over the narration."""
    workdir = dest.parent
    total = _duration(audio_path)
    lines = []
    for i, (image, start) in enumerate(slides):
        end = slides[i + 1][1] if i + 1 < len(slides) else total
        lines += [f"file '{_quote(image)}'", f"duration {max(end - start, 0.1):.3f}"]
    lines.append(f"file '{_quote(slides[-1][0])}'")
    list_file = dest.with_name(dest.stem + ".slides.txt")
    tmp = dest.with_name(dest.stem + ".tmp" + dest.suffix)
    filters = ["fps=10", "scale=1920:1080"]
    if subtitles is not None:
        filters.append(f"subtitles={subtitles.name}:force_style='{SUBTITLE_STYLE}'")
    try:
        list_file.write_text("\n".join(lines) + "\n")
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", *SAFE_INPUT,
                "-f", "concat", "-safe", "0", "-i", list_file.name,
                "-i", str(audio_path.resolve()),
                "-vf", ",".join(filters),
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "26",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                "-shortest", "-movflags", "+faststart", tmp.name,
            ],
            check=True, cwd=workdir,
        )
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
        list_file.unlink(missing_ok=True)
    return dest


def _duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", *SAFE_INPUT, "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def _quote(path: Path) -> str:
    return str(path.resolve()).replace("'", "'\\''")
