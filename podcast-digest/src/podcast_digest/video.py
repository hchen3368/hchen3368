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
