from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import discovery, pipeline


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
    run.add_argument("--minutes", type=int, default=5)
    run.add_argument("--output-dir", type=Path, default=Path("output"))
    run.add_argument(
        "--transcript-sources", default="published,local-whisper",
        help="Comma-separated, tried in order: published, local-whisper, openai-transcribe",
    )
    run.add_argument("--whisper-model", default="base.en")
    run.add_argument("--llm-model", default="gpt-5.4-mini")
    run.add_argument("--tts-model", default="gpt-4o-mini-tts")
    run.add_argument("--voice", default="alloy")
    run.add_argument("--keep-audio", action="store_true", help="Keep the downloaded episode audio")
    run.add_argument(
        "--force", action="store_true",
        help="Recompute transcript, notes, script and digest (downloaded audio and chunks are reused)",
    )

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
            minutes=args.minutes,
            transcript_sources=[s.strip() for s in args.transcript_sources.split(",") if s.strip()],
            whisper_model=args.whisper_model,
            llm_model=args.llm_model,
            tts_model=args.tts_model,
            tts_voice=args.voice,
            keep_audio=args.keep_audio,
            force=args.force,
        )
        result = pipeline.run(episode, config)
        print(f"\nDigest ready: {result.digest_audio} ({result.meta['digest_seconds']}s)")
        print(f"Notes: {result.notes}\nScript: {result.script}")


if __name__ == "__main__":
    main()
