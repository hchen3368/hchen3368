from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEFAULT_COOKIE_FILE = Path.home() / ".config" / "podcast-digest" / "bilibili_cookies.json"
DEFAULT_TID = 201
TITLE_MAX = 80
DESC_MAX = 2000
TAG_MAX = 10
TAG_LEN_MAX = 20
RECORD_FILE = "bilibili.json"


def _gears():
    try:
        import stream_gears
    except ImportError as exc:
        raise RuntimeError("Bilibili upload needs biliup: pip install 'podcast-digest[bilibili]'") from exc
    return stream_gears


def login(cookie_file: Path = DEFAULT_COOKIE_FILE) -> Path:
    """Shows a QR code in the terminal; scan it with the Bilibili app to log in."""
    gears = _gears()
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    ret = gears.get_qrcode()
    data = json.loads(ret)
    url = (data.get("data") or {}).get("url") or data.get("url")
    _print_qr(url)
    print("请用 B站 App 扫描上面的二维码登录 / Scan with the Bilibili app")
    gears.login_by_qrcode(ret, file=str(cookie_file))
    os.chmod(cookie_file, 0o600)
    return cookie_file


def build_submission(workdir: Path, code: str = "zh", tid: int = DEFAULT_TID) -> dict:
    meta = json.loads((workdir / "meta.json").read_text())
    post = json.loads((workdir / f"post.{code}.json").read_text())
    episode = meta["episode"]
    video = workdir / f"video.{code}.mp4"
    cover = workdir / f"frame.{code}.png"
    if not video.exists():
        raise FileNotFoundError(f"{video} not found; run the pipeline with video enabled first")
    footer = (
        f"\n\n原节目：{episode['podcast_title']}《{episode['title']}》"
        + (f"\n{clean_link(episode['link'])}" if episode.get("link") else "")
        + "\n本视频为 AI 辅助整理的中文摘要，观点归原嘉宾所有，完整内容请收听原节目。"
    )
    desc = post["bilibili_description"].strip()
    desc = desc[: DESC_MAX - len(footer)] + footer
    tags = [t.strip().lstrip("#")[:TAG_LEN_MAX] for t in post["bilibili_tags"] if t.strip()][:TAG_MAX]
    return {
        "video_path": [str(video)],
        "title": post["bilibili_title"].strip()[:TITLE_MAX],
        "desc": desc,
        "tag": ",".join(dict.fromkeys(tags)),
        "tid": tid,
        "copyright": 1,
        "source": "",
        "cover": str(cover) if cover.exists() else "",
    }


def upload(workdir: Path, cookie_file: Path = DEFAULT_COOKIE_FILE, code: str = "zh",
           tid: int = DEFAULT_TID, schedule: datetime | None = None, force: bool = False,
           dry_run: bool = False) -> dict:
    record_path = workdir / RECORD_FILE
    if record_path.exists() and not force:
        raise RuntimeError(f"Already uploaded at {json.loads(record_path.read_text())['uploaded_at']}; "
                           "use --force to upload again")
    submission = build_submission(workdir, code, tid)
    if schedule:
        submission["dtime"] = int(schedule.timestamp())
    if dry_run:
        return submission
    if not cookie_file.exists():
        raise FileNotFoundError(f"{cookie_file} not found; run `podcast-digest bilibili-login` first")
    _gears().upload(cookie_file=str(cookie_file), **submission)
    record = {"uploaded_at": datetime.now().isoformat(timespec="seconds"), "title": submission["title"],
              "scheduled_for": schedule.isoformat() if schedule else None}
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return submission


def clean_link(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not k.startswith("utm_")])
    return urlunsplit(parts._replace(query=query))


def _print_qr(url: str) -> None:
    try:
        import qrcode
    except ImportError:
        print(f"Open this link on your phone (Bilibili app) to log in:\n{url}")
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.print_ascii(invert=True)
