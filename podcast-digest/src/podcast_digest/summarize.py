from __future__ import annotations

from . import prompts
from .llm import LLM
from .models import Digest, Episode, Transcript

WORDS_PER_MINUTE = 150
SINGLE_PASS_MAX_WORDS = 120_000
CHUNK_WORDS = 40_000


def make_digest(llm: LLM, episode: Episode, transcript: Transcript, minutes: int = 5) -> Digest:
    notes = extract_notes(llm, episode, transcript.text)
    script = write_script(llm, episode, notes, minutes)
    return Digest(notes_markdown=notes, script=script)


def extract_notes(llm: LLM, episode: Episode, text: str) -> str:
    words = text.split()
    if len(words) > SINGLE_PASS_MAX_WORDS:
        chunks = [" ".join(words[i : i + CHUNK_WORDS]) for i in range(0, len(words), CHUNK_WORDS)]
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
