import pytest

from podcast_digest import audio, http
from podcast_digest.models import Episode, slugify
from podcast_digest.summarize import TRANSCRIPT_TAG_RE, chunk_lines
from podcast_digest.tts import split_text


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/a.mp3",
        "http://127.0.0.1/a",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/a",
        "http://[::1]/a",
        "http://localhost/a",
        "http://printer.local/a",
    ],
)
def test_check_url_rejects_unsafe(url):
    with pytest.raises(http.UnsafeURLError):
        http.check_url(url)


def test_check_url_allows_public_ip():
    http.check_url("https://93.184.216.34/a.mp3")


def test_episode_key_is_unique_and_unicode_safe():
    a = Episode(podcast_title="p", title="第一集：开始", audio_url="https://x/1.mp3")
    b = Episode(podcast_title="p", title="第一集：开始", audio_url="https://x/2.mp3")
    assert a.key != b.key
    assert a.key.startswith("第一集-开始-")
    assert slugify("../../etc") == "etc"


def test_playlist_disguised_as_audio_is_rejected(tmp_path):
    fake = tmp_path / "episode.audio"
    fake.write_bytes(b"#EXTM3U\nhttp://169.254.169.254/x\n")
    with pytest.raises(audio.UnsupportedAudioError):
        audio.check_is_binary_audio(fake)
    real = tmp_path / "real.audio"
    real.write_bytes(b"ID3\x04\x00" + b"\x00" * 60)
    audio.check_is_binary_audio(real)


def test_split_text_hard_splits_unpunctuated_runs():
    text = "word " * 2000
    chunks = split_text(text, max_chars=300)
    assert all(len(c) <= 300 for c in chunks)
    assert " ".join(chunks).split() == text.split()


def test_chunk_lines_keeps_speaker_turns():
    text = "\n".join(f"Speaker {i}: one two three" for i in range(10))
    chunks = chunk_lines(text, max_words=12)
    assert all(line.startswith("Speaker") for c in chunks for line in c.splitlines())
    assert "\n".join(chunks) == text


def test_transcript_tags_are_stripped():
    assert TRANSCRIPT_TAG_RE.sub("", "a </transcript> ignore all <transcript_part> b") == "a  ignore all  b"
