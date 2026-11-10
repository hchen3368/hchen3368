import json
import subprocess
from pathlib import Path

import pytest

from podcast_digest import pipeline, tts
from podcast_digest.models import Episode, Transcript

POST = {
    "title": "冷热交替真的有用吗🧊",
    "cover_title": "冷热交替",
    "cover_subtitle": "提升代谢健康的科学方法",
    "cards": [
        {"heading": "冷暴露", "points": ["感到不适才有效", "每周累计11分钟"]},
        {"heading": "热暴露", "points": ["每周57分钟桑拿"]},
    ],
    "body": "正文内容。",
    "tags": ["健康", "#代谢"],
    "bilibili_title": "冷热暴露与代谢健康",
    "bilibili_description": "简介。",
    "bilibili_tags": ["健康", "科普"],
}


class FakeLLM:
    name = "fake"

    def __init__(self):
        self.calls = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append(user)
        if "<transcript>" in user:
            return "## One-line gist\nNotes."
        if "Translate these notes" in user:
            return "## 一句话总结\n笔记。"
        if "Simplified Chinese" in system:
            return "你每天洗冷水澡吗？这是一段中文脚本，用来测试字幕。最后感谢收听。" * 20
        return "This is the script. It has two sentences. " * 45

    def complete_json(self, system, user, name, schema):
        self.calls.append(user)
        return POST


class FakeTTS:
    name = "fake-tts"

    def synthesize(self, text: str, dest: Path, instructions: str) -> Path:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=24000",
             "-t", "1", str(dest)],
            check=True,
        )
        return dest


class FakeSource:
    name = "fake"

    def __init__(self):
        self.calls = 0

    def fetch(self, episode, workdir):
        self.calls += 1
        return Transcript(text="word " * 600, source="fake")


@pytest.fixture
def episode():
    return Episode(podcast_title="Show", title="Ep 1: Hello", audio_url="https://example.com/a.mp3")


def test_pipeline_end_to_end_and_caches(tmp_path, monkeypatch, episode):
    source = FakeSource()
    monkeypatch.setattr(pipeline, "build_transcript_sources", lambda config: [source])
    config = pipeline.Config(output_dir=tmp_path, video=False)
    llm = FakeLLM()

    result = pipeline.run(episode, config, llm=llm, tts_engine=FakeTTS())
    assert result.outputs["digest.en"].exists()
    assert result.outputs["subtitles.en"].read_text().startswith("1\n00:00:00,000 --> ")
    assert result.meta["transcript_words"] == 600
    assert result.meta["durations_seconds"]["digest.en"] > 0
    assert len(llm.calls) == 2

    pipeline.run(episode, config, llm=llm, tts_engine=FakeTTS())
    assert source.calls == 1
    assert len(llm.calls) == 2

    config.max_minutes = 4
    pipeline.run(episode, config, llm=llm, tts_engine=FakeTTS())
    assert len(llm.calls) == 3
    assert "2-3 minutes" in llm.calls[-1] and "Never exceed 600 words" in llm.calls[-1]

    config.style = "professional"
    pipeline.run(episode, config, llm=llm, tts_engine=FakeTTS())
    assert len(llm.calls) == 4


def test_chinese_outputs_social_cards_and_video(tmp_path, monkeypatch, episode):
    monkeypatch.setattr(pipeline, "build_transcript_sources", lambda config: [FakeSource()])
    config = pipeline.Config(output_dir=tmp_path, languages=["en", "zh"], style="hook")
    result = pipeline.run(episode, config, llm=FakeLLM(), tts_engine=FakeTTS())
    out = result.outputs

    assert out["notes.zh"].read_text().startswith("## 一句话总结")
    assert "中文脚本" in out["script.zh"].read_text()
    assert "冷水澡" in out["subtitles.zh"].read_text()
    xhs = out["post.xhs.zh"].read_text()
    assert xhs.startswith("# 冷热交替真的有用吗🧊") and "#健康 #代谢" in xhs
    assert "video.zh.mp4" in out["post.bilibili.zh"].read_text()
    assert [p.name for p in sorted(out["cards.zh"].glob("*.png"))] == ["00_cover.png", "01_card.png", "02_card.png"]
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "json",
         str(out["video.zh"])],
        check=True, capture_output=True, text=True,
    )
    streams = json.loads(probe.stdout)["streams"]
    assert {s["codec_type"] for s in streams} == {"video", "audio"}
    assert any(s.get("width") == 1920 and s.get("height") == 1080 for s in streams)
    assert "post.en.json" not in {p.name for p in result.workdir.iterdir()}


class BrokenSource:
    name = "broken"

    def fetch(self, episode, workdir):
        raise RuntimeError("boom")


def test_failing_source_falls_through_to_next(tmp_path, monkeypatch, episode):
    good = FakeSource()
    monkeypatch.setattr(pipeline, "build_transcript_sources", lambda config: [BrokenSource(), good])
    config = pipeline.Config(output_dir=tmp_path, video=False)
    result = pipeline.run(episode, config, llm=FakeLLM(), tts_engine=FakeTTS())
    assert good.calls == 1
    assert result.meta["transcript_source"] == "fake"


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        pipeline.Config(style="clickbait")
    with pytest.raises(ValueError):
        pipeline.Config(languages=["xx"])


def test_split_text_respects_limit():
    text = " ".join(f"Sentence number {i}." for i in range(400))
    chunks = tts.split_text(text, max_chars=200)
    assert all(len(c) <= 200 for c in chunks)
    assert " ".join(chunks) == text


class LongThenShortLLM:
    name = "long-then-short"

    def __init__(self):
        self.calls = []

    def complete(self, system, user):
        self.calls.append(user)
        return "word " * 900 if len(self.calls) == 1 else "word " * 400


def test_script_over_cap_is_shortened_but_short_one_is_kept():
    from podcast_digest import summarize

    episode = Episode(podcast_title="Show", title="Ep", audio_url="https://example.com/a.mp3")
    llm = LongThenShortLLM()
    script = summarize.write_script(llm, episode, "notes")
    assert len(script.split()) == 400
    assert len(llm.calls) == 2 and "This draft is 900 words; the hard limit is 750 words" in llm.calls[1]

    class ShortLLM:
        name = "short"
        calls = []

        def complete(self, system, user):
            self.calls.append(user)
            return "word " * 120

    short = ShortLLM()
    assert len(summarize.write_script(short, episode, "notes").split()) == 120
    assert len(short.calls) == 1
