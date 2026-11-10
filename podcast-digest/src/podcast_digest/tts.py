from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import os

import requests

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


class MiniMaxTTS:
    """MiniMax T2A v2 (international endpoint). Delivery is set by the voice; instructions are unused."""

    ENDPOINT = "https://api.minimax.io/v1/t2a_v2"
    VOICES_ENDPOINT = "https://api.minimax.io/v1/get_voice"
    LANGUAGE_BOOST = {"zh": "Chinese", "en": "English"}

    def __init__(self, model: str = "speech-2.8-hd", voice: str = "", language_code: str = "zh",
                 speed: float = 1.0, session: requests.Session | None = None):
        self.model = model
        self.voice = voice
        self.language_code = language_code
        self.speed = speed
        self._session = session or requests.Session()
        self.name = f"minimax:{model}:{voice}"

    def synthesize(self, text: str, dest: Path, instructions: str = "") -> Path:
        body = {
            "model": self.model,
            "text": text,
            "stream": False,
            "output_format": "hex",
            "language_boost": self.LANGUAGE_BOOST.get(self.language_code, "auto"),
            "voice_setting": {"voice_id": self.voice, "speed": self.speed, "vol": 1, "pitch": 0},
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
        }
        data = self._post(self.ENDPOINT, body)
        audio_hex = (data.get("data") or {}).get("audio")
        if not audio_hex:
            raise RuntimeError(f"MiniMax returned no audio: {data.get('base_resp')}")
        dest.write_bytes(bytes.fromhex(audio_hex))
        return dest

    def list_voices(self) -> list[dict]:
        data = self._post(self.VOICES_ENDPOINT, {"voice_type": "system"})
        return data.get("system_voice") or []

    def _post(self, url: str, body: dict) -> dict:
        response = self._session.post(url, json=body, headers=self._headers(), timeout=120)
        response.raise_for_status()
        data = response.json()
        status = (data.get("base_resp") or {}).get("status_code", 0)
        if status != 0:
            raise RuntimeError(f"MiniMax error {status}: {data['base_resp'].get('status_msg')}")
        return data

    @staticmethod
    def _headers() -> dict:
        return {"Authorization": f"Bearer {os.environ.get('MINIMAX_API_KEY', 'proxy-injected')}"}


PROVIDERS = {
    "openai": {"model": DEFAULT_TTS_MODEL, "voices": {"en": "alloy", "zh": "marin"}},
    "minimax": {"model": "speech-2.8-hd", "voices": {"en": "English_Trustworth_Man", "zh": "Chinese (Mandarin)_Radio_Host"}},
}


def build_engine(provider: str, language: Language, model: str | None = None, voice: str | None = None) -> TTSEngine:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown TTS provider {provider!r}; choose from {sorted(PROVIDERS)}")
    defaults = PROVIDERS[provider]
    model = model or defaults["model"]
    voice = voice or defaults["voices"].get(language.code) or defaults["voices"]["en"]
    if provider == "minimax":
        return MiniMaxTTS(model, voice, language.code)
    return OpenAITTS(model, voice)


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
