import json
import sys
import types
from datetime import datetime

import pytest

from podcast_digest import bilibili


@pytest.fixture
def episode_dir(tmp_path):
    workdir = tmp_path / "show" / "ep-1-abcd1234"
    workdir.mkdir(parents=True)
    (workdir / "video.zh.mp4").write_bytes(b"mp4")
    (workdir / "frame.zh.png").write_bytes(b"png")
    (workdir / "meta.json").write_text(json.dumps({"episode": {
        "podcast_title": "Show", "title": "Ep 1", "link": "https://example.com/ep1/?utm_source=rss&id=7"}}))
    (workdir / "post.zh.json").write_text(json.dumps({
        "bilibili_title": "标题" * 50,
        "bilibili_description": "简介内容",
        "bilibili_tags": ["#AI", "AI", "科普", " ", "很长的标签" * 6] + [f"t{i}" for i in range(12)],
    }, ensure_ascii=False))
    return workdir


@pytest.fixture
def fake_gears(monkeypatch):
    module = types.SimpleNamespace(calls=[])
    module.upload = lambda **kwargs: module.calls.append(kwargs)
    monkeypatch.setitem(sys.modules, "stream_gears", module)
    return module


def test_submission_is_self_made_with_credit_and_clean_fields(episode_dir):
    sub = bilibili.build_submission(episode_dir)
    assert sub["copyright"] == 1 and sub["tid"] == 201
    assert len(sub["title"]) == bilibili.TITLE_MAX
    assert sub["desc"].startswith("简介内容") and "【原出处】Show《Ep 1》" in sub["desc"]
    assert "原节目链接：https://example.com/ep1/?id=7" in sub["desc"] and "AI 辅助中文整理" in sub["desc"]
    assert "https://example.com/ep1/?id=7" in sub["desc"] and "utm_" not in sub["desc"]
    tags = sub["tag"].split(",")
    assert tags[:2] == ["AI", "科普"] and len(tags) <= bilibili.TAG_MAX
    assert all(len(t) <= bilibili.TAG_LEN_MAX for t in tags)
    assert sub["cover"].endswith("frame.zh.png")


def test_upload_calls_biliup_records_and_blocks_duplicates(episode_dir, fake_gears, tmp_path):
    cookies = tmp_path / "cookies.json"
    cookies.write_text("{}")
    when = datetime(2030, 1, 1, 20, 0)
    bilibili.upload(episode_dir, cookies, schedule=when)
    call = fake_gears.calls[0]
    assert call["cookie_file"] == str(cookies) and call["dtime"] == int(when.timestamp())
    assert json.loads((episode_dir / "bilibili.json").read_text())["scheduled_for"] == when.isoformat()
    with pytest.raises(RuntimeError, match="Already uploaded"):
        bilibili.upload(episode_dir, cookies)
    bilibili.upload(episode_dir, cookies, force=True)
    assert len(fake_gears.calls) == 2


def test_dry_run_needs_no_login_and_uploads_nothing(episode_dir, fake_gears, tmp_path):
    sub = bilibili.upload(episode_dir, tmp_path / "missing.json", dry_run=True)
    assert sub["title"] and not fake_gears.calls and not (episode_dir / "bilibili.json").exists()


def test_upload_without_login_explains_next_step(episode_dir, fake_gears, tmp_path):
    with pytest.raises(FileNotFoundError, match="bilibili-login"):
        bilibili.upload(episode_dir, tmp_path / "missing.json")


def test_queue_upload_schedules_next_evening_and_skips_done(episode_dir, fake_gears, tmp_path):
    queue = tmp_path / "queue"
    queued = bilibili.enqueue(episode_dir, queue)
    assert sorted(p.name for p in queued.iterdir()) == ["frame.zh.png", "meta.json", "post.zh.json", "video.zh.mp4"]
    cookies = tmp_path / "cookies.json"
    cookies.write_text("{}")

    results = bilibili.upload_queue(queue, cookies)
    assert len(results) == 1 and results[0]["scheduled_for"].endswith("20:00:00+08:00")
    assert (queued / "bilibili.json").exists()
    assert bilibili.upload_queue(queue, cookies) == []
    assert len(fake_gears.calls) == 1


def test_next_publish_time_is_next_day_in_beijing():
    from datetime import timezone

    now = datetime(2026, 11, 10, 15, 30, tzinfo=timezone.utc)
    when = bilibili.next_publish_time(now)
    assert when.isoformat() == "2026-11-11T20:00:00+08:00"
    assert 2 * 3600 <= (when - now).total_seconds() <= 15 * 86400


def test_cli_starts_without_optional_dependencies():
    import subprocess

    code = (
        "import sys\n"
        "for name in ('PIL', 'boto3', 'faster_whisper', 'numpy'):\n"
        "    sys.modules[name] = None\n"
        "from podcast_digest import cli\n"
        "cli.main(['bilibili-upload', '--help'])\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "bilibili-upload" in result.stdout


def test_list_archives_reads_nested_cookies_and_parses_states(tmp_path):
    cookie_file = tmp_path / "c.json"
    cookie_file.write_text(json.dumps({"cookie_info": {"cookies": [
        {"name": "SESSDATA", "value": "s"}, {"name": "bili_jct", "value": "j"}]}, "token_info": {"mid": 1}}))
    assert bilibili.web_cookies(cookie_file) == {"SESSDATA": "s", "bili_jct": "j"}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": 0, "data": {"arc_audits": [{"Archive": {
                "bvid": "BV1x", "title": "t", "state": -40, "state_desc": "定时发布", "dtime": 1}}]}}

    class Session:
        def get(self, url, params, cookies, headers, timeout):
            assert cookies["SESSDATA"] == "s" and "is_pubing" in params["status"]
            return Resp()

    rows = bilibili.list_archives(cookie_file, session=Session())
    assert rows[0]["bvid"] == "BV1x" and rows[0]["state_desc"] == "定时发布"


VIEW = {"archive": {"aid": 7, "copyright": 1, "tid": 201, "cover": "http://i0/c.jpg", "title": "old",
                    "desc": "old desc", "tag": "AI,科普", "dtime": 1794398400},
        "videos": [{"filename": "n123", "title": "P1", "desc": "", "cid": 99}]}


def test_build_edit_changes_only_text_and_schedule():
    keep = bilibili.build_edit(VIEW, title="new")
    assert keep["title"] == "new" and keep["desc"] == "old desc" and keep["dtime"] == 1794398400
    assert keep["videos"] == [{"filename": "n123", "title": "P1", "desc": "", "cid": 99}]
    now = bilibili.build_edit(VIEW, desc="new desc", immediate=True)
    assert "dtime" not in now and now["desc"] == "new desc" and now["cover"] == "http://i0/c.jpg"


def test_apply_requests_dry_run_then_skips_done(tmp_path, monkeypatch):
    cookie_file = tmp_path / "c.json"
    cookie_file.write_text(json.dumps([{"name": "SESSDATA", "value": "s"}, {"name": "bili_jct", "value": "j"}]))
    calls = []

    class Resp:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return {"code": 0, "data": self.data}

    class Session:
        def get(self, url, params, cookies, headers, timeout):
            calls.append(("get", params))
            return Resp(VIEW)

        def post(self, url, params, json, cookies, headers, timeout):
            calls.append(("post", params, json))
            return Resp({})

    monkeypatch.setattr("requests.Session", Session)
    requests_dir = tmp_path / "req"
    requests_dir.mkdir()
    (requests_dir / "001.json").write_text(json.dumps({"action": "edit", "bvid": "BV1", "title": "T", "immediate": True}))
    results = bilibili.apply_requests(requests_dir, cookie_file)
    assert results[0]["ok"] and results[0]["dry_run"] and "dtime" not in results[0]["payload"]
    assert [c[0] for c in calls] == ["get"]

    (requests_dir / "002.json").write_text(json.dumps(
        {"action": "edit", "bvid": "BV1", "title": "T", "immediate": True, "dry_run": False}))
    results = bilibili.apply_requests(requests_dir, cookie_file)
    assert [r["request"] for r in results] == ["002.json"]
    assert calls[-1][0] == "post" and calls[-1][1] == {"csrf": "j"} and calls[-1][2]["title"] == "T"
