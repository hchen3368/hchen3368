import json

from podcast_digest import transcripts
from podcast_digest.discovery import TRANSCRIPT_LINK_RE, parse_duration


def test_html_speaker_segments_preferred():
    html = """<html><body><nav>menu</nav>
    <div class="ts-segment"><span class="ts-name">Host</span> <span class="ts-timestamp">(00:00:01)</span>
    <span class="ts-text">Welcome   to the show.</span></div>
    <div class="ts-segment"><span class="ts-name">Guest</span> <span class="ts-text">Thanks.</span></div>
    </body></html>"""
    assert transcripts.html_to_text(html) == "Host (00:00:01) Welcome to the show.\nGuest Thanks."


def test_html_falls_back_to_article_paragraphs():
    html = "<html><body><header><p>nav</p></header><article><p>One.</p><p></p><p>Two.</p></article></body></html>"
    assert transcripts.html_to_text(html) == "One.\nTwo."


def test_vtt_cues_are_stripped_and_deduplicated():
    vtt = "WEBVTT\n\n1\n00:00:00.000 --> 00:00:02.000\n<v Host>Hello there\n\n2\n00:00:02.000 --> 00:00:04.000\nHello there\nGeneral Kenobi\n"
    assert transcripts.parse_transcript(vtt, "text/vtt") == "Hello there\nGeneral Kenobi"


def test_podcast_namespace_json():
    raw = json.dumps({"segments": [{"speaker": "A", "body": "Hi"}, {"body": "  "}, {"body": "Bye"}]})
    assert transcripts.parse_transcript(raw, "application/json") == "A: Hi\nBye"


def test_transcript_link_found_in_show_notes():
    html = '<p>Links: <a href="https://example.com/ep-1-transcript">Transcript</a></p>'
    assert TRANSCRIPT_LINK_RE.search(html).group(1) == "https://example.com/ep-1-transcript"


def test_parse_duration_formats():
    assert parse_duration("3:42:40") == 13360
    assert parse_duration("2316") == 2316
    assert parse_duration("01:08:19") == 4099
    assert parse_duration("bad") is None
    assert parse_duration(None) is None
