from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from . import audio
from .languages import LANGUAGES, Language

MAX_CHARS_PER_REQUEST = 3000


class TTSEngine(Protocol):
    name: str

    def synthesize(self, text: str, dest: Path, instructions: str) -> Path: ...


@dataclass(frozen=True)
class SpokenPart:
    text: str
    start: float
    end: float


DEFAULT_TTS_MODEL = "gpt-4o-mini-tts-2025-12-15"


class OpenAITTS:
    def __init__(self, model: str = DEFAULT_TTS_MODEL, voice: str = "alloy", client=None):
        self.model = model
        self.voice = voice
        self._client = client
        self.name = f"openai:{model}:{voice}"

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI()
        return self._client

    def synthesize(self, text: str, dest: Path, instructions: str) -> Path:
        with self.client.audio.speech.with_streaming_response.create(
            model=self.model, voice=self.voice, input=text,
            instructions=instructions, response_format="mp3",
        ) as response:
            response.stream_to_file(dest)
        return dest


def render_script(
    engine: TTSEngine, script: str, dest: Path, language: Language = LANGUAGES["en"]
) -> list[SpokenPart]:
    parts_dir = dest.parent / f"tts_parts_{language.code}"
    parts_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    timeline: list[SpokenPart] = []
    cursor = 0.0
    for i, chunk in enumerate(split_text(script, language.tts_max_chars, language.sentence_split)):
        part = engine.synthesize(chunk, parts_dir / f"part_{i:03d}.mp3", language.tts_instructions)
        length = audio.duration_seconds(part)
        timeline.append(SpokenPart(chunk, cursor, cursor + length))
        files.append(part)
        cursor += length
    audio.concat_and_normalize(files, dest)
    return timeline


def split_text(
    text: str, max_chars: int = MAX_CHARS_PER_REQUEST, sentence_split: re.Pattern | None = None
) -> list[str]:
    pattern = sentence_split or LANGUAGES["en"].sentence_split
    sentences = [s.strip() for s in pattern.split(text.strip()) if s and s.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = _join(current, sentence)
    if current:
        chunks.append(current)
    return [piece for chunk in chunks for piece in _hard_split(chunk, max_chars)]


def _join(left: str, right: str) -> str:
    if not left:
        return right
    if _is_cjk(left[-1]) or _is_cjk(right[0]):
        return left + right
    return f"{left} {right}"


def _is_cjk(char: str) -> bool:
    return "⺀" <= char <= "鿿" or "＀" <= char <= "￯" or "　" <= char <= "〿"


def _hard_split(text: str, max_chars: int) -> list[str]:
    pieces = []
    while len(text) > max_chars:
        cut = text.rfind(" ", 0, max_chars + 1)
        cut = cut if cut > 0 else max_chars
        pieces.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return pieces + ([text] if text else [])
