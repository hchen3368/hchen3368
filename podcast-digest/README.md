# podcast-digest

Turn a long podcast episode into a 3–5 minute audio digest you can listen to (and share).

```
discover (iTunes / RSS) → transcript → notes → script → speech (MP3)
                                        ↘ Chinese script → Mandarin MP3 + subtitles → Bilibili MP4
                                        ↘ Xiaohongshu post + image cards → publish to storage
```

The transcript step tries the cheapest source first:

1. **published** – a transcript the publisher already provides: a `<podcast:transcript>` tag in the
   RSS feed, or a "transcript" link in the show notes (e.g. Lex Fridman). Free.
2. **local-whisper** – transcribe on your machine with `faster-whisper`. Free, CPU is fine.
3. **openai-transcribe** – `gpt-4o-mini-transcribe` via API (~$0.18/hour of audio). Opt in.

Summarizing uses an OpenAI model (default `gpt-5.4-mini`) in two passes: structured notes, then a
script written for the ear. Speech uses `gpt-4o-mini-tts`; parts are joined and loudness-normalized with ffmpeg.

## Setup

Requires Python 3.10+, `ffmpeg` (with libass) and, for Chinese cards/subtitles, a CJK font
(`apt install fonts-noto-cjk`).

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[local-whisper,social,storage,dev]'
export OPENAI_API_KEY=sk-...        # never commit this
```

## Usage

```bash
podcast-digest search "huberman lab"
podcast-digest episodes "https://lexfridman.com/feed/podcast/" --limit 5   # [transcript] = free transcript available
podcast-digest run "https://lexfridman.com/feed/podcast/" --episode 0 --language en,zh --style professional
podcast-digest run "huberman lab" --title-contains "Cold & Heat" --language zh --style auto --publish
```

`podcast` can be an RSS URL or a search term (first iTunes match).

| Option | Effect |
|---|---|
| `--language zh,en` | Output languages (default `zh` only). Chinese gets a natural spoken script, Mandarin narration and subtitles. |
| `--style auto\|hook\|professional` | How the digest opens. `hook` starts with a question tied to the listener's life; `professional` stays formal; `auto` lets the model pick by topic (default). |
| `--brand-name`, `--brand-tagline` | Our channel's name and tagline (or `PD_BRAND_NAME` / `PD_BRAND_TAGLINE`). Every digest opens with "<tagline>这里是<name>。" and then "今天我们探讨的内容，来自《<original podcast>》…"; the original show is never presented as ours. Defaults are placeholders (长话短听 / 与最优秀的思想并肩。). |
| `--tts-provider openai\|minimax`, `--voice`, `--tts-model` | Speech provider; defaults to MiniMax for `zh` and OpenAI for `en`. MiniMax (international, `api.minimax.io`, key in `MINIMAX_API_KEY`): `speech-2.8-hd`, voice `Chinese (Mandarin)_Warm_Bestie`. OpenAI: `gpt-4o-mini-tts-2025-12-15`, voice `alloy` (en) / `marin` (zh). `podcast-digest voices --filter Mandarin` lists MiniMax voices. |
| `--no-social` | Skip the Xiaohongshu / Bilibili posts and image cards (generated for `zh`). |
| `--no-video` | Skip the MP4 (cover frame + narration + burned-in subtitles). |
| `--publish` | Upload the shareable outputs after the run (see Storage). |
| `--target-minutes` | Optional soft length target (e.g. `10` means roughly 8–12 minutes). It only guides what the script keeps; the script is never padded or trimmed afterwards. |
| `--max-minutes` | Hard cap on digest length (default 5). Scripts aim for 3–4.5 minutes (decided while writing the script) and are shortened only if they exceed the cap. |
| `--llm-model`, `--voice`, `--keep-audio`, `--force` | Models, voice, keep downloaded audio, recompute everything. |

Outputs land in `output/<podcast>/<episode>/`:

| File | Content |
|---|---|
| `transcript.txt` | Full transcript (never published) |
| `notes.md`, `notes.zh.md` | Structured notes (gist, key ideas, takeaways, quotes), English and translated |
| `script.<lang>.txt` | Narration script |
| `digest.<lang>.mp3` | The audio digest |
| `subtitles.<lang>.srt` | Subtitles timed to the narration |
| `video.<lang>.mp4` | 1920×1080 video for Bilibili: cover frame, narration, burned-in subtitles |
| `post.xhs.zh.md` + `cards_zh/*.png` | Xiaohongshu post: title, body, hashtags and 3:4 image cards in upload order |
| `post.bilibili.zh.md` | Bilibili title, description and tags |
| `meta.json`, `stamps.json` | Sources, models, timings; inputs that produced each cached output |

Each stage is cached and stamped with the inputs that produced it (model, voice, prompts, length,
style, language), so rerunning skips finished stages but recomputes any stage whose inputs changed.
`--force` recomputes everything. Downloaded episode audio is deleted once a transcript exists unless
you pass `--keep-audio`.

## Storage

`publish` uploads digests, notes, posts, cards, subtitles and videos — never transcripts or source
audio — and maintains a `manifest.json` per episode plus a top-level `index.json`.

```bash
podcast-digest publish output/huberman-lab/<episode-dir>
```

Configure with environment variables:

| Variable | Meaning |
|---|---|
| `PD_STORAGE` | `local` (default) or `s3` |
| `PD_LOCAL_ROOT` | Folder for `local` (default `published/`) |
| `PD_S3_BUCKET`, `PD_S3_PREFIX` | Bucket and optional key prefix |
| `PD_S3_ENDPOINT_URL` | Needed for non-AWS S3-compatible stores (R2, MinIO, GCS interop) |
| `PD_PUBLIC_BASE_URL` | Public URL prefix for shareable links in manifests |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Bucket credentials (standard AWS variables) |

**Cloudflare R2 (recommended: free egress, 10 GB free):**

1. Cloudflare dashboard → R2 → *Create bucket* (e.g. `podcast-digest`).
2. Bucket → Settings → *Public access*: enable the `r2.dev` URL (or connect a custom domain).
3. R2 → *Manage API tokens* → create a token with *Object Read & Write* on that bucket.
4. Set the variables:
   ```bash
   export PD_STORAGE=s3 PD_S3_BUCKET=podcast-digest
   export PD_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
   export PD_PUBLIC_BASE_URL=https://pub-<id>.r2.dev
   export AWS_ACCESS_KEY_ID=<token key id> AWS_SECRET_ACCESS_KEY=<token secret> AWS_DEFAULT_REGION=auto
   ```

AWS S3 works the same without `PD_S3_ENDPOINT_URL`. Keep credentials in your shell or CI secrets,
never in the repo.

Feed content is treated as untrusted: only public http(s) URLs are fetched (redirects re-checked),
downloads are size- and time-limited, ffmpeg is restricted to local files, and files that look like
playlists rather than audio are rejected.

Useful options: `--transcript-sources published,openai-transcribe`, `--whisper-model small.en`,
`--llm-model gpt-5.4`, `--voice nova`.

## Cost per episode (2-hour episode, approx.)

| Stage | Default | Cost |
|---|---|---|
| Transcript | published → local whisper | $0 |
| Notes + script | `gpt-5.4-mini` | a few cents |
| Speech (3–5 min) | `gpt-4o-mini-tts` | ~$0.06 |

## Verified runs

| Episode | Length | Transcript source | Style | Chinese digest |
|---|---|---|---|---|
| Lex Fridman #503 – AI Crisis in Math | 3h 42m | published (39k words, free) | professional | 2:09 |
| Huberman Lab Essentials – Cold & Heat | 38 min | local whisper `base.en` (free) | auto → hook | 1:45 |

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
