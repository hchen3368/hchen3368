from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import audio, prompts, summarize, transcripts, tts
from .files import Stamps, fingerprint, write_text_atomic
from .llm import LLM, OpenAILLM
from .models import Episode, slugify

log = logging.getLogger(__name__)

STAGE_OUTPUTS = ("transcript.json", "transcript.txt", "notes.md", "script.txt", "digest.mp3", "stamps.json")


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
    keep_audio: bool = False
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
    return config.output_dir / slugify(episode.podcast_title, 40) / episode.key


def run(
    episode: Episode,
    config: Config,
    llm: LLM | None = None,
    tts_engine: tts.TTSEngine | None = None,
) -> Result:
    llm = llm or OpenAILLM(config.llm_model)
    tts_engine = tts_engine or tts.OpenAITTS(config.tts_model, config.tts_voice)
    workdir = episode_workdir(config, episode)
    if config.force:
        for name in STAGE_OUTPUTS:
            (workdir / name).unlink(missing_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)
    stamps = Stamps(workdir / "stamps.json")
    timings: dict[str, float] = {}

    with _timed(timings, "transcript"):
        transcript = transcripts.get_transcript(episode, workdir, build_transcript_sources(config))
    log.info("Transcript: %d words via %s", transcript.word_count, transcript.source)
    if not config.keep_audio:
        _discard_audio(workdir)

    notes_path, script_path, digest_path = workdir / "notes.md", workdir / "script.txt", workdir / "digest.mp3"
    with _timed(timings, "summarize"):
        notes_fp = fingerprint(llm.name, prompts.NOTES_SYSTEM, prompts.NOTES_USER, transcript.text)
        if not stamps.is_fresh(notes_path, notes_fp):
            write_text_atomic(notes_path, summarize.extract_notes(llm, episode, transcript.text))
            stamps.record(notes_path, notes_fp)
        notes = notes_path.read_text()
        script_fp = fingerprint(llm.name, prompts.SCRIPT_SYSTEM, prompts.SCRIPT_USER, config.minutes, notes)
        if not stamps.is_fresh(script_path, script_fp):
            write_text_atomic(script_path, summarize.write_script(llm, episode, notes, config.minutes))
            stamps.record(script_path, script_fp)

    with _timed(timings, "tts"):
        script = script_path.read_text()
        digest_fp = fingerprint(tts_engine.name, script)
        if not stamps.is_fresh(digest_path, digest_fp):
            tts.render_script(tts_engine, script, digest_path)
            stamps.record(digest_path, digest_fp)

    meta = {
        "episode": asdict(episode) | {"description_html": None},
        "transcript_source": transcript.source,
        "transcript_words": transcript.word_count,
        "script_words": len(script.split()),
        "digest_seconds": round(audio.duration_seconds(digest_path), 1),
        "llm": llm.name,
        "tts": tts_engine.name,
        "timings_seconds": timings,
    }
    write_text_atomic(workdir / "meta.json", json.dumps(meta, indent=2, default=str))
    return Result(workdir, digest_path, notes_path, script_path, meta)


def _discard_audio(workdir: Path) -> None:
    (workdir / "episode.audio").unlink(missing_ok=True)
    shutil.rmtree(workdir / "chunks", ignore_errors=True)


class _timed:
    def __init__(self, sink: dict[str, float], key: str):
        self.sink, self.key = sink, key

    def __enter__(self):
        self.start = time.monotonic()

    def __exit__(self, *exc):
        self.sink[self.key] = round(time.monotonic() - self.start, 1)
