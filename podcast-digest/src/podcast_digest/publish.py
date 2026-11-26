from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .storage import Storage, read_json

PUBLISH_PATTERNS = ("digest.*.mp3", "notes*.md", "post.*.md", "cards_*/*.png", "video.*.mp4", "subtitles.*.srt")
INDEX_KEY = "index.json"


def publishable_files(workdir: Path) -> list[Path]:
    files = {p for pattern in PUBLISH_PATTERNS for p in workdir.glob(pattern) if p.is_file()}
    return sorted(files)


def publish_episode(workdir: Path, storage: Storage) -> dict:
    meta = json.loads((workdir / "meta.json").read_text())
    prefix = f"{workdir.parent.name}/{workdir.name}"
    files = {
        str(path.relative_to(workdir)): storage.put(path, f"{prefix}/{path.relative_to(workdir).as_posix()}")
        for path in publishable_files(workdir)
    }
    episode = meta["episode"]
    manifest = {
        "podcast": episode["podcast_title"],
        "title": episode["title"],
        "link": episode.get("link", ""),
        "published": episode.get("published", ""),
        "languages": meta.get("languages", []),
        "styles": meta.get("styles", {}),
        "published_digest_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": files,
    }
    manifest_url = storage.put_text(json.dumps(manifest, ensure_ascii=False, indent=2), f"{prefix}/manifest.json")
    _update_index(storage, prefix, manifest, manifest_url)
    return manifest | {"manifest_url": manifest_url}


def _update_index(storage: Storage, prefix: str, manifest: dict, manifest_url: str) -> None:
    index = [entry for entry in read_json(storage, INDEX_KEY, []) if entry.get("key") != prefix]
    index.append({
        "key": prefix,
        "podcast": manifest["podcast"],
        "title": manifest["title"],
        "languages": manifest["languages"],
        "manifest": manifest_url,
        "updated": manifest["published_digest_at"],
    })
    index.sort(key=lambda entry: entry["updated"], reverse=True)
    storage.put_text(json.dumps(index, ensure_ascii=False, indent=2), INDEX_KEY)
