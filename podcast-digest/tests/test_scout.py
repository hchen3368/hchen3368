import json
from datetime import datetime, timezone

import pytest

from podcast_digest import pipeline, scout
from podcast_digest.models import Episode

NOW = datetime(2026, 11, 21, tzinfo=timezone.utc)


def _episode(title, published="Thu, 19 Nov 2026 10:00:00 GMT", transcript=True):
    return Episode("Pod", title, f"https://a/{title}.mp3", guid=title, published=published,
                   duration_seconds=5400, description_html=f"<p>{title} talk</p>",
                   transcript_urls=(("https://a/t.vtt", "text/vtt"),) if transcript else ())


class ScoutLLM:
    name = "fake"

    def __init__(self, indexes):
        self.indexes, self.prompts = indexes, []

    def complete_json(self, system, user, name, schema):
        self.prompts.append(user)
        return {"candidates": [
            {"index": i, "title": f"标题{i}？", "question": "问题？", "question_en": "Q?", "viewer_value": "收获",
             "viewpoints": ["甲", "乙"], "category": "科技", "score": 8, "estimated_minutes": 5}
            for i in self.indexes
        ]}


def test_recent_episodes_skip_old_and_seen(monkeypatch):
    episodes = [_episode("new"), _episode("old", "Mon, 01 Jun 2026 10:00:00 GMT"), _episode("seen")]
    monkeypatch.setattr(scout.discovery, "list_episodes", lambda feed, limit: episodes)
    found = scout.recent_episodes([scout.Source("Pod", "https://f")], 14, 6, NOW, {episodes[2].key})
    assert [e.title for _, e in found] == ["new"]


def test_scout_writes_report_and_history_and_drops_bad_picks(monkeypatch, tmp_path):
    episodes = [_episode("a"), _episode("b", transcript=False)]
    monkeypatch.setattr(scout.discovery, "list_episodes", lambda feed, limit: episodes)
    llm = ScoutLLM([1, 1, 7, 0])
    report, picked = scout.scout(llm, [scout.Source("Pod", "https://f", ("科技",))], tmp_path, 5, now=NOW)
    assert [c["episode"] for c in picked] == ["b", "a"]
    assert picked[0]["transcript"] == "whisper"
    assert "标题1？" in report.read_text() and "需语音转写" in report.read_text()
    history = json.loads((tmp_path / "history.json").read_text())
    assert {h["episode_key"] for h in history} == {e.key for e in episodes}
    with pytest.raises(LookupError):
        scout.scout(llm, [scout.Source("Pod", "https://f")], tmp_path, 5, now=NOW)


def test_topic_needs_question_and_gets_its_own_workdir(tmp_path):
    with pytest.raises(ValueError):
        pipeline.Config(script_format="topic")
    with pytest.raises(ValueError):
        pipeline.Config(question="为什么？")
    episode = _episode("a")
    a = pipeline.Config(output_dir=tmp_path, script_format="topic", question="甲？")
    b = pipeline.Config(output_dir=tmp_path, script_format="topic", question="乙？")
    base = pipeline.episode_workdir(a, episode)
    assert pipeline.topic_workdir(a, episode).parent == base.parent
    assert pipeline.topic_workdir(a, episode) != pipeline.topic_workdir(b, episode)


def test_produced_keys_include_topic_videos(tmp_path):
    (tmp_path / "pod" / "ep-1234").mkdir(parents=True)
    (tmp_path / "pod" / "ep-5678--abcd1234").mkdir()
    assert scout.produced_keys(tmp_path, tmp_path / "missing") == {"ep-1234", "ep-5678"}
