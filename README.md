# MotionForge

MotionForge turns a puzzle prompt into a finished, vertical YouTube Short: a
verified puzzle, a six-beat storyboard, dense 9:16 visuals, karaoke captions,
generated audio, deterministic judge rounds, packaging, analytics and a playable
MP4.

The pipeline is deterministic-first. Every stage has an offline fallback, so a
preview render always finishes even when the LLM quota or TTS endpoint is down.
LLM output is optional enrichment and never decides whether an answer is correct.

## Quick start

```powershell
# Python 3.12 venv (the repo's .venv is authoritative on this machine)
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium

.\.venv\Scripts\python.exe main.py create "number series puzzle, 35 seconds" --ratio 9:16 --quality preview
```

Outputs live in `runs/<run_id>/`:

| File | Meaning |
| --- | --- |
| `final.mp4` | Playable H.264 + AAC Short |
| `package.json` | Titles, description, hashtags, tags, pinned comment, thumbnails |
| `improvement_log.json` | Judge rounds, scores, changes, final gates |
| `verification.json` | Code-verifier record and generation attempts |
| `report.json` | Full run report, budget, scene checks, degraded reasons |
| `judge.json` | Final seven-dimension panel |
| `storyboard.json` | Timed beats, narration, component props |
| `scene_checks.json` | Per-scene DOM measurements and problems |
| `audio/audio.wav` | −14 LUFS master (voice + music + SFX) |
| `package/thumbnail_1080x1920.jpg` | Vertical thumbnail |
| `package/thumbnail_1280x720.jpg` | Horizontal thumbnail |

## Commands

```powershell
python main.py create "<prompt>" [--ratio 9:16] [--duration 35] [--quality preview|final]
python main.py series "Daily Logic" --topic "number series" --count 3
python main.py batch prompts.txt
python main.py resume <run_id>
python main.py analytics [--import metrics.json]
python main.py budget
python main.py feedback <run_id> "feedback text"
python main.py approve <run_id>
python main.py lessons
python main.py list
```

Useful flags on generation commands:

- `--offline` — no LLM or TTS network calls (music + SFX only).
- `--no-llm` — deterministic puzzle/hook/script generation.
- `--no-tts` — keep music and SFX, skip voiceover.
- `--preview` — legacy alias for `--quality preview`.
- `--music <file>` / `--voiceover <file>` — supply your own audio.
- `--max-rounds N` — cap the judge/improve loop for a run.

`--quality preview` renders the full 1080×1920 CSS layout at half device scale
(540×960, 15 fps). `--quality final` renders 1080×1920 at 30 fps.

## Pipeline

1. **Concept** — eight formats scored from the prompt, topic history and imported
   analytics; recent formats are penalised to avoid repetition.
2. **Verified puzzle** — number series, arithmetic, percentage, ratio,
   time-and-work, algebra, truth-and-lies, and river/bridge crossing. Each has a
   deterministic code verifier. Wrong and ambiguous answers are rejected; number
   series are regenerated up to five times. Unverified types require a blind
   second LLM solve.
3. **Hooks** — six variants scored locally, plus optional LLM variants; the loop
   ending reuses the curiosity gap with a new sequence.
4. **Storyboard** — six beats (HOOK, PATTERN, YOUR TURN, SOLUTION, ANSWER, LOOP)
   timed at ~2.5 words/second, ≤14-word sentences, ≤10 words of on-screen copy.
5. **Scenes** — 15 deterministic components and three original inline-SVG
   characters, built on a dark-navy/cyan/yellow/red mobile design system.
6. **Render checks** — Playwright samples five moments per scene, checks safe
   areas, typography, contrast, overflow, overlap, occupancy and blank frames,
   then repairs or rescues non-renderable scenes.
7. **Judge rounds** — seven deterministic scores (hook, clarity, correctness,
   pacing, visual, audio, retention). Gates: every score ≥7, hook ≥8,
   correctness =10. Up to five evidence-driven improvement rounds, keeping the
   best; stops after two rounds with less than +0.3 gain. An LLM judge is
   advisory only.
8. **Audio** — per-scene edge-tts voiceover fitted to the timeline, procedural
   music and SFX, speech-ducked music, loudness normalised to −14 LUFS. TTS is
   optional; the music bed keeps the video from being silent.
9. **Packaging** — five titles, description, 8–12 hashtags, tags, pinned comment,
   and both thumbnail sizes.
10. **Analytics** — every run updates concept averages; import real retention or
    completion as `{"run_id": {"retention": 0.62, "completion": 0.41}}` to replace
    the judge-score proxy.
11. **Budget** — daily and per-run request limits, cost cap, prompt cache,
    pre-stage estimates, live usage bar, Retry-After handling, 402 adaptation and
    a degraded-run flag.

## Configuration

`config.yaml` controls models, budget, quality, safe areas, typography,
occupancy, narration pacing, audio targets, judge gates, checks, memory and
series defaults. The API key is read from `D:\YT\AI_AGENT\.env`.

Free-tier behaviour is deliberate: paid models are tried only for high-value
steps, then the configured fallback and free model; a failed model is skipped for
the rest of the run. If quota runs out, the run continues with deterministic
templates and says so in `report.json`.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The suite covers every verifier (correct, wrong, ambiguous), the layout engine,
occupancy and plan-vs-render consistency, the judge gate, the budget manager,
all visual components, audio synthesis, packaging and thumbnail sizes.

## Honest limitations

- Judge scores are deterministic evaluations of measured frames, verified
  answers, timed narration and the actual audio master. They are not channel
  analytics and not a guarantee of views.
- Until real metrics are imported, `retention_proxy` is `judge overall / 10`.
- Karaoke word timing is estimated from narration pacing; word-level TTS
  boundaries are not currently stored.
- edge-tts requires network access. Without it the Short is music + SFX only,
  and the report marks the run degraded.
- The free OpenRouter tier is rate-limited. Check `python main.py budget` before
  a batch run.
