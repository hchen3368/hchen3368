import subprocess
from pathlib import Path

from podcast_digest import pipeline, tts
from podcast_digest.models import Episode, Transcript


class FakeLLM:
    name = "fake"

    def __init__(self):
        self.calls = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append(user)
        return "## One-line gist\nNotes." if len(self.calls) == 1 else "This is the script. It has two sentences."


class FakeTTS:
    name = "fake-tts"

    def synthesize(self, text: str, dest: Path) -> Path:
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


def test_pipeline_end_to_end_and_caches(tmp_path, monkeypatch):
    source = FakeSource()
    monkeypatch.setattr(pipeline, "build_transcript_sources", lambda config: [source])
    episode = Episode(podcast_title="Show", title="Ep 1: Hello", audio_url="https://example.com/a.mp3")
    config = pipeline.Config(output_dir=tmp_path)
    llm = FakeLLM()

    result = pipeline.run(episode, config, llm=llm, tts_engine=FakeTTS())
    assert result.digest_audio.exists()
    assert result.meta["transcript_words"] == 600
    assert result.meta["digest_seconds"] > 0
    assert len(llm.calls) == 2

    pipeline.run(episode, config, llm=llm, tts_engine=FakeTTS())
    assert source.calls == 1
    assert len(llm.calls) == 2


def test_split_text_respects_limit():
    text = " ".join(f"Sentence number {i}." for i in range(400))
    chunks = tts.split_text(text, max_chars=200)
    assert all(len(c) <= 200 for c in chunks)
    assert " ".join(chunks) == text
