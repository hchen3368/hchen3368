from __future__ import annotations

import re

from . import prompts
from .languages import LANGUAGES, Language
from .llm import LLM
from .models import Episode

SINGLE_PASS_MAX_WORDS = 120_000
CHUNK_WORDS = 40_000
MIN_LENGTH_RATIO = 0.9
TRANSCRIPT_TAG_RE = re.compile(r"</?\s*transcript(_part)?\s*>", re.IGNORECASE)


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


def write_script(
    llm: LLM, episode: Episode, notes: str, minutes: int,
    language: Language = LANGUAGES["en"], style: str = "auto",
) -> str:
    target = minutes * language.units_per_minute
    system = prompts.SCRIPT_SYSTEM.format(writing_rules=language.writing_rules)
    script = llm.complete(
        system,
        prompts.SCRIPT_USER.format(
            length=target, unit=language.unit, minutes=minutes,
            episode=episode.title, podcast=episode.podcast_title, notes=notes,
            style_rules=prompts.STYLE_RULES[style],
            credit_line=language.credit_line.format(podcast=episode.podcast_title),
        ),
    )
    actual = language.length(script)
    if actual < MIN_LENGTH_RATIO * target:
        script = llm.complete(
            system,
            prompts.EXPAND_SCRIPT_USER.format(
                actual=actual, length=target, unit=language.unit, notes=notes, script=script,
            ),
        )
    return script


def translate_notes(llm: LLM, episode: Episode, notes: str, language: Language) -> str:
    return llm.complete(
        prompts.TRANSLATE_NOTES_SYSTEM.format(writing_rules=language.writing_rules),
        prompts.TRANSLATE_NOTES_USER.format(podcast=episode.podcast_title, episode=episode.title, notes=notes),
    )


def social_post(llm: LLM, episode: Episode, notes: str, style: str = "auto") -> dict:
    tone = "professional and precise" if style == "professional" else "warm, relatable and practical"
    return _unescape_newlines(llm.complete_json(
        prompts.SOCIAL_SYSTEM,
        prompts.SOCIAL_USER.format(podcast=episode.podcast_title, episode=episode.title, tone=tone, notes=notes),
        name="social_post",
        schema=prompts.SOCIAL_SCHEMA,
    ))


def _unescape_newlines(value):
    if isinstance(value, str):
        return value.replace("\\r\\n", "\n").replace("\\n", "\n")
    if isinstance(value, list):
        return [_unescape_newlines(v) for v in value]
    if isinstance(value, dict):
        return {k: _unescape_newlines(v) for k, v in value.items()}
    return value


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
