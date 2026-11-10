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
        writing_rules=(
            "Write in conversational English, like a podcast host talking to a friend: short sentences, "
            "contractions, the odd rhetorical question; no essay phrasing."
        ),
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
        units_per_minute=290,
        writing_rules=(
            "Write in natural, spoken Simplified Chinese (简体中文口语), the way a podcast host talks to a "
            "friend, not translated-sounding prose. Use short sentences. Occasional spoken connectors "
            "(其实、你想想、说白了、简单来说、有意思的是) and the odd rhetorical question are good, but do "
            "not pile up filler words. Avoid written or translated phrasing such as 进而、与此同时、"
            "其核心观点在于、值得注意的是. Keep proper nouns and technical terms in English in parentheses "
            "the first time, e.g. 纳维-斯托克斯方程（Navier-Stokes）. Use established Chinese terms, never "
            "phonetic transliterations (e.g. 毒物兴奋效应（hormesis）, not 荷尔米西斯). Use Arabic numerals. "
            "Use full-width Chinese punctuation."
        ),
        credit_line="结尾说明：本期内容整理自英文播客《{podcast}》，完整内容请收听原节目。",
        tts_instructions=(
            "你是一位中文播客主持人，正在跟朋友聊天。用自然、放松的普通话说，语速有快有慢，"
            "句子之间有自然的停顿和换气，语调有起伏，不要播音腔，不要每个字都一样重，"
            "提问的时候带一点好奇的语气。"
        ),
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
