from __future__ import annotations

import re
from dataclasses import dataclass

from .languages import Language
from .tts import SpokenPart

TRAILING_PUNCTUATION = "，。、；：,.;:"
SENTENCE_END = ("。", "！", "？", "!", "?", ".")


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def build_cues(timeline: list[SpokenPart], language: Language) -> list[Cue]:
    """Spreads each spoken part's duration over its subtitle lines in proportion to their length."""
    cues: list[Cue] = []
    for part in timeline:
        lines = subtitle_lines(part.text, language)
        weights = [max(len(re.sub(r"\s", "", line)), 1) for line in lines]
        total = sum(weights)
        cursor = part.start
        for line, weight in zip(lines, weights):
            span = (part.end - part.start) * weight / total
            cues.append(Cue(cursor, cursor + span, line))
            cursor += span
    return cues


def subtitle_lines(text: str, language: Language) -> list[str]:
    lines: list[str] = []
    current = ""
    for clause in (c.strip() for c in language.clause_split.split(text) if c and c.strip()):
        candidate = _concat(current, clause, language)
        if current and (current.endswith(SENTENCE_END) or len(candidate) > language.subtitle_max_chars):
            lines.append(current)
            current = clause
        else:
            current = candidate
        while len(current) > language.subtitle_max_chars:
            cut = _cut_point(current, language.subtitle_max_chars)
            lines.append(current[:cut].strip())
            current = current[cut:].strip()
    if current:
        lines.append(current)
    return [line.rstrip(TRAILING_PUNCTUATION) or line for line in lines]


def to_srt(cues: list[Cue]) -> str:
    return "\n".join(
        f"{i}\n{_timestamp(c.start)} --> {_timestamp(c.end)}\n{c.text}\n" for i, c in enumerate(cues, 1)
    )


def _concat(left: str, right: str, language: Language) -> str:
    if not left:
        return right
    return left + right if language.unit == "characters" else f"{left} {right}"


def _cut_point(text: str, limit: int) -> int:
    space = text.rfind(" ", 0, limit + 1)
    return space if space > 0 else limit


def _timestamp(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
