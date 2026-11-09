from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Protocol

from bs4 import BeautifulSoup

from . import audio, http
from .models import Episode, Transcript

log = logging.getLogger(__name__)

MIN_TRANSCRIPT_WORDS = 500
SPEAKER_SEGMENT_SELECTORS = (".ts-segment",)
CUE_TIMING_RE = re.compile(r"^\s*(\d+\s*$|[\d:.,]+\s*-->\s*[\d:.,]+.*$|WEBVTT.*$|NOTE\b.*$)")


class TranscriptSource(Protocol):
    name: str

    def fetch(self, episode: Episode, workdir: Path) -> Transcript | None: ...


class PublishedTranscriptSource:
    """Uses transcripts the publisher already provides (RSS tag or a linked page)."""

    name = "published"

    def fetch(self, episode: Episode, workdir: Path) -> Transcript | None:
        for url, mime in episode.transcript_urls:
            try:
                text = parse_transcript(http.get_text(url), mime or _guess_mime(url))
            except Exception as exc:
                log.warning("Transcript fetch failed for %s: %s", url, exc)
                continue
            if len(text.split()) >= MIN_TRANSCRIPT_WORDS:
                return Transcript(text=text, source=f"published:{url}")
            log.info("Transcript at %s too short, skipping", url)
        return None


class LocalWhisperSource:
    """Transcribes on this machine with faster-whisper (no API cost)."""

    name = "local-whisper"

    def __init__(self, model_size: str = "base.en", compute_type: str = "int8"):
        self.model_size = model_size
        self.compute_type = compute_type

    def fetch(self, episode: Episode, workdir: Path) -> Transcript | None:
        from faster_whisper import WhisperModel

        audio_path = audio.ensure_episode_audio(episode, workdir)
        model = WhisperModel(self.model_size, device="cpu", compute_type=self.compute_type)
        segments, _ = model.transcribe(str(audio_path), vad_filter=True, beam_size=1)
        text = "\n".join(segment.text.strip() for segment in segments)
        return Transcript(text=text, source=f"{self.name}:{self.model_size}")


class OpenAITranscribeSource:
    """Transcribes with the OpenAI API, splitting audio under the upload size limit."""

    name = "openai-transcribe"

    def __init__(self, model: str = "gpt-4o-mini-transcribe", client=None):
        self.model = model
        self._client = client

    def fetch(self, episode: Episode, workdir: Path) -> Transcript | None:
        from openai import OpenAI

        client = self._client or OpenAI()
        audio_path = audio.ensure_episode_audio(episode, workdir)
        parts = []
        for chunk in audio.split_for_upload(audio_path, workdir / "chunks"):
            with chunk.open("rb") as fh:
                result = client.audio.transcriptions.create(model=self.model, file=fh)
            parts.append(result.text.strip())
        return Transcript(text="\n".join(parts), source=f"{self.name}:{self.model}")


def get_transcript(episode: Episode, workdir: Path, sources: list[TranscriptSource]) -> Transcript:
    cache = workdir / "transcript.json"
    if cache.exists():
        data = json.loads(cache.read_text())
        return Transcript(text=data["text"], source=data["source"])
    for source in sources:
        log.info("Trying transcript source: %s", source.name)
        transcript = source.fetch(episode, workdir)
        if transcript and transcript.text.strip():
            workdir.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"source": transcript.source, "text": transcript.text}))
            (workdir / "transcript.txt").write_text(transcript.text)
            return transcript
    raise RuntimeError(f"No transcript source succeeded for {episode.title!r}")


def parse_transcript(raw: str, mime: str) -> str:
    mime = mime.lower()
    if "json" in mime:
        return _from_json(raw)
    if "vtt" in mime or "srt" in mime or "subrip" in mime:
        return _from_cues(raw)
    if "html" in mime:
        return html_to_text(raw)
    return raw.strip()


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for selector in SPEAKER_SEGMENT_SELECTORS:
        segments = soup.select(selector)
        if segments:
            return "\n".join(_collapse(s.get_text(" ", strip=True)) for s in segments)
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    paragraphs = [_collapse(p.get_text(" ", strip=True)) for p in root.find_all("p")]
    return "\n".join(p for p in paragraphs if p)


def _from_cues(raw: str) -> str:
    lines = [line.strip() for line in raw.splitlines()]
    text_lines = [re.sub(r"<[^>]+>", "", l).strip() for l in lines if l and not CUE_TIMING_RE.match(l)]
    deduped = [l for i, l in enumerate(text_lines) if l and (i == 0 or l != text_lines[i - 1])]
    return "\n".join(deduped)


def _from_json(raw: str) -> str:
    data = json.loads(raw)
    segments = data.get("segments", data if isinstance(data, list) else [])
    lines = []
    for seg in segments:
        body = (seg.get("body") or seg.get("text") or "").strip()
        speaker = seg.get("speaker")
        if body:
            lines.append(f"{speaker}: {body}" if speaker else body)
    return "\n".join(lines)


def _guess_mime(url: str) -> str:
    path = url.lower().split("?")[0]
    for ext, mime in ((".vtt", "text/vtt"), (".srt", "application/srt"), (".json", "application/json"), (".txt", "text/plain")):
        if path.endswith(ext):
            return mime
    return "text/html"


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
