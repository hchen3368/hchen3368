from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from . import discovery, prompts, summarize
from .files import write_text_atomic
from .llm import LLM
from .models import Episode

log = logging.getLogger(__name__)

HISTORY_FILE = "history.json"
SCOUT_DESCRIPTION_CHARS = 1200


@dataclass(frozen=True)
class Source:
    name: str
    feed: str
    categories: tuple[str, ...] = ()


def load_sources(path: Path) -> list[Source]:
    return [Source(s["name"], s["feed"], tuple(s.get("categories", ())))
            for s in json.loads(path.read_text())["sources"]]


def published_at(episode: Episode) -> datetime | None:
    try:
        when = parsedate_to_datetime(episode.published)
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def recent_episodes(sources: list[Source], days: int, per_source: int, now: datetime | None = None,
                    seen: set[str] = frozenset()) -> list[tuple[Source, Episode]]:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    found = []
    for source in sources:
        try:
            episodes = discovery.list_episodes(source.feed, per_source)
        except Exception as exc:
            log.warning("Skipping %s: %s", source.name, exc)
            continue
        for episode in episodes:
            when = published_at(episode)
            if episode.key not in seen and (when is None or when >= cutoff):
                found.append((source, episode))
    return found


def propose(llm: LLM, items: list[tuple[Source, Episode]], count: int, recent_titles: list[str]) -> list[dict]:
    listing = "\n\n".join(
        f"[{i}] {episode.podcast_title} | {episode.title}\n"
        f"categories: {', '.join(source.categories)} | published: {episode.published} | "
        f"length: {summarize.spoken_duration(episode.duration_seconds)} | "
        f"transcript: {'published' if episode.transcript_urls else 'needs speech-to-text'}\n"
        f"{summarize.episode_description(episode, SCOUT_DESCRIPTION_CHARS)}"
        for i, (source, episode) in enumerate(items)
    )
    result = llm.complete_json(
        prompts.SCOUT_SYSTEM,
        prompts.SCOUT_USER.format(count=count, episodes=listing,
                                  recent="\n".join(f"- {t}" for t in recent_titles) or "(none)"),
        name="scout", schema=prompts.SCOUT_SCHEMA,
    )
    picked = []
    for candidate in result["candidates"]:
        index = candidate.pop("index")
        if not 0 <= index < len(items) or any(p["episode_key"] == items[index][1].key for p in picked):
            continue
        source, episode = items[index]
        picked.append(candidate | {
            "podcast": episode.podcast_title, "episode": episode.title, "published": episode.published,
            "duration_minutes": episode.duration_seconds // 60 if episode.duration_seconds else None,
            "feed": source.feed, "link": episode.link, "episode_key": episode.key,
            "transcript": "published" if episode.transcript_urls else "whisper",
        })
    return picked[:count]


def render_report(candidates: list[dict], date: str) -> str:
    lines = [f"# 长话短听 · 今日备选（{date}）", ""]
    for i, c in enumerate(candidates, start=1):
        minutes = f"{c['duration_minutes']} 分钟" if c["duration_minutes"] else "时长未知"
        lines += [
            f"## {i}. {c['title']}",
            f"- 问题：{c['question']}",
            f"- 观众收获：{c['viewer_value']}",
            "- 预计观点：" + "；".join(c["viewpoints"]),
            f"- 分类：{c['category']} · 评分 {c['score']}/10 · 预计 {c['estimated_minutes']} 分钟",
            f"- 来源：《{c['podcast']}》{c['episode']}（{minutes}，"
            f"{'有官方文字稿' if c['transcript'] == 'published' else '需语音转写'}）",
            "",
        ]
    return "\n".join(lines)


def produced_keys(*roots: Path) -> set[str]:
    """Episode keys already made into videos: <root>/<podcast>/<episode key>[--<topic>] directories."""
    return {d.name.split("--")[0] for root in roots if root.exists() for d in root.glob("*/*") if d.is_dir()}


def scout(llm: LLM, sources: list[Source], out_dir: Path, count: int = 5, days: int = 14,
          per_source: int = 6, now: datetime | None = None,
          produced: set[str] = frozenset()) -> tuple[Path, list[dict]]:
    now = now or datetime.now(timezone.utc)
    history_path = out_dir / HISTORY_FILE
    history = json.loads(history_path.read_text()) if history_path.exists() else []
    items = recent_episodes(sources, days, per_source, now, {h["episode_key"] for h in history} | produced)
    if not items:
        raise LookupError(f"No new episodes in the last {days} days")
    candidates = propose(llm, items, count, [h["title"] for h in history[-30:]])
    date = now.date().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    write_text_atomic(out_dir / f"{date}.json", json.dumps(candidates, ensure_ascii=False, indent=2))
    report = out_dir / f"{date}.md"
    write_text_atomic(report, render_report(candidates, date))
    history += [{"date": date, "episode_key": c["episode_key"], "title": c["title"]} for c in candidates]
    write_text_atomic(history_path, json.dumps(history, ensure_ascii=False, indent=2))
    return report, candidates

