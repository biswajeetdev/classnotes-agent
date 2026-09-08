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

**Confirmed directly with pybuild:** root override is the `CLASSNOTES_ROOT`
environment variable (affects both reads and writes -- `config.default_root()`).
A separate `--out-root` flag on `run`/`note`/`synthesis` redirects writes only
while still reading the real root; that's for testing generation quality
against real transcripts, not what this suite uses. `whisper-cli` is invoked
directly by name via `subprocess.run` in `classnotes/density.py`; full
transcription goes through `scripts_bridge.transcribe()`, which shells out to
`scripts/transcribe.sh` (one level removed -- that script calls
`ffmpeg`/`whisper-cli` itself). `fake_bin` in `conftest.py` stubs both paths
on `PATH`, which works for either.

`--dry-run` is confirmed to intentionally exist only on the three writing
commands (`run`/`note`/`synthesis`) -- `verify` and `status` are already
non-mutating and don't have it by design, not by omission. (An earlier
version of this README and `test_cli_contract.py` flagged `verify` lacking
`--dry-run` as a bug; that's retracted -- see the numbered findings below.)

| File | Defends |
|---|---|
| `test_cli_contract.py` | All five subcommands exist and run without a traceback; `--dry-run` on `run`/`note`/`synthesis` performs no writes; `verify` runs plainly with no flag needed. |
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

`test_silent_chunk_gaps.py` tries a short list of plausible internal
module/function names for the chunk-numbering-gap explainer (it isn't part
of the published CLI surface, and no such module exists in the package yet).
Once pybuild adds it, either it'll already match one of the guesses, or the
candidate list at the top of that file needs one line added -- the
assertions underneath don't need to change.

`test_density_guard.py` originally guessed at a `classnotes.density`
function this way too, but partway through writing this suite pybuild's
in-progress package became visible from this session (a shared-sandbox cwd
landed inside `~/classnotes-agent`, their separate worktree, while both of
us were working -- not something to rely on happening again). That let this
file be rewritten against the real `density.check(live_dir, lang) ->
DensityResult` API instead of guessing, so it's now a real, precise unit
test rather than a name-guessing one.

## Findings from writing these tests

Writing the suite against the real package surfaced three issues. **All three are
now fixed** -- this section is kept as a record of what the tests caught, not as an
open to-do list. Each has a regression test guarding it.

1. **`status` did not honour `CLASSNOTES_ROOT`.** `term-coverage.py` hardcoded
   `ROOT = os.path.expanduser("~/class-notes")` at import time, so
   `python3 -m classnotes status` read the *real* course tree no matter what
   `CLASSNOTES_ROOT` said. That made the command untestable without touching real
   user data, so this suite originally refused to invoke it via the CLI at all.
   Fixed in both places: `term-coverage.py` now reads the env var itself, and
   `scripts_bridge.term_coverage()` threads it through explicitly rather than
   relying on ambient inheritance.

2. **`config.resolve_course()` picked the first matching alias, not a unique one.**
   The slug-substring fallback already required exactly one match before returning
   -- never guess silently -- but the alias/code loop above it returned on the first
   hit, so two courses sharing an alias would silently resolve to whichever appeared
   first in `courses.yaml`. That is the failure mode SKILL.md warns about most
   sharply: a note filed under the wrong course corrupts that course's synthesis.
   Now requires uniqueness and raises `ConfigError` listing every match.
   Guarded by `test_course_resolution.py::test_ambiguous_alias_does_not_silently_pick_one`.

3. **`density.py` hardcoded the whisper model path** to `~/class-notes/models/...`,
   ignoring `CLASSNOTES_ROOT` like every other module honoured it. Found while
   answering a question about the sandbox mechanism, fixed and re-verified against
   real live-capture chunks (466 vs 466, unchanged result).

One test remains skipped by design: the chunk-numbering-gap explainer (gotcha 9)
has no module yet. It skips with a message naming the candidate import paths to try
once that lands, rather than passing vacuously.

