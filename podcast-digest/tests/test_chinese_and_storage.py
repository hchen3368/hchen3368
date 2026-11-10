import json

import boto3
import pytest
from moto import mock_aws

from podcast_digest import publish, subtitles
from podcast_digest.languages import LANGUAGES
from podcast_digest.storage import LocalStorage, S3Storage, storage_from_env
from podcast_digest.tts import SpokenPart, split_text

ZH = LANGUAGES["zh"]


def test_chinese_split_without_spaces_and_keeps_text():
    text = "冷水澡真的有用吗？研究说，关键在于不适感。每周累计十一分钟就够了！" * 40
    chunks = split_text(text, ZH.tts_max_chars, ZH.sentence_split)
    assert len(chunks) > 1
    assert all(len(c) <= ZH.tts_max_chars for c in chunks)
    assert "".join(chunks) == text


def test_chinese_subtitle_lines_are_short_and_drop_trailing_punctuation():
    lines = subtitles.subtitle_lines("冷水澡真的有用吗？研究人员发现，关键在于身体感受到明显的不适感，而不是水温本身。", ZH)
    assert all(len(line) <= ZH.subtitle_max_chars for line in lines)
    assert not any(line.endswith(("，", "。")) for line in lines)
    assert lines[0] == "冷水澡真的有用吗？"


def test_cues_cover_part_duration_in_order():
    timeline = [SpokenPart("第一句话。第二句话比较长一些。", 0.0, 4.0), SpokenPart("第三句。", 4.0, 5.0)]
    cues = subtitles.build_cues(timeline, ZH)
    assert cues[0].start == 0.0 and abs(cues[-1].end - 5.0) < 1e-6
    assert all(a.end <= b.start + 1e-9 for a, b in zip(cues, cues[1:]))
    srt = subtitles.to_srt(cues)
    assert "00:00:05,000" in srt and "第三句" in srt


def _episode_dir(tmp_path):
    workdir = tmp_path / "output" / "show" / "ep-1-abcd1234"
    (workdir / "cards_zh").mkdir(parents=True)
    for name in ["digest.zh.mp3", "notes.md", "notes.zh.md", "post.xhs.zh.md", "video.zh.mp4",
                 "subtitles.zh.srt", "transcript.txt", "transcript.json", "script.zh.txt", "stamps.json"]:
        (workdir / name).write_bytes(b"x")
    (workdir / "cards_zh" / "00_cover.png").write_bytes(b"png")
    (workdir / "meta.json").write_text(json.dumps({
        "episode": {"podcast_title": "Show", "title": "Ep 1", "link": "https://e/1", "published": ""},
        "languages": ["zh"], "styles": {"zh": "hook"},
    }))
    return workdir


def test_publish_never_uploads_transcripts(tmp_path):
    names = {p.name for p in publish.publishable_files(_episode_dir(tmp_path))}
    assert "transcript.txt" not in names and "transcript.json" not in names
    assert {"digest.zh.mp3", "notes.zh.md", "post.xhs.zh.md", "video.zh.mp4", "00_cover.png"} <= names


def test_publish_local_writes_manifest_and_index(tmp_path):
    store = LocalStorage(tmp_path / "published", public_base_url="https://cdn.example.com")
    workdir = _episode_dir(tmp_path)
    manifest = publish.publish_episode(workdir, store)
    publish.publish_episode(workdir, store)
    assert manifest["files"]["digest.zh.mp3"] == "https://cdn.example.com/show/ep-1-abcd1234/digest.zh.mp3"
    assert (tmp_path / "published/show/ep-1-abcd1234/cards_zh/00_cover.png").exists()
    index = json.loads((tmp_path / "published/index.json").read_text())
    assert len(index) == 1 and index[0]["title"] == "Ep 1"


def test_local_storage_rejects_escaping_keys(tmp_path):
    with pytest.raises(ValueError):
        LocalStorage(tmp_path).put_text("x", "../evil.json")


@mock_aws
def test_publish_to_s3_compatible_bucket(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket="digests")
    store = S3Storage("digests", prefix="v1", public_base_url="https://pub.example.r2.dev", client=client)
    manifest = publish.publish_episode(_episode_dir(tmp_path), store)

    keys = {o["Key"] for o in client.list_objects_v2(Bucket="digests")["Contents"]}
    assert "v1/show/ep-1-abcd1234/digest.zh.mp3" in keys
    assert "v1/index.json" in keys
    assert not any("transcript" in k for k in keys)
    head = client.head_object(Bucket="digests", Key="v1/show/ep-1-abcd1234/post.xhs.zh.md")
    assert head["ContentType"] == "text/markdown; charset=utf-8"
    assert manifest["manifest_url"] == "https://pub.example.r2.dev/v1/show/ep-1-abcd1234/manifest.json"


def test_storage_from_env():
    assert isinstance(storage_from_env({"PD_STORAGE": "local"}), LocalStorage)
    s3 = storage_from_env({"PD_STORAGE": "s3", "PD_S3_BUCKET": "b", "PD_S3_ENDPOINT_URL": "https://x.r2"})
    assert isinstance(s3, S3Storage) and s3.bucket == "b"
    with pytest.raises(ValueError):
        storage_from_env({"PD_STORAGE": "ftp"})


def test_card_lines_avoid_orphans_and_leading_punctuation():
    from podcast_digest.cards import balance_cjk_lines

    assert balance_cjk_lines(["棕色脂肪参与产热，是关键机制之", "一"]) == ["棕色脂肪参与产热，是关键机", "制之一"]
    assert balance_cjk_lines(["冷信号会传到下丘脑", "，并触发反应"]) == ["冷信号会传到下丘脑，", "并触发反应"]
    assert balance_cjk_lines(["Brown fat matters", "a"]) == ["Brown fat matters", "a"]


def test_social_post_unescapes_double_escaped_newlines():
    from podcast_digest.models import Episode
    from podcast_digest.summarize import social_post

    class EscapingLLM:
        name = "x"

        def complete_json(self, system, user, name, schema):
            return {"body": "第一段\\n\\n第二段", "cards": [{"heading": "h", "points": ["a\\nb"]}]}

    post = social_post(EscapingLLM(), Episode(podcast_title="p", title="t", audio_url="https://x/a.mp3"), "n")
    assert post["body"] == "第一段\n\n第二段"
    assert post["cards"][0]["points"] == ["a\nb"]
