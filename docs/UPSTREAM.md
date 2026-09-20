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

**MLX Whisper** (Apple Silicon) — several small wrappers exist around it. On an M-series Mac
it is meaningfully faster than the current `whisper-cli` path for batch work. Worth measuring
before adopting; the current pipeline is not latency-bound, so this is a convenience, not a fix.

## Worth building, not adopting

**Anki export.** The survey turned up a dozen AI-to-Anki generators, none above 30 stars and
none worth a dependency. But the idea fits: this pipeline already produces quiz questions, a
Bloom blueprint and mock papers. Emitting those as an Anki deck or a plain CSV is a small
amount of code and turns one-off revision material into spaced repetition.

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
