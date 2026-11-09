from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Podcast:
    title: str
    feed_url: str
    author: str = ""


@dataclass(frozen=True)
class Episode:
    podcast_title: str
    title: str
    audio_url: str
    link: str = ""
    published: str = ""
    duration_seconds: int | None = None
    description_html: str = ""
    transcript_urls: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def slug(self) -> str:
        return slugify(self.title)


@dataclass(frozen=True)
class Transcript:
    text: str
    source: str

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass(frozen=True)
class Digest:
    notes_markdown: str
    script: str


def slugify(value: str, max_len: int = 80) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value[:max_len].rstrip("-") or "untitled"
