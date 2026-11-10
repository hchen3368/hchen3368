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
