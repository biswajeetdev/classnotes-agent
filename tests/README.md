# classnotes-agent test suite

Two kinds of tests live here. `conftest.py` explains the mechanics; this file
maps each test module to the gotcha or contract item it defends.

## Real tests (run today, not gated on the classnotes/ package)

These import the already-implemented scripts in `scripts/` directly (via
`import_script()` in conftest.py) or invoke them as subprocesses. They pass
or fail for real right now.

| File | Defends |
|---|---|
| `test_check_coverage_script.py` | Whisper's per-file language lock silently dropping speech (`check-coverage.py`'s gap detection); and documents the measured "handed a .txt instead of an .srt" false-alarm failure mode. |
| `test_verify_notes_script.py` | "Verify the finished note against the transcript" -- fabricated quotes/numbers/names must be flagged and the script must exit non-zero. |
| `test_extract_signals_script.py` | "A summariser will drop the single most important sentence" (deterministic extraction catches absolute/negated framing with no signal word) and "live-coding narration is not emphasis" (repetition detection surfaces it; discarding it is a human step). |
| `test_term_coverage_script.py` | Gotcha 11, cancellations parsing (whole-day / per-course / per-slot / `#` comments), against the real `load_cancellations()`; also the session-schedule half of gotcha 10 via `load_courses()`. |

## Contract tests (skip cleanly until pybuild's feat/python-pipeline lands)

These target the CLI contract given in the task:

```
python3 -m classnotes run <course-slug> [<input.mp4>|--date YYYY-MM-DD]
python3 -m classnotes note <course-slug> <date>
python3 -m classnotes synthesis <course-slug>
python3 -m classnotes verify <note.md> <transcript.txt>
python3 -m classnotes status
```

They call `require_classnotes()` (or `run_cli()`, which calls it internally)
and skip -- not fail -- when the `classnotes` package isn't importable yet.
Because tests/ and classnotes/ are being built in parallel on separate
branches, that's the expected state in this worktree today; the suite
becomes meaningful the moment the branches merge.

**Assumption flagged, not confirmed by pybuild at write time:** root override
via a `CLASSNOTES_ROOT` environment variable, and that whisper-cli/ffmpeg are
invoked as subprocess calls to binaries found on `PATH` (matching
`scripts/transcribe.sh`'s existing contract). If pybuild used a different
mechanism, update `run_cli()` / `fake_bin` in `conftest.py` -- the assertions
themselves shouldn't need to change.

| File | Defends |
|---|---|
| `test_cli_contract.py` | All five subcommands exist, run without a traceback, and `--dry-run` performs no writes. |
| `test_whisper_safety.py` | Never `-bs 1` (silent total failure: rc=0, no transcript). Never `-tr`/`--translate`. Language defaults to `auto`. |
| `test_transcript_reuse.py` | An existing `transcripts/<date>.txt` is reused, never re-transcribed or overwritten. |
| `test_density_guard.py` | Re-passed-chunk word count vs. capture-log word count: match proceeds, mismatch flags loudly and blocks writing a note (measured case: 451 vs 451 cleared a false alarm on 2026-09-06). |
| `test_coverage_routing.py` | `check-coverage.py` (or its consolidated equivalent) is never hit with a `.txt` path where an `.srt` is required. |
| `test_synthesis_rebuild.py` | `SYNTHESIS.md` is fully rewritten, never appended -- old unique content must not survive a rebuild. |
| `test_verification_gate.py` | A verify failure must surface as pipeline failure, never be swallowed into a success report. |
| `test_root_safety.py` | Never writes outside the configured root; never deletes anything under `raw/` or `transcripts/`. |
| `test_silent_chunk_gaps.py` | A numbering gap from deleted silent chunks (below ~-45 dB) is explained, not reported as loss/corruption. |
| `test_course_resolution.py` | Slug, alias, and unresolvable-course handling -- never silently guesses; an ambiguous alias must not resolve to either match. |
| `test_cancellations_contract.py` | Pipeline-level version of gotcha 11 -- a cancelled session is never silently captured and counted as normal. |

## Running

```bash
cd tests
python3 -m venv .venv && .venv/bin/pip install pytest pyyaml
.venv/bin/python -m pytest
```

(`.venv/` is local and gitignored -- see the repo `.gitignore`.)

## What's not testable yet without the implementation

A few contract items in `test_density_guard.py` and `test_silent_chunk_gaps.py`
try a short list of plausible internal module/function names (since those
aren't part of the published CLI surface) and skip with a clear message if
none match. Once pybuild names the real function, either it'll already match
one of the guesses, or the candidate list at the top of that file needs one
line added -- the assertions underneath don't need to change.
