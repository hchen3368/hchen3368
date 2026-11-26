from __future__ import annotations

import math

import feedparser
from bs4 import BeautifulSoup

from . import http
from .models import Episode, Podcast

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac")


def search_podcasts(term: str, limit: int = 5) -> list[Podcast]:
    data = http.get_json(
        ITUNES_SEARCH_URL, params={"term": term, "entity": "podcast", "limit": limit}
    )
    return [
        Podcast(title=r["collectionName"], feed_url=r["feedUrl"], author=r.get("artistName", ""))
        for r in data.get("results", [])
        if r.get("feedUrl")
    ]


def resolve_feed_url(feed_or_term: str) -> str:
    if feed_or_term.startswith(("http://", "https://")):
        return feed_or_term
    matches = search_podcasts(feed_or_term, limit=1)
    if not matches:
        raise LookupError(f"No podcast found for {feed_or_term!r}")
    return matches[0].feed_url


def list_episodes(feed_url: str, limit: int | None = None) -> list[Episode]:
    parsed = feedparser.parse(http.get_bytes(feed_url))
    podcast_title = parsed.feed.get("title", "")
    entries = parsed.entries[:limit] if limit else parsed.entries
    return [ep for ep in (_to_episode(podcast_title, e) for e in entries) if ep]


def select_episode(episodes: list[Episode], index: int = 0, title_contains: str | None = None) -> Episode:
    if title_contains:
        needle = title_contains.lower()
        for episode in episodes:
            if needle in episode.title.lower():
                return episode
        raise LookupError(f"No episode title contains {title_contains!r}")
    if not 0 <= index < len(episodes):
        raise LookupError(f"Episode index {index} out of range (feed has {len(episodes)} episodes)")
    return episodes[index]


def _to_episode(podcast_title: str, entry) -> Episode | None:
    audio_url = _audio_url(entry)
    if not audio_url:
        return None
    description = _description_html(entry)
    return Episode(
        podcast_title=podcast_title,
        title=entry.get("title", "untitled"),
        audio_url=audio_url,
        guid=entry.get("id", ""),
        link=entry.get("link", ""),
        published=entry.get("published", ""),
        duration_seconds=parse_duration(entry.get("itunes_duration")),
        description_html=description,
        transcript_urls=tuple(_transcript_urls(entry, description)),
    )


def _audio_url(entry) -> str | None:
    enclosures = [e for e in entry.get("enclosures", []) if e.get("href")]
    for enclosure in enclosures:
        if enclosure.get("type", "").startswith("audio"):
            return enclosure["href"]
    for enclosure in enclosures:
        if enclosure["href"].lower().split("?")[0].endswith(AUDIO_EXTENSIONS):
            return enclosure["href"]
    return None


def _description_html(entry) -> str:
    contents = [c.get("value", "") for c in entry.get("content", [])]
    return max(contents + [entry.get("summary", "")], key=len)


def _transcript_urls(entry, description_html: str) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    tag = entry.get("podcast_transcript")
    if isinstance(tag, dict) and tag.get("url"):
        urls.append((tag["url"], tag.get("type", "")))
    urls.extend((href, "text/html") for href in find_transcript_links(description_html))
    seen: set[str] = set()
    return [u for u in urls if not (u[0] in seen or seen.add(u[0]))]


def find_transcript_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return [
        a["href"]
        for a in soup.find_all("a", href=True)
        if "transcript" in a.get_text(" ", strip=True).lower()
        and a["href"].startswith(("http://", "https://"))
    ]


def parse_duration(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parts = [float(p) for p in str(value).split(":")]
    except ValueError:
        return None
    if not parts or any(math.isnan(p) or math.isinf(p) or p < 0 for p in parts):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds
