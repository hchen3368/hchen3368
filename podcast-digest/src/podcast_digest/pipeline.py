from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import audio, summarize, transcripts, tts
from .llm import LLM, OpenAILLM
from .models import Episode, slugify

log = logging.getLogger(__name__)


@dataclass
class Config:
    output_dir: Path = Path("output")
    minutes: int = 5
    transcript_sources: list[str] = field(default_factory=lambda: ["published", "local-whisper"])
    whisper_model: str = "base.en"
    openai_transcribe_model: str = "gpt-4o-mini-transcribe"
    llm_model: str = "gpt-5.4-mini"
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "alloy"
    force: bool = False


@dataclass
class Result:
    workdir: Path
    digest_audio: Path
    notes: Path
    script: Path
    meta: dict


def build_transcript_sources(config: Config) -> list[transcripts.TranscriptSource]:
    factories = {
        "published": lambda: transcripts.PublishedTranscriptSource(),
        "local-whisper": lambda: transcripts.LocalWhisperSource(config.whisper_model),
        "openai-transcribe": lambda: transcripts.OpenAITranscribeSource(config.openai_transcribe_model),
    }
    unknown = set(config.transcript_sources) - factories.keys()
    if unknown:
        raise ValueError(f"Unknown transcript sources: {sorted(unknown)}")
    return [factories[name]() for name in config.transcript_sources]


def episode_workdir(config: Config, episode: Episode) -> Path:
    return config.output_dir / slugify(episode.podcast_title, 40) / episode.slug


def run(
    episode: Episode,
    config: Config,
    llm: LLM | None = None,
    tts_engine: tts.TTSEngine | None = None,
) -> Result:
    llm = llm or OpenAILLM(config.llm_model)
    tts_engine = tts_engine or tts.OpenAITTS(config.tts_model, config.tts_voice)
    workdir = episode_workdir(config, episode)
    if config.force and workdir.exists():
        for name in ("transcript.json", "notes.md", "script.txt", "digest.mp3"):
            (workdir / name).unlink(missing_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}

    with _timed(timings, "transcript"):
        transcript = transcripts.get_transcript(episode, workdir, build_transcript_sources(config))
    log.info("Transcript: %d words via %s", transcript.word_count, transcript.source)

    notes_path, script_path = workdir / "notes.md", workdir / "script.txt"
    with _timed(timings, "summarize"):
        if not notes_path.exists():
            notes_path.write_text(summarize.extract_notes(llm, episode, transcript.text))
        if not script_path.exists():
            script_path.write_text(
                summarize.write_script(llm, episode, notes_path.read_text(), config.minutes)
            )

    digest_path = workdir / "digest.mp3"
    with _timed(timings, "tts"):
        if not digest_path.exists():
            tts.render_script(tts_engine, script_path.read_text(), digest_path)

    meta = {
        "episode": asdict(episode) | {"description_html": None},
        "transcript_source": transcript.source,
        "transcript_words": transcript.word_count,
        "script_words": len(script_path.read_text().split()),
        "digest_seconds": round(audio.duration_seconds(digest_path), 1),
        "llm": llm.name,
        "tts": tts_engine.name,
        "timings_seconds": timings,
    }
    (workdir / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    return Result(workdir, digest_path, notes_path, script_path, meta)


class _timed:
    def __init__(self, sink: dict[str, float], key: str):
        self.sink, self.key = sink, key

    def __enter__(self):
        self.start = time.monotonic()

    def __exit__(self, *exc):
        self.sink[self.key] = round(time.monotonic() - self.start, 1)
