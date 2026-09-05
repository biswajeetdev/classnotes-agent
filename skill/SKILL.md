---
name: classnotes
description: Turn a recorded class (Microsoft Teams .mp4, or any audio/video) into structured lecture notes and a rolling per-course exam-prep synthesis. Handles code-switched Hindi + English lectures. Use when the user says /classnotes, "take notes on this class", "process today's lecture", "add this class", or points at a lecture recording. Also use for exam-prep questions like "what's likely on the exam for <course>", "what did I miss", or "quiz me on <course>".
---

# Class Notes

Turns a recorded lecture into notes that are actually usable in November.

The point is **not** transcription. The point is that after every class, the
per-course `SYNTHESIS.md` gets rebuilt so exam prep is a file you open, not a
term's worth of reading you have to redo.

Context: designed for an online postgraduate programme — several courses running in
parallel, classes on Microsoft Teams, recordings downloadable from Teams/SharePoint.
Lectures are code-switched **Hindi + English**; adjust the Hinglish rules below for
your own language pair.

## Layout

```
~/class-notes/
  scripts/transcribe.sh
  models/ggml-large-v3-turbo.bin
  courses.yaml                      # course slugs, names, professors, exam dates
  <course-slug>/
    raw/YYYY-MM-DD-lecture.mp4      # the Teams download, kept
    transcripts/YYYY-MM-DD.txt      # kept — lets a bad pass be redone
    lectures/YYYY-MM-DD-<topic>.md
    SYNTHESIS.md                    # rewritten every run
    QUESTIONS.md                    # accumulates across the term
```

## Running it

### 0. Capturing a live class (audio + slides in one command)

If the class is happening now, capture it live instead of waiting for the Teams
recording. One launcher runs both streams and cleans up after itself:

```bash
~/class-notes/scripts/class-start.sh <course-slug>     # start; leave it running
~/class-notes/scripts/class-start.sh stop <course-slug> # or Ctrl-C, or let it auto-stop
```

It records the professor's **audio** via BlackHole (`live-notes.sh`) and the shared
**screen** as deduped slide frames (`capture-slides.sh`) together. Audio is the master:
when it auto-stops after ~15 min of silence, slides stop and your speaker output is
restored automatically. Requires the one-time **Multi-Output Device** (see the header
of `class-start.sh`) and Screen Recording permission for the terminal. When it finishes,
the transcript and `slides/<date>/` are in place — carry on from step 1.

### 1. Work out the course and date

`courses.yaml` is the source of truth for slugs. Read it first.

- Course given explicitly (`/classnotes marketing lecture.mp4`) → use it.
- Not given → infer from the filename, then **confirm with the user before
  writing**. Never guess a course silently; a note filed under the wrong course
  corrupts that course's synthesis.
- Date → from the filename if it carries one, else the file's mtime, else ask.
  Teams names downloads like `Meeting in _General_-20260825_183000-Meeting Recording.mp4`.

### 2. Transcribe

```bash
~/class-notes/scripts/transcribe.sh <input> ~/class-notes/<course>/transcripts/<YYYY-MM-DD> [lang]
```

Skip this if a `transcripts/<date>.txt` already exists — reuse it. Re-running a
90-minute lecture costs many minutes for nothing.

Language argument: **leave it at `auto`.** But know the failure mode below.

#### whisper locks onto ONE language per file

Measured on turbo, 22 Aug 2026, on two code-switched samples:

| sample | `auto` | `hi` | `en` |
|---|---|---|---|
| majority **English** + Hindi | all kept, Hindi romanised | all kept, Devanagari | all kept |
| majority **Hindi** + English | **English sentence DROPPED** | **English sentence DROPPED** | all kept, but Hindi **translated** + a hallucinated line |

Whisper commits to the dominant language and **silently drops sustained speech
in the other** — no error, no gap marker in the output. Forcing the other
direction (`-l en` on Hindi-dominant audio) doesn't drop but *translates*, which
is just as lossy and adds hallucination.

What survives fine: **English technical terms embedded mid-Hindi-sentence.** Those
come out correctly in Latin (`Cross Validation`, `Fold`, `Overfitting`). Ordinary
code-switching is not the problem. **Sustained stretches in the minority language
are** — student Q&A in English during a Hindi lecture is the realistic case.

#### So: always check coverage

`transcribe.sh` runs this automatically and prints `!!` lines if speech went
untranscribed. **Never skip it and never ignore a `!!`** — a dropped exam signal
is exactly the failure this tool exists to prevent.

**Calibration caveat.** The detector picks its silence threshold per file
(10 dB under the file's mean level) and was verified on synthetic audio, clean
and with pink noise added — not yet on a real Teams recording. On your **first
real lecture, count the `!!` lines**:

- 0–2 flagged gaps → working; check them.
- Many flagged gaps → almost certainly false alarms from room tone, not real
  loss. Raise `min_gap` (3rd arg to `check-coverage.py`, default 3.0s) before you
  start ignoring the warnings. Alarm fatigue here defeats the whole guard.

To recover a flagged gap:

```bash
ffmpeg -nostdin -y -i <input> -ss <start> -to <end> gap.wav
~/class-notes/scripts/transcribe.sh gap.wav ./gap en
```

Then splice the recovered text into the transcript at the right position, marked
`[recovered: en pass]`, and note it under Transcription notes in the lecture note.

Never reach for translation (`-tr`) at any point.

Expect roughly **5x realtime** on turbo at full threads — a 90-minute lecture takes
~18 min. (An earlier 2.5x figure was measured on a 27-second clip and was dominated
by model-load overhead; on realistic lengths it is twice as fast.) Roughly halve that
when transcription is overlapped with a capture on restricted threads.

**Never pass `-bs 1`.** Measured 22 Aug: whisper-cli exits `rc=0` in under a second
and writes **no transcript at all**. It looks like a 400x speedup and is total silent
failure.

Whisper also garbles technical terms at any setting — "bias-variance tradeoff"
came out "bias variance study of", "into k folds" as "in 2k folds". Reconstruct
from context and record what you reconstructed under Transcription notes so it
can be checked against slides.

A Teams `.vtt`/`.docx` transcript, if the user has one, is a **cross-check only** —
use it to resolve names, acronyms and numbers Whisper garbled. Never use it as
the primary source; Teams handles Hinglish badly.

### 1b. Read LESSONS.md first — this is what makes later notes better

Before writing anything, read `<course>/LESSONS.md` if it exists. It carries what
previous sessions taught you about **this specific professor**: which words the ASR
reliably garbles, which phrases signal an exam question, how the class is structured,
and any factual slips he has made before.

Notes get better across a term only if each session writes back what it learned. So
**after** writing the note, update `LESSONS.md` with anything that would have helped you
an hour ago. Keep it short — corrections and patterns, not a diary.

```markdown
# Lessons — <course code>

## ASR corrections (recurring)
| heard | actually |
|---|---|
| pitney voice / whitney goes | Pitney Bowes |

## How this professor signals an exam question
- "according to the syllabus ... that's why we need to read it"

## Class format
- Harvard case method; student teams present

## Known factual slips — do not repeat in an exam
- attributed "Attention Is All You Need" to Mustafa Suleyman (he is not an author)
```

### 2a. Prefer the professor's own slides

Two possible slide sources, and they are not equal:

1. **`slides/*.pdf` or `*.pptx` — uploaded by the professor to Moodle.** Always prefer
   these. Real text, nothing clipped, and they include slides he clicked past too fast
   to read aloud. Fetch with `scripts/fetch-slides.sh <course-slug>`.
2. **`slides/<date>/slide-*.jpg` — screen frames captured during class.** A fallback.
   Only exists if slide capture ran, and many sessions are audio-only.

### 2b. Read the slides, if there are any

If `slides/<date>/` exists, **`Read` every `slide-*.jpg` before writing the note.**
They are already deduplicated — each one is a distinct board state, kept at its most
complete point (the dedup keeps the *last* frame of each run, so a slide that built up
bullet by bullet appears finished, not half-empty).

This matters because the transcript and the slides carry different things. A professor
says "as you can see here" and writes the formula on the board — the formula exists
only in the frame. Anything you take from a slide rather than the audio, mark
`[from slide N]` so it can be checked later.

If a slide contradicts the transcript, trust the slide for notation and the transcript
for emphasis.

### 2c. Digest long transcripts with Groq first

A 10,000-word transcript is expensive to read in full, and *finding* what was said is
the mechanical half of the work. Offload that; keep the judgement.

```bash
python3 ~/class-notes/scripts/digest.py <transcript.txt>   # -> <transcript>-digest.md
```

Then write the note from the digest, reading **targeted spans of the raw transcript**
for anything you need verbatim — exact quotes, formulas, assignment wording.

- Worth it above roughly 4,000 words. Below that, just read the transcript.
- Free tier is **8,000 tokens/minute**, so it paces itself: ~35 s between chunks,
  about 3 minutes for a 90-minute lecture. Run it and do something else.
- Needs `GROQ_API_KEY` in `~/class-notes/.env`.
- **The digest is lossy and is never the source of truth.** Verified 22 Aug: it passed
  a full fact-check against the transcript, but that is a property to re-check, not to
  assume. Step 3c always verifies the finished note against the FULL transcript.

**Always run the signal extract alongside it — the digest alone is not safe for ⚡:**

```bash
python3 ~/class-notes/scripts/extract-signals.py <transcript.txt>
```

Measured 22 Aug: the Groq digest invented nothing, but it **dropped the two highest
value lines of the lecture** — the "according to the syllabus" exam signal and "we can
change the model, but we can't change the data". A summariser optimises for topic
coverage and has no notion that one sentence outweighs a paragraph. Exam signals are
exactly that sentence.

`extract-signals.py` does not summarise. It greps for assessment language, superlatives,
absolutes and repeated lines, and returns the professor's words untouched. Deterministic,
free, and it cannot lose what it matches. **Build the ⚡ section from this, not the
digest.**

### 3. Write the lecture note

`~/class-notes/<course>/lectures/YYYY-MM-DD-<topic-slug>.md`

Read the full transcript before writing. Structure, never a transcript dump —
if a line of the note could be deleted without losing an idea, delete it.

```markdown
# <Topic> — <Course name>
**Date:** YYYY-MM-DD · **Professor:** <name> · **Source:** transcripts/YYYY-MM-DD.txt

## In one line
<what this lecture was actually about>

## Key concepts
### <Concept>
<Plain-English definition. Hindi term inline in Devanagari with a gloss the
first time the professor uses one — see Hinglish rules below.>

## Formulas / frameworks
<Written out properly, with what each symbol means and when it applies. Take these
from the slides where they exist — spoken formulas garble badly. Mark `[from slide N]`.>

## Worked examples
<The examples the professor actually walked through, with the numbers.>

## ⚡ Exam signals
- <Anything repeated, slowed down for, written on the board, or flagged
  outright: "this is important", "yeh exam mein aayega". Quote the professor
  where the phrasing carries the emphasis.>

## Open questions
- <Asked and not answered, or genuinely unclear from the audio.>

## Admin
<Deadlines, assignments, next-class announcements. Omit the heading if none.>

## Transcription notes
<Any term you reconstructed from a garbled transcript, and any gap the coverage
check flagged and how it was recovered. Omit the heading if the transcript was
clean. This is what lets you re-check a doubtful note against the slides.>
```

Rules:
- **⚡ Exam signals is the highest-value section.** It drives the synthesis
  ranking later. Be generous but honest — a flag means the professor gave a real
  signal, not that the topic seemed important to you.
- No speaker diarization is available. Never attribute a line to a named
  student. Q&A goes in as a block: "A student asked … the professor answered …".
- If the audio is unclear, write `[unclear: <your best guess>]` rather than
  inventing content. A wrong note found in November is worse than a gap.
- Append every open question to `QUESTIONS.md` with its date and lecture link.

### 3b. Pull out assignments — they are time-critical

Append any assignment, submission, quiz or deadline to `ASSIGNMENTS.md`. Do this even
when the professor mentions it only in passing; a missed deadline is the most
expensive thing this tool can drop.

```markdown
## <Title> — <course code>
**Given:** YYYY-MM-DD · **Due:** <date, or "not stated">
**Weight:** <if mentioned>

<What is actually required, in the professor's own terms. Quote him where the wording
matters — "make a one page" is a constraint you cannot recover later.>

**Submission:** <where/how, if stated>
**Status:** not started
```

If no due date was given, write **"not stated — ask"** rather than guessing. Sort the
file soonest-deadline first. This is published as its own PDF, so it must stand alone
without the lecture note around it.

### 3c. Verify the note against the transcript — required

```bash
python3 ~/class-notes/scripts/verify-notes.py <lecture.md> <transcript.txt>
```

It checks every **figure, direct quote and proper noun** in the note against what was
actually said, and prints anything it cannot ground. **Fix or remove every flagged
item before publishing.** A fabricated figure found in November is worse than a gap.

Rules when it flags something:
- **A quote that does not match** — replace it with what was actually said, or drop the
  quotation marks. Never present a paraphrase as a quote.
- **A name the transcript never contains** — it is a reconstruction. Either declare it
  under Transcription notes or remove it.
- **A number with no source** — delete it. Do not "remember" figures.

Run it again after fixing until it passes clean. It found four real errors in the first
two notes this pipeline produced, so do not treat a clean pass as a formality.

### 4. Rebuild the synthesis — never skip this

`~/class-notes/<course>/SYNTHESIS.md`, **regenerated from every lecture note in
the course**, on every run. Read them all. Do not append to the old file; write
a new one.

This is the deliverable. Appending gives you 100 files and no study material.

```markdown
# <Course name> — Exam Synthesis
*Rebuilt YYYY-MM-DD · <n> lectures · exam <date from courses.yaml>*

## Concept index
<Every concept across the term, one line each, grouped by theme rather than by
date. Link to the lecture that covers it best.>

## How it fits together
<Cross-lecture connections. "Week 6's costing model is the same idea as week
3's X applied to Y." This is the part that cannot be got from any single note,
and the reason the file is rebuilt rather than appended.>

## Likely exam questions
<Ranked by ⚡ density across lectures. For each: the question, and which
lectures you would answer it from.>

## Revised or contradicted
<Where the professor corrected or refined something said earlier. Flag both
versions — this is a classic exam trap.>

## Thin ice
<Concepts mentioned once and never revisited, and anything still sitting
unanswered in QUESTIONS.md. This is the revision to-do list.>
```

### 5. Report back

Tell the user, briefly: course, date, topic, how many exam signals were caught,
anything unclear in the audio, and any new admin/deadline picked up. Then stop.

## Hinglish rules

Notes are written in **English**. The transcript is code-switched; the notes are
not.

- A Hindi term the professor chose deliberately stays, inline in Devanagari,
  glossed on first appearance: *लागत* (cost). Thereafter use it freely.
- Hindi used as ordinary connective speech ("toh phir yeh hota hai ki…") is not
  preserved — it carries no content. Write the idea in English.
- Quote the professor verbatim where the phrasing itself is the emphasis, e.g.
  "yeh definitely exam mein aayega" — then flag it under ⚡.
- **Never translate a technical term away.** If the professor says *ब्याज दर*
  where the textbook says "interest rate", keep both.
- Whisper may romanise or Devanagari-ise inconsistently across a file. Normalise
  in the notes; leave the transcript untouched.

## Other things this skill answers

- **"What's likely on the exam for X?"** → read that course's `SYNTHESIS.md`,
  answer from it. Don't re-read every lecture unless the synthesis is stale.
- **"Quiz me on X."** → generate questions from the synthesis, hardest-flagged
  first, and mark answers against the lecture notes.
- **"What did I miss?"** → `QUESTIONS.md` plus the Thin ice section.
- **A lecture note was bad** → rebuild it from the kept transcript. That is why
  transcripts are kept; you never need the recording twice.

## Constraints

- Files stay under 500 lines. If `SYNTHESIS.md` outgrows that, split the concept
  index into `SYNTHESIS-concepts.md` and link it.
- Never delete anything under `raw/` or `transcripts/`.
- Never write outside `~/class-notes/`.
