from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    unit: str
    units_per_minute: int
    writing_rules: str
    credit_line: str
    tts_instructions: str
    tts_max_chars: int
    subtitle_max_chars: int
    sentence_split: re.Pattern
    clause_split: re.Pattern

    def length(self, text: str) -> int:
        return len(re.sub(r"\s", "", text)) if self.unit == "characters" else len(text.split())


LANGUAGES = {
    "en": Language(
        code="en",
        name="English",
        unit="words",
        units_per_minute=150,
        writing_rules="Write in English.",
        credit_line='End with: "This was a summary of {podcast}. Find the full episode wherever you get podcasts."',
        tts_instructions="Warm, clear podcast narrator. Natural pace, light emphasis on key ideas.",
        tts_max_chars=3000,
        subtitle_max_chars=42,
        sentence_split=re.compile(r"(?<=[.!?])\s+"),
        clause_split=re.compile(r"(?<=[,.!?;:])\s+"),
    ),
    "zh": Language(
        code="zh",
        name="Simplified Chinese",
        unit="characters",
        units_per_minute=260,
        writing_rules=(
            "Write in natural, spoken Simplified Chinese (简体中文口语), not translated-sounding prose. "
            "Keep proper nouns and technical terms in English in parentheses the first time, e.g. "
            "纳维-斯托克斯方程（Navier-Stokes）. Use Arabic numerals. Use full-width Chinese punctuation."
        ),
        credit_line="结尾说明：本期内容整理自英文播客《{podcast}》，完整内容请收听原节目。",
        tts_instructions="用标准、自然的普通话朗读，语气亲切清晰，像播客主播一样，语速适中，重点处稍作强调。",
        tts_max_chars=800,
        subtitle_max_chars=20,
        sentence_split=re.compile(r"(?<=[。！？；])|(?<=[.!?])\s+"),
        clause_split=re.compile(r"(?<=[，。！？；：、])|(?<=[,.!?;:])\s+"),
    ),
}

STYLES = ("auto", "hook", "professional")


def get_language(code: str) -> Language:
    try:
        return LANGUAGES[code]
    except KeyError:
        raise ValueError(f"Unsupported language {code!r}; choose from {sorted(LANGUAGES)}") from None
