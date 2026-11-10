import pytest

from podcast_digest import tts
from podcast_digest.languages import LANGUAGES


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, json, headers, timeout):
        self.calls.append((url, json, headers))
        return FakeResponse(self.payload)


def test_minimax_decodes_hex_audio_and_sends_expected_body(tmp_path, monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    session = FakeSession({"data": {"audio": b"ID3fake".hex()}, "base_resp": {"status_code": 0}})
    engine = tts.MiniMaxTTS("speech-2.8-hd", "voice-x", "zh", session=session)
    out = engine.synthesize("你好。", tmp_path / "a.mp3")
    assert out.read_bytes() == b"ID3fake"
    url, body, headers = session.calls[0]
    assert url == "https://api.minimax.io/v1/t2a_v2"
    assert body["voice_setting"]["voice_id"] == "voice-x"
    assert body["language_boost"] == "Chinese" and body["audio_setting"]["format"] == "mp3"
    assert headers["Authorization"] == "Bearer proxy-injected"


def test_minimax_raises_on_api_error(tmp_path):
    session = FakeSession({"base_resp": {"status_code": 1004, "status_msg": "auth failed"}})
    with pytest.raises(RuntimeError, match="1004"):
        tts.MiniMaxTTS(voice="v", session=session).synthesize("x", tmp_path / "a.mp3")


def test_build_engine_defaults_and_overrides():
    zh = LANGUAGES["zh"]
    assert tts.build_engine("openai", zh).name == f"openai:{tts.DEFAULT_TTS_MODEL}:marin"
    assert tts.build_engine("minimax", zh, voice="v1").name == "minimax:speech-2.8-hd:v1"
    with pytest.raises(ValueError):
        tts.build_engine("nope", zh)
