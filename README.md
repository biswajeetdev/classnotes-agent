# classnotes-agent

Turn a recorded lecture into notes you can actually revise from in November.

Built for online postgraduate programmes taught over Microsoft Teams, where lectures are
long, code-switched between languages, and the recording is the only record. Runs locally
on macOS with [whisper.cpp](https://github.com/ggerganov/whisper.cpp). Designed to be
driven by [Claude Code](https://claude.com/claude-code) as a skill, but every script here
works standalone.

**The point is not transcription.** A transcript of a 90-minute lecture is 10,000 words
you will never re-read. The point is that after every class, a per-course `SYNTHESIS.md`
is rebuilt from *all* lectures so far — so exam prep is a file you open, not a term's
worth of reading you have to redo.

---

## Why this exists

Whisper on a real lecture fails in ways that are silent and specific. This repo is mostly
the accumulated defences against those failures.

| Failure | What it looks like | Defence here |
|---|---|---|
| **Hallucination on silence** | The professor pauses for questions; the transcript gains 32 copies of *"Any doubt in this notebook?"* that nobody said | VAD on by default (`--vad`). Measured: 36 fabrications → **0** |
| **Language lock** | Whisper commits to one language and **silently drops** sustained speech in the other. No error, no gap marker | `check-coverage.py` compares speech regions against the transcript timeline and flags what was never transcribed |
| **Confident wrong notes** | The model writes a plausible figure or quote the professor never said | `verify-notes.py` checks every figure, quote and proper noun in the finished note against the transcript |
| **Notes that pile up** | 40 lecture files, no study material | `SYNTHESIS.md` is **rebuilt from scratch** every run, never appended |
| **Missed classes** | You don't notice a lecture was never recorded until the exam | `term-coverage.py` reports which scheduled sessions have no transcript |

The VAD numbers above are from one real 5-minute lecture chunk: 36 fabricated lines → 0,
real words 466 → **515** (it recovered speech the non-VAD pass lost), a mis-transcribed
technical term corrected, and runtime 35s → 27s. Strictly better on every axis.

---

## What you get

```
$CLASSNOTES_ROOT/
  courses.yaml                      # your timetable — the single source of truth
  <course-slug>/
    raw/YYYY-MM-DD-lecture.mp4      # the recording, kept
    transcripts/YYYY-MM-DD.txt      # kept, so a bad note can be rebuilt without it
    lectures/YYYY-MM-DD-<topic>.md  # one structured note per class
    slides/<date>/                  # deduplicated slide frames, if captured
    SYNTHESIS.md                    # REBUILT every run — the deliverable
    QUESTIONS.md                    # accumulates unanswered questions
    ASSIGNMENTS.md                  # deadlines, so none is missed
    LESSONS.md                      # what this professor's ASR garbles, how he signals an exam
```

`LESSONS.md` is the part that compounds. Each run writes back what it learned about *this
specific professor* — which words the ASR reliably mangles, which phrases signal an exam
question, which factual slips he has made. The next run reads it first, so notes get
better across a term instead of repeating the same mistakes.

---

## Install

Requires macOS. Homebrew packages:

```bash
brew install whisper-cpp ffmpeg switchaudio-osx
brew install --cask blackhole-2ch      # only for live capture
```

Then:

```bash
git clone https://github.com/<you>/classnotes-agent.git
cd classnotes-agent

export CLASSNOTES_ROOT="$HOME/class-notes"     # add to your shell profile
mkdir -p "$CLASSNOTES_ROOT"/{scripts,models}
cp scripts/* "$CLASSNOTES_ROOT/scripts/"
cp courses.example.yaml "$CLASSNOTES_ROOT/courses.yaml"   # then edit it

# transcription model (~1.6 GB) and the VAD model (~900 KB)
curl -L -o "$CLASSNOTES_ROOT/models/ggml-large-v3-turbo.bin" \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin
curl -L -o "$CLASSNOTES_ROOT/models/ggml-silero-v5.1.2.bin" \
  https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin
```

Optional, for the Groq digest pass on very long transcripts:

```bash
cp .env.example "$CLASSNOTES_ROOT/.env"
chmod 600 "$CLASSNOTES_ROOT/.env"      # then paste your key
```

To use it as a Claude Code skill, copy `skill/SKILL.md` to
`~/.claude/skills/classnotes/SKILL.md` and invoke it with `/classnotes`.

---

## Use

**Transcribe a downloaded recording:**

```bash
scripts/transcribe.sh lecture.mp4 "$CLASSNOTES_ROOT/<course>/transcripts/2026-09-05"
```

**Capture a class live** (audio via BlackHole, plus slides as deduplicated frames):

```bash
scripts/class-start.sh <course-slug>            # start; leave it running
scripts/class-start.sh stop <course-slug>       # stop (or let it auto-stop on silence)
scripts/check-audio.sh                          # is the recorder actually hearing anything?
```

One-time setup for live capture: a **Multi-Output Device** so audio reaches both your
speakers and BlackHole. `scripts/make-multiout.py` builds it for you — no Audio MIDI
Setup required.

**Then write the notes.** Open Claude Code in `$CLASSNOTES_ROOT` and run `/classnotes`.
It reads `LESSONS.md`, transcribes if needed, checks coverage, writes the lecture note,
verifies it against the transcript, and rebuilds `SYNTHESIS.md`.

**Ask about the course:**

```
/classnotes what's likely on the exam for <course>
/classnotes quiz me on <course>
/classnotes what did I miss
```

---

## Two ways to run this

The steps above are driven by an agent (Claude Code, via `/classnotes`) that does the
judgement work — ranking exam signals, handling code-switched Hindi/English, deciding
what a note can lose without losing an idea. That's still the default.

There's also a **pure-Python mode**: one command, no agent session, the same
transcription and safety checks, with Groq's free tier standing in for the language
work an agent would otherwise do.

```bash
python3 -m classnotes run <course-slug> lecture.mp4
```

It's the faster path for a routine lecture. It is not a like-for-like substitute for
the judgement above — see [`docs/PYTHON-PIPELINE.md`](docs/PYTHON-PIPELINE.md) for
what it does, and where it's honestly weaker than having an agent in the loop.

## Script reference

| Script | Does |
|---|---|
| `transcribe.sh` | mp4/m4a → transcript, with VAD and a coverage check |
| `live-notes.sh` | live capture in 5-min chunks, transcribed as it goes; stops itself on sustained silence |
| `class-start.sh` | wrapper running audio + slide capture together, tearing both down cleanly |
| `class-watch.sh` | optional launchd watcher that starts captures from your timetable |
| `check-audio.sh` | 4-second probe: is audio actually reaching the recorder right now? |
| `check-coverage.py` | flags speech the transcript has nothing for |
| `verify-notes.py` | checks every figure, quote and name in a note against the transcript |
| `extract-signals.py` | greps for assessment language and repetition — deterministic, never invents |
| `digest.py` | optional Groq pass to summarise very long transcripts |
| `term-coverage.py` | which scheduled sessions have no transcript |
| `capture-slides.sh` / `dedup-frames.py` | screen frames, deduplicated to distinct board states |
| `fetch-slides.sh` | opens Moodle in your existing Chrome session; files what you download |
| `gen-calendar.py` | generates an `.ics` from `courses.yaml` |
| `make-multiout.py` | creates the Multi-Output audio device via CoreAudio |
| `md2pdf.py` / `publish-notes.sh` | notes → PDFs in a readable folder tree |

---

## Things that will bite you

Learned the hard way; all documented in [`docs/GOTCHAS.md`](docs/GOTCHAS.md).

- **Never pass `-bs 1` to whisper-cli.** It exits `0` in under a second and writes no
  transcript at all. Looks like a 400× speedup; is total silent failure.
- **Back-to-back classes defeat the silence auto-stop.** The room never goes quiet, so one
  lecture records straight into the next course. Stop the earlier capture manually.
- **Switching audio output mid-class kills the recording.** AirPods bypass the
  Multi-Output device, so the recorder goes deaf while the class continues.
  `live-notes.sh` now detects this and warns instead of concluding the class ended.
- **launchd runs with a minimal `PATH`** that excludes Homebrew, so a scheduled capture
  dies on "whisper-cli missing" while the log says it started.
- **Slide capture needs Screen Recording permission.** Without it ffmpeg runs happily and
  writes zero frames — indistinguishable from a working capture until you look.

---

## Privacy

Everything runs locally. Audio and transcripts never leave your machine unless you opt
into the Groq digest pass (`digest.py`), which sends transcript text to Groq's API.

**This repo contains the tool only.** The `.gitignore` is deny-by-default at the
repository root, so your notes, recordings, transcripts, timetable and `.env` cannot be
committed by accident.

Recording a class may require your institution's or lecturer's consent. That is your call
to make, not this tool's.

---

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The most useful
contributions are **measured** failure modes: if whisper drops or invents something on
your audio, a reproduction with numbers is worth more than a fix.

## License

MIT — see [LICENSE](LICENSE).
