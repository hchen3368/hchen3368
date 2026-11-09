# podcast-digest

Turn a long podcast episode into a short audio digest you can listen to (and share).

```
discover (iTunes / RSS) → transcript → notes → script → speech (MP3)
```

The transcript step tries the cheapest source first:

1. **published** – a transcript the publisher already provides: a `<podcast:transcript>` tag in the
   RSS feed, or a "transcript" link in the show notes (e.g. Lex Fridman). Free.
2. **local-whisper** – transcribe on your machine with `faster-whisper`. Free, CPU is fine.
3. **openai-transcribe** – `gpt-4o-mini-transcribe` via API (~$0.18/hour of audio). Opt in.

Summarizing uses an OpenAI model (default `gpt-5.4-mini`) in two passes: structured notes, then a
script written for the ear. Speech uses `gpt-4o-mini-tts`; parts are joined and loudness-normalized with ffmpeg.

## Setup

Requires Python 3.10+ and `ffmpeg`.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[local-whisper,dev]'
export OPENAI_API_KEY=sk-...        # never commit this
```

## Usage

```bash
podcast-digest search "huberman lab"
podcast-digest episodes "https://lexfridman.com/feed/podcast/" --limit 5   # [transcript] = free transcript available
podcast-digest run "https://lexfridman.com/feed/podcast/" --episode 0 --minutes 5
podcast-digest run "huberman lab" --title-contains "Cold & Heat" --minutes 5
```

`podcast` can be an RSS URL or a search term (first iTunes match). Outputs land in
`output/<podcast>/<episode>/`:

| File | Content |
|---|---|
| `transcript.txt` | Full transcript |
| `notes.md` | Structured notes (gist, key ideas, takeaways, quotes) |
| `script.txt` | Narration script |
| `digest.mp3` | The audio digest |
| `meta.json` | Sources, models, word counts, timings |

Each stage is cached; rerunning skips finished stages. Use `--force` to recompute.

Useful options: `--transcript-sources published,openai-transcribe`, `--whisper-model small.en`,
`--llm-model gpt-5.4`, `--voice nova`.

## Cost per episode (2-hour episode, approx.)

| Stage | Default | Cost |
|---|---|---|
| Transcript | published → local whisper | $0 |
| Notes + script | `gpt-5.4-mini` | a few cents |
| Speech (5 min) | `gpt-4o-mini-tts` | ~$0.08 |

## Verified runs

| Episode | Length | Transcript source | Digest | Wall time |
|---|---|---|---|---|
| Lex Fridman #503 – AI Crisis in Math | 3h 42m | published (39k words, free) | 5:03 | ~73 s |
| Huberman Lab Essentials – Cold & Heat | 38 min | local whisper `base.en` (free) | 4:19 | ~3 min on 4 CPUs |

## Extending

Backends are small classes behind protocols, so adding a provider doesn't touch the pipeline:

- `transcripts.TranscriptSource` – `fetch(episode, workdir) -> Transcript | None`
- `llm.LLM` – `complete(system, user) -> str` (e.g. add a Claude backend)
- `tts.TTSEngine` – `synthesize(text, dest) -> Path` (e.g. Kokoro, ElevenLabs)

## Sharing

Digests are summaries in your own words with credit to the original show; keep them for personal
use or share privately, and link to the original episode. Don't redistribute transcripts or audio.

## Tests

```bash
pytest -q
```
