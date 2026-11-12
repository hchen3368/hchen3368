from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from . import branding

DEFAULT_COOKIE_FILE = Path.home() / ".config" / "podcast-digest" / "bilibili_cookies.json"
DEFAULT_TID = 201
TITLE_MAX = 80
DESC_MAX = 2000
TAG_MAX = 10
TAG_LEN_MAX = 20
RECORD_FILE = "bilibili.json"
QUEUE_FILES = ("video.{code}.mp4", "frame.{code}.png", "post.{code}.json", "meta.json")
DEFAULT_PUBLISH_TIME = "20:00"
DEFAULT_TIMEZONE = "Asia/Shanghai"


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
    brand = branding.brand_for(code).name
    meta = json.loads((workdir / "meta.json").read_text())
    post = json.loads((workdir / f"post.{code}.json").read_text())
    episode = meta["episode"]
    video = workdir / f"video.{code}.mp4"
    cover = workdir / f"frame.{code}.png"
    if not video.exists():
        raise FileNotFoundError(f"{video} not found; run the pipeline with video enabled first")
    footer = (
        f"\n\n【原出处】{episode['podcast_title']}《{episode['title']}》"
        + (f"\n原节目链接：{clean_link(episode['link'])}" if episode.get("link") else "")
        + f"\n本视频由{brand}基于原节目内容进行 AI 辅助中文整理，观点归原嘉宾所有，完整内容请收听原节目。"
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


PUBLISH_FILE = "publish.json"


def enqueue(workdir: Path, queue_dir: Path, code: str = "zh", title: str | None = None,
            immediate: bool = False) -> Path:
    """Copies the files an upload needs into the publish queue (committed to git for CI to upload)."""
    dest = queue_dir / workdir.parent.name / workdir.name
    dest.mkdir(parents=True, exist_ok=True)
    for pattern in QUEUE_FILES:
        name = pattern.format(code=code)
        source = workdir / name
        if not source.exists():
            raise FileNotFoundError(f"{source} not found; generate the episode with video enabled first")
        shutil.copyfile(source, dest / name)
    if title:
        post_path = dest / f"post.{code}.json"
        post = json.loads(post_path.read_text())
        post["bilibili_title"] = title
        post_path.write_text(json.dumps(post, ensure_ascii=False, indent=2))
    (dest / PUBLISH_FILE).write_text(json.dumps({"immediate": immediate}))
    return dest


def pending(queue_dir: Path) -> list[Path]:
    return sorted(p.parent for p in queue_dir.glob("*/*/meta.json") if not (p.parent / RECORD_FILE).exists())


def next_publish_time(now: datetime, at: str = DEFAULT_PUBLISH_TIME, tz: str = DEFAULT_TIMEZONE) -> datetime:
    """Next day's `at` in `tz`: leaves a review window and stays inside Bilibili's 2h-15d range."""
    local = now.astimezone(ZoneInfo(tz))
    hour, minute = (int(x) for x in at.split(":"))
    return (local + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)


def upload_queue(queue_dir: Path, cookie_file: Path, publish_at: str = DEFAULT_PUBLISH_TIME,
                 tz: str = DEFAULT_TIMEZONE, immediate: bool = False, dry_run: bool = False) -> list[dict]:
    results = []
    for workdir in pending(queue_dir):
        settings_path = workdir / PUBLISH_FILE
        settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
        now = immediate or settings.get("immediate", False)
        schedule = None if now else next_publish_time(datetime.now(timezone.utc), publish_at, tz)
        submission = upload(workdir, cookie_file, schedule=schedule, dry_run=dry_run)
        results.append({"episode": str(workdir), "title": submission["title"],
                        "scheduled_for": schedule.isoformat() if schedule else "now"})
    return results


ARCHIVES_URL = "https://member.bilibili.com/x/web/archives"


def web_cookies(cookie_file: Path) -> dict[str, str]:
    """Pulls name/value cookie pairs out of biliup's login file, whatever its nesting."""
    found: dict[str, str] = {}

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("name"), str) and "value" in node:
                found[node["name"]] = str(node["value"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(json.loads(cookie_file.read_text()))
    return found


VIEW_URL = "https://member.bilibili.com/x/vupre/web/archive/view"
EDIT_URL = "https://member.bilibili.com/x/vu/web/edit"
WEB_HEADERS = {"User-Agent": "podcast-digest/0.1 (biliup)", "Referer": "https://member.bilibili.com/"}


def _checked(response) -> dict:
    response.raise_for_status()
    data = response.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Bilibili error {data.get('code')}: {data.get('message')}")
    return data.get("data") or {}


def build_edit(view: dict, title: str | None = None, desc: str | None = None,
               immediate: bool = False) -> dict:
    """Re-submits the archive as it is, changing only title/description and, if asked, the schedule."""
    arc = view["archive"]
    payload = {
        "aid": arc["aid"], "copyright": arc["copyright"], "tid": arc["tid"], "cover": arc["cover"],
        "title": title or arc["title"], "desc": desc if desc is not None else arc.get("desc", ""),
        "tag": arc.get("tag", ""), "source": arc.get("source", ""), "dynamic": arc.get("dynamic", ""),
        "no_reprint": arc.get("no_reprint", 0),
        "videos": [{"filename": v["filename"],
                    "title": (title or arc["title"]) if len(view["videos"]) == 1 else v.get("title", ""),
                    "desc": v.get("desc", ""), "cid": v["cid"]} for v in view["videos"]],
    }
    if arc.get("dtime") and not immediate:
        payload["dtime"] = arc["dtime"]
    return payload


def edit_archive(cookie_file: Path, bvid: str, title: str | None = None, desc: str | None = None,
                 immediate: bool = False, dry_run: bool = False, session=None) -> dict:
    import requests

    session = session or requests.Session()
    cookies = web_cookies(cookie_file)
    view = _checked(session.get(VIEW_URL, params={"bvid": bvid}, cookies=cookies, headers=WEB_HEADERS, timeout=30))
    payload = build_edit(view, title, desc, immediate)
    if dry_run:
        return {"dry_run": True, "current_dtime": view["archive"].get("dtime"), "payload": payload}
    _checked(session.post(EDIT_URL, params={"csrf": cookies["bili_jct"]}, json=payload, cookies=cookies,
                          headers=WEB_HEADERS, timeout=30))
    return {"dry_run": False, "edited": bvid, "payload": payload}


def apply_requests(requests_dir: Path, cookie_file: Path) -> list[dict]:
    """Runs each pending request file (JSON with action "edit") once; writes <name>.result.json."""
    results = []
    for request_path in sorted(requests_dir.glob("*.json")):
        if request_path.name.endswith(".result.json"):
            continue
        result_path = request_path.with_name(request_path.stem + ".result.json")
        if result_path.exists():
            continue
        request = json.loads(request_path.read_text())
        try:
            if request.get("action") != "edit":
                raise ValueError(f"Unknown action {request.get('action')!r}")
            result = edit_archive(cookie_file, request["bvid"], request.get("title"), request.get("desc"),
                                  request.get("immediate", False), request.get("dry_run", True))
            result["ok"] = True
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        results.append({"request": request_path.name, **result})
    return results


def list_archives(cookie_file: Path, session=None) -> list[dict]:
    """Read-only: the account's recent submissions with review / schedule state."""
    import requests

    session = session or requests.Session()
    cookies = web_cookies(cookie_file)
    if "SESSDATA" not in cookies:
        raise RuntimeError("No SESSDATA cookie in the login file; run bilibili-login again")
    response = session.get(
        ARCHIVES_URL,
        params={"status": "is_pubing,pubed,not_pubed", "pn": 1, "ps": 20},
        cookies=cookies,
        headers={"User-Agent": "podcast-digest/0.1 (biliup)", "Referer": "https://member.bilibili.com/"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Bilibili error {data.get('code')}: {data.get('message')}")
    rows = []
    for item in (data.get("data") or {}).get("arc_audits") or []:
        arc = item.get("Archive") or {}
        rows.append({
            "bvid": arc.get("bvid"), "title": arc.get("title"), "state": arc.get("state"),
            "state_desc": arc.get("state_desc"), "reject_reason": arc.get("reject_reason"),
            "dtime": arc.get("dtime"), "ptime": arc.get("ptime"),
        })
    return rows


def _print_qr(url: str) -> None:
    try:
        import qrcode
    except ImportError:
        print(f"Open this link on your phone (Bilibili app) to log in:\n{url}")
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.print_ascii(invert=True)
