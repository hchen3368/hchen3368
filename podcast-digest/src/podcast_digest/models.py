from __future__ import annotations

import hashlib
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
    guid: str = ""
    link: str = ""
    published: str = ""
    duration_seconds: int | None = None
    description_html: str = ""
    transcript_urls: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def key(self) -> str:
        identity = self.guid or self.audio_url
        return f"{slugify(self.title, 60)}-{hashlib.sha1(identity.encode()).hexdigest()[:8]}"


@dataclass(frozen=True)
class Transcript:
    text: str
    source: str

    @property
    def word_count(self) -> int:
        return len(self.text.split())


def slugify(value: str, max_len: int = 80) -> str:
    value = re.sub(r"[^\w]+", "-", value, flags=re.UNICODE).strip("-_").lower()
    return value[:max_len].rstrip("-_") or "untitled"
