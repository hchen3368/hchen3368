from __future__ import annotations

import re

from . import prompts
from .llm import LLM
from .models import Digest, Episode, Transcript

WORDS_PER_MINUTE = 150
SINGLE_PASS_MAX_WORDS = 120_000
CHUNK_WORDS = 40_000
TRANSCRIPT_TAG_RE = re.compile(r"</?\s*transcript(_part)?\s*>", re.IGNORECASE)


def make_digest(llm: LLM, episode: Episode, transcript: Transcript, minutes: int = 5) -> Digest:
    notes = extract_notes(llm, episode, transcript.text)
    script = write_script(llm, episode, notes, minutes)
    return Digest(notes_markdown=notes, script=script)


def extract_notes(llm: LLM, episode: Episode, text: str) -> str:
    text = TRANSCRIPT_TAG_RE.sub("", text)
    if len(text.split()) > SINGLE_PASS_MAX_WORDS:
        chunks = chunk_lines(text, CHUNK_WORDS)
        text = "\n\n".join(
            llm.complete(
                prompts.NOTES_SYSTEM,
                prompts.CHUNK_NOTES_USER.format(
                    podcast=episode.podcast_title, episode=episode.title,
                    part=i + 1, total=len(chunks), transcript=chunk,
                ),
            )
            for i, chunk in enumerate(chunks)
        )
    return llm.complete(
        prompts.NOTES_SYSTEM,
        prompts.NOTES_USER.format(podcast=episode.podcast_title, episode=episode.title, transcript=text),
    )


def write_script(llm: LLM, episode: Episode, notes: str, minutes: int) -> str:
    return llm.complete(
        prompts.SCRIPT_SYSTEM,
        prompts.SCRIPT_USER.format(
            words=minutes * WORDS_PER_MINUTE, minutes=minutes,
            episode=episode.title, podcast=episode.podcast_title, notes=notes,
        ),
    )


def chunk_lines(text: str, max_words: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    count = 0
    for line in text.splitlines():
        words = len(line.split())
        if current and count + words > max_words:
            chunks.append("\n".join(current))
            current, count = [], 0
        current.append(line)
        count += words
    if current:
        chunks.append("\n".join(current))
    return chunks
