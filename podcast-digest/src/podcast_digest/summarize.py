from __future__ import annotations

import re

from . import prompts
from .languages import LANGUAGES, Language
from .llm import LLM
from .models import Episode

SINGLE_PASS_MAX_WORDS = 20_000
CHUNK_WORDS = 10_000
DESCRIPTION_MAX_CHARS = 3000
URL_RE = re.compile(r"https?://\S+")
TRANSCRIPT_TAG_RE = re.compile(r"</?\s*(transcript(_part)?|description)\s*>", re.IGNORECASE)


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
        prompts.NOTES_USER.format(
            podcast=episode.podcast_title, episode=episode.title,
            description=episode_description(episode), transcript=text,
        ),
    )


def episode_description(episode: Episode, max_chars: int = DESCRIPTION_MAX_CHARS) -> str:
    from bs4 import BeautifulSoup

    text = BeautifulSoup(episode.description_html or "", "html.parser").get_text(" ", strip=True)
    text = TRANSCRIPT_TAG_RE.sub("", URL_RE.sub("", text))
    return re.sub(r"\s+", " ", text).strip()[:max_chars] or "(none)"


def write_script(
    llm: LLM, episode: Episode, notes: str,
    language: Language = LANGUAGES["en"], style: str = "auto", max_minutes: float | None = None,
    intro: str = "", target_minutes: float | None = None, script_format: str = "digest",
    context: str = "",
) -> str:
    rate = language.units_per_minute
    max_length = int(max_minutes * rate) if max_minutes else None
    length_limit = ""
    if target_minutes:
        low, high = int(target_minutes * 0.8 * rate), int(target_minutes * 1.2 * rate)
        length_limit += (
            f" Aim for about {target_minutes:g} minutes spoken (roughly {low}-{high} {language.unit}): "
            "choose the most important questions, answers, tensions and insights to fit that, rather "
            "than covering everything thinly."
        )
    if max_length:
        length_limit += f" Hard limit: {max_length} {language.unit}."
    system = prompts.SCRIPT_SYSTEM.format(spoken_rules=language.spoken_rules)
    credit_line = language.credit_line.format(podcast=episode.podcast_title)
    script_format_rules = prompts.SCRIPT_FORMATS[script_format]
    script = llm.complete(
        system,
        prompts.SCRIPT_USER.format(
            episode=episode.title, podcast=episode.podcast_title, notes=notes, length_limit=length_limit,
            goal=script_format_rules["goal"],
            body=script_format_rules["body"].format(credit_line=credit_line),
            opening_rules=prompts.OPENING_RULES.format(
                style_rule=prompts.STYLE_RULES[style], duration=spoken_duration(episode.duration_seconds)
            ),
            intro=intro or "(none)",
        ) + (f"\n\nEditor-provided context (verified by our editor; may be used in the opening):\n{context}"
             if context else ""),
    )
    actual = language.length(script) + language.length(intro)
    if max_length and actual > max_length:
        script = llm.complete(
            system,
            prompts.SHORTEN_SCRIPT_USER.format(
                actual=actual, max_length=max_length, unit=language.unit, script=script,
            ),
        )
    script = language.polish_spoken(script.strip())
    return f"{intro}\n\n{script}" if intro else script


def spoken_duration(seconds: int | None) -> str:
    if not seconds:
        return "(unknown length)"
    hours, minutes = divmod(round(seconds / 60), 60)
    return f"about {hours} hours {minutes} minutes" if hours else f"about {minutes} minutes"


def translate_notes(llm: LLM, episode: Episode, notes: str, language: Language) -> str:
    return llm.complete(
        prompts.TRANSLATE_NOTES_SYSTEM.format(writing_rules=language.writing_rules),
        prompts.TRANSLATE_NOTES_USER.format(podcast=episode.podcast_title, episode=episode.title, notes=notes),
    )


def social_post(llm: LLM, episode: Episode, notes: str, style: str = "auto", brand: str = "") -> dict:
    tone = "professional and precise" if style == "professional" else "warm, relatable and practical"
    return _unescape_newlines(llm.complete_json(
        prompts.SOCIAL_SYSTEM,
        prompts.SOCIAL_USER.format(
            brand=brand or "(unnamed)", podcast=episode.podcast_title, episode=episode.title,
            tone=tone, notes=notes,
        ),
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
