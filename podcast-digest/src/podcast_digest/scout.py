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
BACKLOG_FILE = "backlog.json"
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
        carried = f"（{c['first_proposed']} 起备选）" if c.get("first_proposed", date) != date else "（新）"
        lines += [
            f"## {i}. {c['title']} {carried}",
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


def _load(path: Path) -> list:
    return json.loads(path.read_text()) if path.exists() else []


def scout(llm: LLM, sources: list[Source], out_dir: Path, count: int = 5, days: int = 14,
          per_source: int = 6, now: datetime | None = None,
          produced: set[str] = frozenset()) -> tuple[Path, list[dict]]:
    """Today's list: candidates still waiting in the backlog first, topped up with new proposals."""
    now = now or datetime.now(timezone.utc)
    date = now.date().isoformat()
    history = _load(out_dir / HISTORY_FILE)
    backlog = [c for c in _load(out_dir / BACKLOG_FILE) if c["episode_key"] not in produced][:count]
    fresh = []
    if len(backlog) < count:
        items = recent_episodes(sources, days, per_source, now, {h["episode_key"] for h in history} | produced)
        if items:
            fresh = [c | {"first_proposed": date}
                     for c in propose(llm, items, count - len(backlog), [h["title"] for h in history[-30:]])]
        elif not backlog:
            raise LookupError(f"No new episodes in the last {days} days")
    candidates = backlog + fresh
    out_dir.mkdir(parents=True, exist_ok=True)
    write_text_atomic(out_dir / f"{date}.json", json.dumps(candidates, ensure_ascii=False, indent=2))
    report = out_dir / f"{date}.md"
    write_text_atomic(report, render_report(candidates, date))
    write_text_atomic(out_dir / BACKLOG_FILE, json.dumps(candidates, ensure_ascii=False, indent=2))
    history += [{"date": date, "episode_key": c["episode_key"], "title": c["title"]} for c in fresh]
    write_text_atomic(out_dir / HISTORY_FILE, json.dumps(history, ensure_ascii=False, indent=2))
    return report, candidates


def decide(out_dir: Path, date: str, make: list[int] = (), drop: list[int] = ()) -> list[dict]:
    """Takes the chosen (to make) and rejected candidates of a day's list out of the backlog."""
    day = _load(out_dir / f"{date}.json")
    removed = {day[n - 1]["episode_key"]: ("made" if n in make else "dropped") for n in [*make, *drop]}
    backlog = [c for c in _load(out_dir / BACKLOG_FILE) if c["episode_key"] not in removed]
    write_text_atomic(out_dir / BACKLOG_FILE, json.dumps(backlog, ensure_ascii=False, indent=2))
    history = _load(out_dir / HISTORY_FILE)
    for entry in history:
        if entry["episode_key"] in removed:
            entry["decision"] = removed[entry["episode_key"]]
    write_text_atomic(out_dir / HISTORY_FILE, json.dumps(history, ensure_ascii=False, indent=2))
    return [day[n - 1] for n in make]
