# The Python pipeline

`scripts/` plus a Claude Code skill is the original way to run this tool: an agent
drives each stage and does the judgement work — deciding what's worth an exam-signal
flag, what to cut from a note, how a Hindi clause folds into an English sentence. That
mode is not going anywhere.

The Python pipeline (the `classnotes` package) is a second way to run the same
pipeline **with no agent in the loop**. One command, no Claude Code session, no
back-and-forth. The only thing that leaves your machine is transcript text sent to
Groq's free tier — everything else, including every safety check in
[GOTCHAS.md](GOTCHAS.md), is the same deterministic Python either way.

> **Status.** This document was first drafted against the command contract while the
> `classnotes` package was being built in parallel, then reconciled against the
> finished implementation. What follows describes shipped code.

---

## When to use it — and, honestly, when not to

Use it when you just need the note and the synthesis updated, and you'd rather not
spend an agent session babysitting seven steps. It's the right default for a routine
lecture in a course that's already producing good notes.

Don't reach for it when the judgement matters more than the transcription does:

- **Ranking exam signals.** `extract-signals.py`'s grep is deterministic and cannot be
  fooled into hallucinating — but it also can't tell a lecturer's serious "yeh exam
  mein aayega" from the fortieth restatement of something routine. An agent reading
  the transcript weighs that; Groq's digest pass, guided by the same prompt, only
  approximates it.
- **Code-switched Hindi/English.** The Hinglish rules in the skill — when a Devanagari
  term stays inline and glossed, when Hindi connective speech gets dropped as
  content-free — are exactly the kind of per-sentence call a general-purpose model in
  an agent session handles better than a single Groq completion built for speed on the
  free tier.
- **Deciding what to cut.** "If a line of the note could be deleted without losing an
  idea, delete it" is an editing judgement. Groq drafts to a template; nobody reads the
  draft and asks whether each line earns its place the way an agent does.

If a lecture is unusually dense, unusually garbled, or the one right before an exam,
run it through the agent-driven skill instead — or run the Python pipeline first and
have the agent review what it produced. **Say this plainly to yourself before you rely
on Groq output going straight into `SYNTHESIS.md` unread: it is a faster, cheaper
approximation of the judgement the agent mode does, not a replacement for it.**

---

## Setup

Same local dependencies as the agent-driven mode — whisper.cpp and ffmpeg do the same
work either way — plus a Python environment and a Groq key.

```bash
brew install whisper-cpp ffmpeg
whisper-cli --help | grep -- --vad     # confirm VAD support (whisper-cpp >= 1.9)
```

**Python.** 3.10 or newer, declared in `pyproject.toml`. There are **no third-party
runtime dependencies** — the package is stdlib-only and reaches Groq over `urllib`
rather than pulling in `requests`. `pip install -e ".[dev]"` adds pytest and ruff,
for development only.

**Models**, same as [SETUP.md](SETUP.md):

```bash
export CLASSNOTES_ROOT="$HOME/class-notes"
mkdir -p "$CLASSNOTES_ROOT/models"
curl -L -o "$CLASSNOTES_ROOT/models/ggml-large-v3-turbo.bin" \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin
curl -L -o "$CLASSNOTES_ROOT/models/ggml-silero-v5.1.2.bin" \
  https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin
```

**Groq key** — the one AI dependency in this mode:

```bash
cp .env.example "$CLASSNOTES_ROOT/.env"
chmod 600 "$CLASSNOTES_ROOT/.env"      # then paste GROQ_API_KEY=...
```

Get a free-tier key at <https://console.groq.com/keys>. The rate limit — 8,000
tokens/minute — is why the digest stage paces itself; see Limitations below.

**Your timetable**, same file as always:

```bash
cp courses.example.yaml "$CLASSNOTES_ROOT/courses.yaml"
```

Nothing about `courses.yaml`, `LESSONS.md`, or the directory layout under
`$CLASSNOTES_ROOT` changes between the two modes — they share the same on-disk
format, so a course you've been running through the agent skill works with the Python
pipeline on the next lecture with no migration.

---

## Commands

```bash
python3 -m classnotes run <course-slug> [<input.mp4>|--date YYYY-MM-DD]
python3 -m classnotes note <course-slug> <date>
python3 -m classnotes synthesis <course-slug>
python3 -m classnotes verify <note.md> <transcript.txt>
python3 -m classnotes status
```

- `run` is the end-to-end command: transcribe (if needed) through synthesis rebuild,
  for one lecture. Point it at a downloaded recording, or at `--date` if the transcript
  already exists and you just want the rest of the pipeline re-run.
- `note` and `synthesis` are the individual stages, for re-running just one of them —
  the same reason `SYNTHESIS.md` is safe to regenerate on its own: it's rebuilt from
  the kept lecture notes, never appended.
- `verify` is the standalone checker — the Python-pipeline equivalent of
  `scripts/verify-notes.py` — for re-checking a note you edited by hand.
- `status` reports term coverage per course: which scheduled sessions have a
  transcript and which do not, with a captured/held summary. It **wraps**
  `scripts/term-coverage.py` as a subprocess rather than reimplementing it, so the
  output is identical to running that script directly.

**`--dry-run`** is supported on `run`, `note` and `synthesis` — the three commands that
write. It prints what the command would do (which stages would run, which files would be
written or overwritten) without touching disk or calling Groq. Use it before your first
`run` on a new course, and any time you're unsure whether a step will re-transcribe
something expensive by mistake.

`verify` and `status` take no `--dry-run`, deliberately: neither writes anything, so
there is nothing for a dry run to skip.

---

## Pipeline stages

`run` walks through these in order. Each one is deterministic Python except where
marked; Groq is the only stage that leaves the machine.

1. **Transcribe.** Same whisper.cpp invocation as `scripts/transcribe.sh`: VAD on by
   default, language left at `auto`, never `-bs 1`, never `-tr`. If a transcript
   already exists for that date, this stage is skipped — transcripts are always kept
   and reused, never silently regenerated. See Safety rails below.

2. **Density check.** A cheap sanity pass that compares the transcript's word count
   against what's expected for the audio, to catch a transcription that silently
   truncated or produced far less than it should have — the same category of failure
   as `-bs 1`, just caught after the fact instead of by avoiding the flag. This is
   separate from `check-coverage.py`'s speech-region comparison, and deliberately so:
   `check-coverage.py` needs an `.srt` timeline and falsely reports 100% of speech
   missing when handed a `.txt`, so the density check never calls it. It works instead
   from the `.wav`/`.txt` chunk pairs `live-notes.sh` already keeps under
   `raw/<date>-live/`, picking the *densest* chunk (not a middle one, which can land on
   a silence break and pass meaninglessly), re-transcribing that one with the language
   forced, and comparing against its paired `.txt`. Both checks answer "did whisper
   actually get all of this," from different angles. On 2026-09-06, a re-passed chunk logging 451 words against an
   already-logged 451 correctly cleared what looked like a false alarm — the density
   check agreeing with itself is what avoided a multi-hour recovery pass on audio that
   had transcribed cleanly the first time.

3. **Digest (Groq).** The one network call in the pipeline. Condenses the raw
   transcript the same way `scripts/digest.py` does today: topics, key statements,
   emphasis, Q&A, admin — never inventing facts, never the source of truth. Used for
   navigating the transcript when writing the note, not for the note's content
   directly.

4. **Signal extraction (deterministic, not the LLM).** Runs the same grep-based pass
   as `scripts/extract-signals.py` — assessment language, superlatives, absolutes,
   repeated lines, returned in the professor's own words. This is what the digest
   cannot be trusted to do alone: see Safety rails.

5. **Note.** Assembles the structured lecture note — the same sections as the
   agent-driven skill (In one line, Key concepts, Formulas, Worked examples, ⚡ Exam
   signals, Open questions, Admin, Transcription notes) — from the digest plus the
   extracted signals. Groq drafts the prose sections (In one line, Key concepts,
   Formulas, Worked examples, Open questions, Admin). The ⚡ section is **not** drafted
   by Groq: it is assembled in Python from `extract-signals.py` plus the course's
   `LESSONS.md` phrase vocabulary, and every assembled line is then asserted present in
   Groq's output and force-appended verbatim if it was dropped. That makes "the
   summariser silently drops the highest-value line" structurally impossible rather
   than merely instructed against.

6. **Verify.** Runs the same checks as `scripts/verify-notes.py` — every figure, quote,
   and proper noun in the note against the full transcript, not the digest. Publishing
   is gated on this passing; see Safety rails.

7. **Synthesis rebuild.** `SYNTHESIS.md` is regenerated from every lecture note in the
   course, same as always — never appended to.

---

## A worked walkthrough

Using the example course from `courses.example.yaml` (`intro-statistics`), with a
recording already downloaded to `~/Downloads/lecture.mp4`:

```bash
export CLASSNOTES_ROOT="$HOME/class-notes"
python3 -m classnotes run intro-statistics ~/Downloads/lecture.mp4
```

What happens, in order:

1. The recording is transcribed to
   `$CLASSNOTES_ROOT/intro-statistics/transcripts/2026-09-08.txt`, with VAD on. If a
   transcript for that date already exists, this step is skipped and the existing file
   is used.
2. The density check runs against the new transcript. A clean pass moves on silently;
   a flagged discrepancy prints a warning and the pipeline pauses rather than building
   a note on top of a possibly-truncated transcript.
3. The transcript is sent to Groq in chunks, paced to the free-tier rate limit, and
   condensed into a digest — roughly 3 minutes for a 90-minute lecture.
4. `extract-signals.py`'s logic runs over the raw transcript directly (not the digest)
   for the ⚡ candidates.
5. A note is written to
   `$CLASSNOTES_ROOT/intro-statistics/lectures/2026-09-08-<topic-slug>.md`.
6. The note is verified against the full transcript. Anything unverifiable — an
   ungrounded quote, a number with no source — is either fixed automatically where the
   fix is unambiguous, or flagged for you [contract: exact automatic-fix vs.
   flag-only behaviour not yet confirmed].
7. `$CLASSNOTES_ROOT/intro-statistics/SYNTHESIS.md` is rebuilt from every note in
   `intro-statistics/lectures/`, including the new one.

To re-run just the parts that touch judgement, once the transcript already exists:

```bash
python3 -m classnotes note intro-statistics 2026-09-08
python3 -m classnotes synthesis intro-statistics
```

And to check a note you hand-edited afterward:

```bash
python3 -m classnotes verify \
  "$CLASSNOTES_ROOT/intro-statistics/lectures/2026-09-08-descriptive-stats.md" \
  "$CLASSNOTES_ROOT/intro-statistics/transcripts/2026-09-08.txt"
```

---

## The safety rails, and why each one exists

These are not new rules invented for this mode — they're the same defences documented
in [GOTCHAS.md](GOTCHAS.md), carried over because the failures they guard against are
properties of whisper and of LLM summarisation, not of having an agent in the loop.

- **Never `-bs 1`.** Measured: whisper-cli exits `rc=0` in under a second and writes no
  transcript at all. It looks like a 400× speedup and is total silent failure — there
  is no error to catch, only an empty output file to notice.
- **Never `-tr` (translation mode).** Whisper locks onto one language per file and
  silently drops sustained speech in the other, with no error or gap marker. Forcing
  the minority language doesn't fix this — it translates instead, which is just as
  lossy and adds hallucination on top. Measured on two code-switched samples: a
  majority-Hindi lecture lost a full English sentence under `auto`, and translating it
  back added a hallucinated line.
- **Transcripts are kept and reused, never regenerated.** A 90-minute lecture costs
  real minutes to transcribe; re-running it for nothing is the kind of waste that adds
  up across a term. It also means a bad note can be rebuilt without re-touching the
  recording.
- **The density check.** See stage 2 above — the 2026-09-06 case where a re-passed
  chunk's word count matched the logged count exactly (451 vs. 451) is the concrete
  example of what this check is for: telling a real problem apart from a check crying
  wolf, before you spend hours on a recovery pass the transcript didn't need.
- **Exam signals come from deterministic extraction plus `LESSONS.md`, never from the
  LLM digest.** Measured: the Groq digest invented nothing, but it dropped the two
  highest-value lines of a real lecture — an explicit "according to the syllabus" exam
  signal and the professor's one-sentence thesis. A summariser optimises for topic
  coverage; it has no notion that one sentence outweighs a paragraph. The ⚡ section is
  built from `extract-signals.py`'s grep, which cannot lose what it matches.
- **The digest is lossy and is never the source of truth.** It exists for navigating
  a long transcript quickly, not for content. Anything in the note that comes from the
  digest still has to survive the verify stage against the full transcript.
- **Verification gates publishing.** The same three rules as the agent-driven skill: a
  quote that doesn't match gets replaced with what was actually said or has its
  quotation marks dropped; a name the transcript never contains is either declared as a
  reconstruction or removed; a number with no source is deleted, not "remembered."
- **`SYNTHESIS.md` is rebuilt from every note, never appended.** Appending gives you a
  growing pile of files and no study material. Rebuilding from all of them is what lets
  it show how lectures connect and where something was later revised or contradicted —
  properties a single append pass can never produce.

---

## Limitations and known-broken

- **Slide capture needs macOS Screen Recording permission**, granted to whatever
  terminal or process runs it. Without it, ffmpeg runs cleanly, exits 0, and writes
  zero frames — indistinguishable from a working capture unless you count the files.
  This is a property of the capture scripts the pipeline calls, not something the
  Python mode changes.
- **Groq's free tier is 8,000 tokens/minute.** The digest stage paces itself against
  this rather than erroring — expect roughly 3 minutes of digesting for a 90-minute
  lecture's transcript. This is a fixed cost of the mode, not a bug; if you need it
  faster, that means a paid Groq tier, not a flag on this pipeline.
- **No agent judgement, by design.** Repeating the point from the top of this document
  because it's the limitation that matters most: this mode will not catch the things an
  agent reading the transcript would catch. Treat its output as a strong first draft on
  a routine lecture, not as unread-safe on a lecture that matters more than usual.

---

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `run` finishes fast, transcript is empty or tiny | `-bs 1` got passed somewhere in the chain, or the input had no usable audio | Check the transcript file exists and is non-empty before trusting a fast run; re-run without `-bs 1` |
| Density check flags a discrepancy | Genuine truncation, or two runs measuring slightly different spans | Compare against a fresh chunk re-pass before assuming data loss — see the 2026-09-06 case above |
| A sustained English (or Hindi) passage is just missing from the transcript | Whisper locked onto the other language for the whole file | Re-run that segment with the language forced and splice it in; never use `-tr` to "fix" this |
| Digest stage hangs or is very slow | Groq free-tier rate limiting (8,000 tokens/min) doing its job | Expected for long transcripts; let it finish rather than re-running |
| `note` produces a ⚡ section that looks thin | Extraction is deliberately conservative — it only matches known signal patterns | Check `extract-signals.py`'s raw output directly; a real signal phrased unusually won't be caught, and that's a case for the agent-driven mode instead |
| `verify` keeps flagging the same item after a fix | The note still doesn't match the transcript's actual wording, not a false positive | Reread the transcript at that point rather than rephrasing around the checker |
| Slide frames are missing or zero | Screen Recording permission not granted | Grant it in System Settings → Privacy & Security → Screen Recording, then re-run the capture, not just the note stage |
| `GROQ_API_KEY` errors that look like a bad key | Groq's Cloudflare layer rejecting a bare/default `User-Agent`, not the key itself (a known interaction, documented in `scripts/digest.py`) | Confirm the key is valid at console.groq.com before assuming it's wrong |

---

For the agent-driven mode this pipeline runs alongside, see the main
[README](../README.md) and [`skill/SKILL.md`](../skill/SKILL.md). For the measured
failures behind every rail above, see [GOTCHAS.md](GOTCHAS.md).
