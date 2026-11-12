from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import audio, branding, cards, prompts, subtitles, summarize, transcripts, tts, video
from .files import Stamps, fingerprint, write_text_atomic
from .languages import STYLES, Language, get_language
from .llm import LLM, OpenAILLM
from .models import Episode, slugify
from .sections import split_sections

log = logging.getLogger(__name__)

CACHED_PREFIXES = ("transcript", "notes", "script", "digest", "subtitles", "post", "video", "frame", "stamps")
SOCIAL_LANGUAGES = {"zh"}


@dataclass
class Config:
    output_dir: Path = Path("output")
    max_minutes: float | None = None
    target_minutes: float | None = None
    script_format: str = "digest"
    context: str = ""
    script_file: Path | None = None
    languages: list[str] = field(default_factory=lambda: ["zh"])
    style: str = "auto"
    social: bool = True
    video: bool = True
    transcript_sources: list[str] = field(default_factory=lambda: ["published", "local-whisper"])
    whisper_model: str = "base.en"
    openai_transcribe_model: str = "gpt-4o-mini-transcribe"
    llm_model: str = "gpt-5.4-mini"
    script_llm_model: str = "gpt-5.5"
    script_reasoning_effort: str = "medium"
    brand_name: str | None = None
    brand_tagline: str | None = None
    tts_provider: str | None = None
    tts_model: str | None = None
    tts_voice: str | None = None
    keep_audio: bool = False
    force: bool = False

    def __post_init__(self):
        if self.script_format not in prompts.SCRIPT_FORMATS:
            raise ValueError(f"Unknown script format {self.script_format!r}; choose from {sorted(prompts.SCRIPT_FORMATS)}")
        if self.style not in STYLES:
            raise ValueError(f"Unknown style {self.style!r}; choose from {STYLES}")
        for code in self.languages:
            get_language(code)


@dataclass
class Result:
    workdir: Path
    outputs: dict[str, Path]
    meta: dict


def build_transcript_sources(config: Config) -> list[transcripts.TranscriptSource]:
    factories = {
        "published": lambda: transcripts.PublishedTranscriptSource(),
        "local-whisper": lambda: transcripts.LocalWhisperSource(config.whisper_model),
        "openai-transcribe": lambda: transcripts.OpenAITranscribeSource(config.openai_transcribe_model),
    }
    unknown = set(config.transcript_sources) - factories.keys()
    if unknown:
        raise ValueError(f"Unknown transcript sources: {sorted(unknown)}")
    return [factories[name]() for name in config.transcript_sources]


def episode_workdir(config: Config, episode: Episode) -> Path:
    return config.output_dir / slugify(episode.podcast_title, 40) / episode.key


def run(
    episode: Episode,
    config: Config,
    llm: LLM | None = None,
    tts_engine: tts.TTSEngine | None = None,
) -> Result:
    script_llm = llm or OpenAILLM(config.script_llm_model, reasoning_effort=config.script_reasoning_effort)
    llm = llm or OpenAILLM(config.llm_model)
    workdir = episode_workdir(config, episode)
    if config.force:
        _clear_outputs(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    stage = _Stages(Stamps(workdir / "stamps.json"))

    with stage.timed("transcript"):
        transcript = transcripts.get_transcript(episode, workdir, build_transcript_sources(config))
    log.info("Transcript: %d words via %s", transcript.word_count, transcript.source)
    if not config.keep_audio:
        _discard_audio(workdir)

    outputs: dict[str, Path] = {}
    with stage.timed("notes"):
        notes_path = stage.text(
            workdir / "notes.md",
            fingerprint(llm.name, prompts.NOTES_SYSTEM, prompts.NOTES_USER, transcript.text,
                        summarize.episode_description(episode)),
            lambda: summarize.extract_notes(llm, episode, transcript.text),
        )
    notes = notes_path.read_text()
    outputs["notes.en"] = notes_path

    engines: dict[str, str] = {}
    for code in config.languages:
        language = get_language(code)
        engine = tts_engine or tts.build_engine(
            config.tts_provider, language, config.tts_model, config.tts_voice, rotation_key=episode.key
        )
        engines[code] = engine.name
        outputs |= _render_language(episode, config, language, notes, llm, script_llm, engine, workdir, stage)

    meta = {
        "episode": asdict(episode) | {"description_html": None},
        "transcript_source": transcript.source,
        "transcript_words": transcript.word_count,
        "languages": config.languages,
        "styles": {code: config.style for code in config.languages},
        "durations_seconds": {
            name: round(audio.duration_seconds(path), 1)
            for name, path in outputs.items() if name.startswith("digest.")
        },
        "llm": llm.name,
        "tts": engines,
        "timings_seconds": stage.timings,
    }
    write_text_atomic(workdir / "meta.json", json.dumps(meta, ensure_ascii=False, indent=2, default=str))
    return Result(workdir, outputs, meta)


def _render_language(
    episode: Episode, config: Config, language: Language, notes: str,
    llm: LLM, script_llm: LLM, tts_engine: tts.TTSEngine, workdir: Path, stage: "_Stages",
) -> dict[str, Path]:
    code = language.code
    brand = branding.brand_for(code, config.brand_name, config.brand_tagline)
    intro = branding.intro(code, brand)
    outputs: dict[str, Path] = {}
    with stage.timed(f"text.{code}"):
        if code != "en":
            outputs[f"notes.{code}"] = stage.text(
                workdir / f"notes.{code}.md",
                fingerprint(llm.name, prompts.TRANSLATE_NOTES_SYSTEM, prompts.TRANSLATE_NOTES_USER, notes, language),
                lambda: summarize.translate_notes(llm, episode, notes, language),
            )
        script_path = workdir / f"script.{code}.txt"
        if config.script_file:
            approved = Path(config.script_file).read_text().strip() + "\n"
            stage.text(script_path, fingerprint("approved", approved), lambda: approved)
        else:
            script_fp = fingerprint(
                script_llm.name, config.script_reasoning_effort, prompts.SCRIPT_SYSTEM, prompts.SCRIPT_USER,
                prompts.SHORTEN_SCRIPT_USER, prompts.OPENING_RULES, prompts.SCRIPT_FORMATS[config.script_format],
                config.context, prompts.STYLE_RULES[config.style], language, config.max_minutes,
                config.target_minutes, notes, intro,
            )
            stage.text(script_path, script_fp, lambda: summarize.write_script(
                script_llm, episode, notes, language, config.style, config.max_minutes, intro,
                config.target_minutes, config.script_format, config.context,
            ))
    outputs[f"script.{code}"] = script_path
    script = script_path.read_text()

    digest_path = workdir / f"digest.{code}.mp3"
    srt_path = workdir / f"subtitles.{code}.srt"
    timeline_path = workdir / f"timeline.{code}.json"
    with stage.timed(f"tts.{code}"):
        digest_fp = fingerprint(tts_engine.name, language.tts_instructions, language.subtitle_max_chars, script,
                                "sections-v1")
        if not all(stage.fresh(p, digest_fp) for p in (digest_path, srt_path, timeline_path)):
            timeline = tts.render_script(tts_engine, script, digest_path, language)
            write_text_atomic(srt_path, subtitles.to_srt(subtitles.build_cues(timeline, language)))
            write_text_atomic(timeline_path, json.dumps([asdict(p) for p in timeline], ensure_ascii=False))
            for path in (digest_path, srt_path, timeline_path):
                stage.record(path, digest_fp)
    outputs[f"digest.{code}"] = digest_path
    outputs[f"subtitles.{code}"] = srt_path

    post = None
    if config.social and code in SOCIAL_LANGUAGES:
        with stage.timed(f"social.{code}"):
            post, social_outputs = _render_social(episode, config, language, outputs.get(f"notes.{code}"),
                                                  notes, llm, workdir, stage, brand)
        outputs |= social_outputs

    if config.video:
        with stage.timed(f"video.{code}"):
            outputs[f"video.{code}"] = _render_video(episode, config, code, post, digest_path, srt_path,
                                                     digest_fp, workdir, stage, brand, script, llm)
    return outputs


def _render_social(episode, config, language, localized_notes_path, notes, llm, workdir, stage, brand):
    code = language.code
    source_notes = localized_notes_path.read_text() if localized_notes_path else notes
    post_json = stage.text(
        workdir / f"post.{code}.json",
        fingerprint(llm.name, prompts.SOCIAL_SYSTEM, prompts.SOCIAL_USER, prompts.SOCIAL_SCHEMA,
                    config.style, source_notes, brand),
        lambda: json.dumps(summarize.social_post(llm, episode, source_notes, config.style, brand.name),
                           ensure_ascii=False, indent=2),
    )
    post = json.loads(post_json.read_text())
    cards_dir = workdir / f"cards_{code}"
    cards_fp = fingerprint(post, config.style, brand, "cards-v3")
    marker = cards_dir / ".stamp"
    if not stage.fresh(marker, cards_fp):
        shutil.rmtree(cards_dir, ignore_errors=True)
        cards.render_social_cards(cards_dir, post, episode.podcast_title, episode.title, config.style,
                                  brand=brand.name)
        marker.write_text(cards_fp)
        stage.record(marker, cards_fp)
    card_paths = sorted(cards_dir.glob("*.png"))
    xhs = write_text_atomic(workdir / f"post.xhs.{code}.md", render_xhs_markdown(post, card_paths, workdir))
    bili = write_text_atomic(workdir / f"post.bilibili.{code}.md", render_bilibili_markdown(post, code))
    return post, {f"post.xhs.{code}": xhs, f"post.bilibili.{code}": bili, f"cards.{code}": cards_dir}


def _render_video(episode, config, code, post, digest_path, srt_path, digest_fp, workdir, stage, brand,
                  script, llm) -> Path:
    title = post["cover_title"] if post else episode.podcast_title
    subtitle = post["cover_subtitle"] if post else episode.title
    frame = workdir / f"frame.{code}.png"
    video_path = workdir / f"video.{code}.mp4"
    theme = cards.theme_for(config.style)
    sections = split_sections(script)
    slides_path = workdir / f"slides.{code}.json"
    if len(sections) > 1:
        stage.text(slides_path, fingerprint(llm.name, prompts.SLIDES_SYSTEM, prompts.SLIDES_USER, script),
                   lambda: json.dumps(summarize.slide_points(llm, sections[1:]), ensure_ascii=False, indent=2))
    slide_points = json.loads(slides_path.read_text()) if len(sections) > 1 else []
    video_fp = fingerprint(digest_fp, title, subtitle, config.style, brand, slide_points, "video-v3")
    if not stage.fresh(video_path, video_fp):
        footer = "AI 辅助整理 · 内容来自原节目" if code == "zh" else "AI-assisted summary of the original episode"
        cards.render_cover(frame, title, subtitle, episode.podcast_title, episode.title, theme,
                           brand=brand.name, size=cards.LANDSCAPE, footer=footer,
                           source_prefix="来源：" if code == "zh" else "Source: ")
        if slide_points:
            slides_dir = workdir / f"slides_{code}"
            shutil.rmtree(slides_dir, ignore_errors=True)
            slides_dir.mkdir()
            images = [frame] + [
                cards.render_question_slide(slides_dir / f"{i:02d}.png", point["label"], point["question"],
                                            point["insight"], episode.podcast_title, theme, brand=brand.name,
                                            insight_label="洞见" if code == "zh" else "Insight")
                for i, point in enumerate(slide_points, start=1)
            ]
            timeline = [tts.SpokenPart(**p) for p in json.loads((workdir / f"timeline.{code}.json").read_text())]
            starts = tts.section_starts(timeline)
            video.render_slideshow(list(zip(images, starts)), digest_path, srt_path, video_path)
        else:
            video.render_video(frame, digest_path, srt_path, video_path)
        stage.record(video_path, video_fp)
    return video_path


def render_xhs_markdown(post: dict, card_paths: list[Path], workdir: Path) -> str:
    tags = " ".join(f"#{t.lstrip('#')}" for t in post["tags"])
    card_lines = []
    for path, card in zip(card_paths[1:], post["cards"]):
        points = "\n".join(f"  - {p}" for p in card["points"])
        card_lines.append(f"- `{path.relative_to(workdir)}` **{card['heading']}**\n{points}")
    return (
        f"# {post['title']}\n\n"
        f"## 正文（复制粘贴）\n\n{post['body']}\n\n{tags}\n\n"
        f"## 图片（按顺序上传）\n\n"
        f"- `{card_paths[0].relative_to(workdir)}` 封面：**{post['cover_title']}** / {post['cover_subtitle']}\n"
        + "\n".join(card_lines) + "\n"
    )


def render_bilibili_markdown(post: dict, code: str) -> str:
    tags = "、".join(post["bilibili_tags"])
    return (
        f"# {post['bilibili_title']}\n\n"
        f"## 简介\n\n{post['bilibili_description']}\n\n"
        f"## 标签\n\n{tags}\n\n"
        f"## 上传文件\n\n"
        f"- 视频：`video.{code}.mp4`（已内嵌字幕）\n"
        f"- 外挂字幕（可选）：`subtitles.{code}.srt`\n"
        f"- 封面：`cards_{code}/00_cover.png`（或视频首帧 `frame.{code}.png`）\n"
    )


class _Stages:
    def __init__(self, stamps: Stamps):
        self.stamps = stamps
        self.timings: dict[str, float] = {}

    def fresh(self, path: Path, fp: str) -> bool:
        return self.stamps.is_fresh(path, fp)

    def record(self, path: Path, fp: str) -> None:
        self.stamps.record(path, fp)

    def text(self, path: Path, fp: str, produce) -> Path:
        if not self.fresh(path, fp):
            write_text_atomic(path, produce())
            self.record(path, fp)
        return path

    def timed(self, key: str):
        return _Timer(self.timings, key)


class _Timer:
    def __init__(self, sink: dict[str, float], key: str):
        self.sink, self.key = sink, key

    def __enter__(self):
        self.start = time.monotonic()

    def __exit__(self, *exc):
        self.sink[self.key] = round(self.sink.get(self.key, 0) + time.monotonic() - self.start, 1)


def _clear_outputs(workdir: Path) -> None:
    if not workdir.exists():
        return
    for path in workdir.iterdir():
        if path.name.startswith(CACHED_PREFIXES):
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        elif path.name.startswith("cards_"):
            shutil.rmtree(path, ignore_errors=True)


def _discard_audio(workdir: Path) -> None:
    (workdir / "episode.audio").unlink(missing_ok=True)
    shutil.rmtree(workdir / "chunks", ignore_errors=True)
