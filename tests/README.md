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

## Findings for pybuild

Reading the real (in-progress) package while writing these tests turned up
two things still worth a look (a third, initially reported, turned out to
be intentional design -- see below), plus one pybuild already fixed:

1. **`status` doesn't honour `CLASSNOTES_ROOT`.** `cmd_status` shells out to
   `scripts/term-coverage.py` via `scripts_bridge.term_coverage(root, args)`,
   which sets the subprocess's `cwd` to `root` -- but `term-coverage.py`'s
   `ROOT` is `os.path.expanduser("~/class-notes")`, hardcoded at import time,
   and never reads `cwd`. So `python3 -m classnotes status` always reads the
   *real* `~/class-notes/courses.yaml` regardless of `CLASSNOTES_ROOT`. On
   this machine that file exists, so this suite deliberately never invokes
   `status` via the CLI (see `test_cli_contract.py`'s module docstring) --
   `test_term_coverage_script.py` covers the same parsing logic safely
   instead. Likely fix: either have `term-coverage.py` read `CLASSNOTES_ROOT`
   itself (matching `config.default_root()`), or have `scripts_bridge` pass
   `--root` (would need adding to term-coverage.py's argparse) instead of
   relying on `cwd`.

2. **`config.resolve_course()`'s alias match returns the first hit, not a
   unique one.** The slug-substring fallback explicitly requires
   `len(substr) == 1` before returning (never guess silently), but the
   earlier alias/code-match loop just returns on the first course whose
   aliases contain the needle -- two courses sharing an alias would silently
   resolve to whichever is listed first in `courses.yaml`, rather than
   failing the way an ambiguous substring does.
   `test_course_resolution.py::test_ambiguous_alias_does_not_silently_pick_one`
   fails on this today; the fix is likely making that loop collect all
   matches and require exactly one, same as the substring fallback below it.

**Retracted:** `verify` lacking `--dry-run` was initially flagged as
contradicting the "all commands support --dry-run" contract line. Confirmed
with pybuild: intentional -- `verify` and `status` are already non-mutating
and were never meant to have it. `test_cli_contract.py` now tests `verify`
runs plainly instead.

**Already fixed by pybuild:** `classnotes/density.py` had
`~/class-notes/models/...` hardcoded as module-level constants, ignoring
`CLASSNOTES_ROOT` -- inconsistent with every other module. Fixed in their
commit `0043bf4`; model paths now resolve from `config.default_root()` at
call time, with `WHISPER_MODEL`/`WHISPER_VAD_MODEL` still overriding
explicitly (which is what `test_density_guard.py` sets, so it's unaffected
either way).
