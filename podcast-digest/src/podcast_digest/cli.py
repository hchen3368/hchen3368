from __future__ import annotations

import argparse
import json
from datetime import datetime
import logging
from pathlib import Path

from . import bilibili, discovery, pipeline, publish, storage, tts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="podcast-digest", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="Find podcasts and their RSS feeds")
    search.add_argument("term")
    search.add_argument("--limit", type=int, default=5)

    episodes = sub.add_parser("episodes", help="List recent episodes of a podcast")
    episodes.add_argument("podcast", help="RSS feed URL or search term")
    episodes.add_argument("--limit", type=int, default=10)

    run = sub.add_parser("run", help="Produce an audio digest for one episode")
    run.add_argument("podcast", help="RSS feed URL or search term")
    run.add_argument("--episode", type=int, default=0, help="Index in the feed (0 = latest)")
    run.add_argument("--title-contains", help="Pick the first episode whose title contains this")
    run.add_argument("--target-minutes", type=float,
                     help="Soft length target guiding what the script keeps; never trimmed or padded afterwards")
    run.add_argument("--max-minutes", type=float,
                     help="Optional hard cap on digest length; by default length follows content")
    run.add_argument("--language", default="zh", help="Comma-separated output languages (default zh), e.g. zh,en")
    run.add_argument("--style", choices=pipeline.STYLES, default="auto",
                     help="Digest opening: hook (relatable question), professional, or auto")
    run.add_argument("--no-social", action="store_true", help="Skip Xiaohongshu/Bilibili posts and cards")
    run.add_argument("--no-video", action="store_true", help="Skip the MP4 (cover + narration + subtitles)")
    run.add_argument("--publish", action="store_true", help="Upload shareable outputs (see `publish`)")
    run.add_argument("--output-dir", type=Path, default=Path("output"))
    run.add_argument(
        "--transcript-sources", default="published,local-whisper",
        help="Comma-separated, tried in order: published, local-whisper, openai-transcribe",
    )
    run.add_argument("--whisper-model", default="base.en")
    run.add_argument("--llm-model", default="gpt-5.4-mini")
    run.add_argument("--tts-provider", choices=sorted(tts.PROVIDERS),
                     help="Speech provider; default per language (zh: minimax, en: openai)")
    run.add_argument("--tts-model", help="TTS model; default per provider")
    run.add_argument("--voice", help="Voice id, or 女声/男声 (female/male), or 轮流/alternate to rotate by episode; default 女声")
    run.add_argument("--brand-name", help="Our channel name for the intro (env PD_BRAND_NAME)")
    run.add_argument("--brand-tagline", help="Tagline said before the name (env PD_BRAND_TAGLINE)")
    run.add_argument("--keep-audio", action="store_true", help="Keep the downloaded episode audio")
    run.add_argument(
        "--force", action="store_true",
        help="Recompute transcript, notes, script and digest (downloaded audio and chunks are reused)",
    )

    voices = sub.add_parser("voices", help="List system voices of a TTS provider (MiniMax)")
    voices.add_argument("--filter", default="", help="Only voices whose id or name contains this")

    bl = sub.add_parser("bilibili-login", help="Log in to Bilibili by scanning a QR code (run on your computer)")
    bl.add_argument("--cookies", type=Path, default=bilibili.DEFAULT_COOKIE_FILE)

    bu = sub.add_parser("bilibili-upload", help="Upload an episode's Chinese video to Bilibili as 自制")
    bu.add_argument("episode_dir", type=Path, help="output/<podcast>/<episode> directory")
    bu.add_argument("--cookies", type=Path, default=bilibili.DEFAULT_COOKIE_FILE)
    bu.add_argument("--tid", type=int, default=bilibili.DEFAULT_TID, help="Bilibili category id (default 201 科学科普)")
    bu.add_argument("--schedule", help='Publish later, local time "YYYY-MM-DD HH:MM" (2 hours to 15 days ahead)')
    bu.add_argument("--dry-run", action="store_true", help="Show what would be submitted without uploading")
    bu.add_argument("--force", action="store_true", help="Upload again even if already uploaded")

    pub = sub.add_parser(
        "publish",
        help="Upload digests, notes, posts, cards and videos (never transcripts) to storage",
        description="Storage is configured with env vars: PD_STORAGE=local|s3, PD_LOCAL_ROOT, "
                    "PD_S3_BUCKET, PD_S3_PREFIX, PD_S3_ENDPOINT_URL, PD_PUBLIC_BASE_URL. "
                    "S3 credentials come from the standard AWS environment/profile.",
    )
    pub.add_argument("episode_dirs", nargs="+", type=Path, help="output/<podcast>/<episode> directories")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.command == "search":
        for podcast in discovery.search_podcasts(args.term, args.limit):
            print(f"{podcast.title} — {podcast.author}\n  {podcast.feed_url}")
    elif args.command == "episodes":
        feed = discovery.resolve_feed_url(args.podcast)
        for i, ep in enumerate(discovery.list_episodes(feed, args.limit)):
            mins = f"{ep.duration_seconds // 60} min" if ep.duration_seconds else "?"
            flag = " [transcript]" if ep.transcript_urls else ""
            print(f"[{i}] {ep.title} ({mins}){flag}")
    elif args.command == "run":
        feed = discovery.resolve_feed_url(args.podcast)
        episode = discovery.select_episode(
            discovery.list_episodes(feed), args.episode, args.title_contains
        )
        config = pipeline.Config(
            output_dir=args.output_dir,
            max_minutes=args.max_minutes,
            target_minutes=args.target_minutes,
            transcript_sources=[s.strip() for s in args.transcript_sources.split(",") if s.strip()],
            languages=[s.strip() for s in args.language.split(",") if s.strip()],
            style=args.style,
            social=not args.no_social,
            video=not args.no_video,
            whisper_model=args.whisper_model,
            llm_model=args.llm_model,
            tts_provider=args.tts_provider,
            tts_model=args.tts_model,
            tts_voice=args.voice,
            brand_name=args.brand_name,
            brand_tagline=args.brand_tagline,
            keep_audio=args.keep_audio,
            force=args.force,
        )
        result = pipeline.run(episode, config)
        print(f"\nOutputs in {result.workdir}:")
        for name, path in result.outputs.items():
            print(f"  {name:<22} {path.name}")
        if args.publish:
            _publish([result.workdir])
    elif args.command == "voices":
        for v in tts.MiniMaxTTS().list_voices():
            line = f"{v.get('voice_id')}\t{v.get('voice_name', '')}\t{' '.join(v.get('description') or [])}"
            if args.filter.lower() in line.lower():
                print(line)
    elif args.command == "bilibili-login":
        print(f"Logged in; credentials saved to {bilibili.login(args.cookies)} (keep this file private)")
    elif args.command == "bilibili-upload":
        schedule = datetime.strptime(args.schedule, "%Y-%m-%d %H:%M") if args.schedule else None
        submission = bilibili.upload(args.episode_dir, args.cookies, tid=args.tid, schedule=schedule,
                                     force=args.force, dry_run=args.dry_run)
        print(json.dumps(submission, ensure_ascii=False, indent=2))
        if not args.dry_run:
            print("已提交投稿。请到 B站创作中心确认，并按需勾选“作品含 AI 生成内容”声明。")
    elif args.command == "publish":
        _publish(args.episode_dirs)


def _publish(workdirs: list[Path]) -> None:
    target = storage.storage_from_env()
    for workdir in workdirs:
        manifest = publish.publish_episode(workdir, target)
        print(f"Published {len(manifest['files'])} files to {target.name}\n  manifest: {manifest['manifest_url']}")


if __name__ == "__main__":
    main()
