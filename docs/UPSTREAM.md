# Prior art — survey, 21 Sep 2026

Searched GitHub for work worth adopting into this pipeline. The honest result: unlike the
real-time streaming space, **lecture-note generation has no strong upstream project**. What
exists is mostly small and unmaintained — the best matches found were between 1 and 22 stars.
The useful finds are components, not competitors.

## Worth adopting

**[`m-bain/whisperX`](https://github.com/m-bain/whisperX)** · 24,151★ — word-level timestamps
via forced alignment, plus **speaker diarization**.

Two things this pipeline cannot currently do:

1. **Tell the lecturer from a student.** Notes today flatten every voice into one stream, so a
   half-heard question and the answer to it read identically. Diarization separates them, and
   "a student asked X" is exactly the sort of line that turns out to matter at revision time.
2. **Align notes to slides precisely.** Word-level timestamps would let a note point at the
   slide that was on screen when a sentence was said, rather than at a five-minute chunk.

It is batch, not streaming, which suits this pipeline — transcription already happens after
the fact, in chunks.

**Wired up as `scripts/diarize.py`, but NOT verified end to end.** whisperX pulls torch and
pyannote (multiple GB) and its diarization models are gated on Hugging Face, so the first real
run is the test. The script is deliberately separate from `transcribe.sh` and fails with
setup instructions rather than a traceback, so the main pipeline keeps working on a machine
where none of it is installed.

## Considered and declined — MLX Whisper

Looked promising: an Apple-Silicon-native Whisper, on a machine that is an M1.

It resolves to **torch 2.14 plus mlx, mlx-metal, numba, scipy and llvmlite** — about 2 GB.
So it is not the light alternative to whisper.cpp that it first appears to be; it carries the
same dependency weight as whisperX, for a speedup rather than a capability.

Against that: whisper.cpp already runs on Metal here, and this pipeline is **not
latency-bound**. Lectures are transcribed after the fact, in chunks, while nobody is waiting.
A faster batch transcriber buys very little, and 2 GB of dependencies is a real cost on a
tool whose selling point is that it runs locally with `brew install whisper-cpp`.

**Not benchmarked.** The install was abandoned partway rather than pull 2 GB to measure a
speedup that would not change the recommendation. Worth revisiting only if transcription ever
becomes the slow step — it currently is not.

## Built, not adopted

**Anki export — done, `scripts/make-anki.py`.** The survey turned up a dozen AI-to-Anki
generators, none above 30 stars and none worth a dependency. The idea fits, so it is built
here instead: a synthesis already contains a concept index and a ranked list of likely exam
questions, which are exactly two card decks waiting to be emitted.

Output is TSV rather than `.apkg` — inspectable in an editor, diffable in git, and
re-importable over the same deck without duplicating cards. Zero dependencies.

Across the six live courses it produces **299 cards** (215 concept, 84 exam).

One bug found while testing it, worth recording because it was silent: the notes number exam
questions two ways, `**1. Question**` and `1. **Question**`, and the first parser knew only
the first form. Five of six courses produced **zero** exam cards and reported success, which
is indistinguishable from a synthesis that simply has no questions in it. Both forms now
parse, and a test covers each.

## Not adopted

| Repo | ★ | Why not |
|---|---|---|
| `ggml-org/whisper.cpp` | 53,809 | already the engine here |
| `SYSTRAN/faster-whisper` | 25,483 | CTranslate2 backend; a speed option, not a capability |
| `QuentinFuxa/WhisperLiveKit` | 11,073 | excellent, but built for streaming — this pipeline is batch |
| `pyannote/pyannote-audio` | 10,573 | diarization building blocks; whisperX wraps them with alignment |
| assorted lecture-note generators | 1–22 | smaller in scope than what is already here |

## The fix that came out of this survey

`digest.py` accepted whatever the API returned. A reasoning model can spend its whole token
budget on hidden reasoning and return `content: ""`, and the caller appended nothing, printed
`ok`, and wrote a digest with the middle missing — which is how two SYNTHESIS.md files were
silently gutted.

`call()` now raises on an empty reply, on a whitespace-only reply, and on `finish_reason:
"length"` (a part cut off mid-sentence), so a bad run fails loudly and leaves the previous
digest intact. The default model moved off `openai/gpt-oss-120b` to `qwen/qwen3.8-27b`, which
answers directly instead of reasoning. Six tests in `tests/test_digest_reply_guard.py` cover
it; all six fail against the previous code.
