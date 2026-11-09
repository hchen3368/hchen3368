from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from . import audio

MAX_CHARS_PER_REQUEST = 3000


class TTSEngine(Protocol):
    name: str

    def synthesize(self, text: str, dest: Path) -> Path: ...


class OpenAITTS:
    def __init__(
        self,
        model: str = "gpt-4o-mini-tts",
        voice: str = "alloy",
        instructions: str = "Warm, clear podcast narrator. Natural pace, light emphasis on key ideas.",
        client=None,
    ):
        self.model = model
        self.voice = voice
        self.instructions = instructions
        self._client = client
        self.name = f"openai:{model}:{voice}"

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI()
        return self._client

    def synthesize(self, text: str, dest: Path) -> Path:
        with self.client.audio.speech.with_streaming_response.create(
            model=self.model, voice=self.voice, input=text,
            instructions=self.instructions, response_format="mp3",
        ) as response:
            response.stream_to_file(dest)
        return dest


def render_script(engine: TTSEngine, script: str, dest: Path) -> Path:
    parts_dir = dest.parent / "tts_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    parts = [
        engine.synthesize(chunk, parts_dir / f"part_{i:03d}.mp3")
        for i, chunk in enumerate(split_text(script))
    ]
    return audio.concat_and_normalize(parts, dest)


def split_text(text: str, max_chars: int = MAX_CHARS_PER_REQUEST) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return [piece for chunk in chunks for piece in _hard_split(chunk, max_chars)]


def _hard_split(text: str, max_chars: int) -> list[str]:
    pieces = []
    while len(text) > max_chars:
        cut = text.rfind(" ", 0, max_chars + 1)
        cut = cut if cut > 0 else max_chars
        pieces.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return pieces + ([text] if text else [])
