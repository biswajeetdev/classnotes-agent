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

## Contract tests (skip cleanly if the `classnotes` package is absent)

These target the CLI contract. They were written before the package existed and
guard it now that it has landed; they still skip rather than fail if `classnotes`
cannot be imported, so the suite stays meaningful when run from a checkout where
the package is not installed:

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

All five commands accept `--dry-run` as of pybuild's commit `5f5b854`:
`verify` and `status` are read-only by nature, so theirs is an accepted
no-op ("dry-run: would verify ...") for CLI-shape uniformity, added after
this suite initially (wrongly) flagged `verify` lacking it as a contract
violation -- see the findings below for the full back-and-forth.

| File | Defends |
|---|---|
| `test_cli_contract.py` | All five subcommands exist and run without a traceback; `--dry-run` is accepted by all five (a real skip for the three writing commands, an accepted no-op for `verify`/`status`); `status` reports on the configured root, not real user data. |
| `test_whisper_safety.py` | Never `-bs 1` (silent total failure: rc=0, no transcript). Never `-tr`/`--translate`. Language defaults to `auto`. |
| `test_transcript_reuse.py` | An existing `transcripts/<date>.txt` is reused, never re-transcribed or overwritten. |
| `test_density_guard.py` | Re-passed-chunk word count vs. capture-log word count: match proceeds, mismatch flags loudly and blocks writing a note (measured case: 451 vs 451 cleared a false alarm on 2026-09-06). |
| `test_coverage_routing.py` | `check-coverage.py` (or its consolidated equivalent) is never hit with a `.txt` path where an `.srt` is required. |
| `test_synthesis_rebuild.py` | `SYNTHESIS.md` is fully rewritten, never appended -- old unique content must not survive a rebuild. |
| `test_verification_gate.py` | A verify failure must surface as pipeline failure, never be swallowed into a success report. |
| `test_root_safety.py` | Never writes outside the configured root; never deletes anything under `raw/` or `transcripts/`. |
| `test_silent_chunk_gaps.py` | A numbering gap from deleted silent chunks (below ~-45 dB) is explained, not reported as loss/corruption. |
| `test_course_resolution.py` | Slug, alias, and unresolvable-course handling -- never silently guesses; an ambiguous alias must not resolve to either match. |
| `test_cancellations_contract.py` | Pipeline-level version of gotcha 11 -- a cancelled session is never silently captured by `run`, and `status --all` reports it as cancelled rather than a missing session ("a report that cries wolf is a report nobody reads"). |

## Running

```bash
cd tests
python3 -m venv .venv && .venv/bin/pip install pytest pyyaml
.venv/bin/python -m pytest
```

(`.venv/` is local and gitignored -- see the repo `.gitignore`.)

## Still not covered

`test_silent_chunk_gaps.py` tries a short list of plausible internal
module/function names for the chunk-numbering-gap explainer (gotcha 9). It isn't
part of the published CLI surface and no such module exists yet, so this test
skips -- deliberately, rather than passing vacuously. When that module is added,
either it will already match one of the guesses, or the candidate list at the top
of that file needs one line added; the assertions underneath don't need to change.

`test_density_guard.py` originally guessed at a `classnotes.density`
function this way too, but partway through writing this suite pybuild's
in-progress package became visible from this session (a shared-sandbox cwd
landed inside `~/classnotes-agent`, their separate worktree, while both of
us were working -- not something to rely on happening again). That let this
file be rewritten against the real `density.check(live_dir, lang) ->
DensityResult` API instead of guessing, so it's now a real, precise unit
test rather than a name-guessing one.

## Findings for pybuild (all resolved)

Reading the real (in-progress) package while writing these tests turned up
three things, all now fixed on `feat/python-pipeline`:

1. **`status` didn't honour `CLASSNOTES_ROOT`.** `cmd_status` shelled out to
   `scripts/term-coverage.py` via `scripts_bridge.term_coverage(root, args)`,
   setting only the subprocess's `cwd` -- but `term-coverage.py`'s `ROOT` was
   `os.path.expanduser("~/class-notes")`, hardcoded at import time, and never
   read `cwd`. So `python3 -m classnotes status` always read the *real*
   `~/class-notes/courses.yaml` regardless of `CLASSNOTES_ROOT`. **Fixed in
   commit `5f5b854`:** `term-coverage.py`'s `ROOT` now reads `CLASSNOTES_ROOT`
   directly, and `scripts_bridge.term_coverage()` sets that env var explicitly
   from the `root` it's given rather than relying on `cwd`.
   `test_cli_contract.py::test_status_reads_the_configured_root_not_real_data`
   and `test_cancellations_contract.py::test_status_reports_a_cancellation_not_a_gap`
   now exercise `status` via the CLI directly, safely, against
   `CLASSNOTES_ROOT`.

2. **`config.resolve_course()`'s alias match returned the first hit, not a
   unique one.** The slug-substring fallback explicitly required
   `len(substr) == 1` before returning (never guess silently), but the
   earlier alias/code-match loop just returned on the first course whose
   aliases contained the needle. **Fixed in commit `5f5b854`,** same pattern
   as the substring fallback: collect every alias/code match, raise
   `ConfigError` naming all of them if more than one, only auto-resolve if
   exactly one.
   `test_course_resolution.py::test_ambiguous_alias_does_not_silently_pick_one`
   now also checks the specific error message.

3. **`verify` had no `--dry-run`,** which an earlier version of this README
   flagged as contradicting "all commands support --dry-run." pybuild
   initially clarified this was intentional (verify/status are already
   non-mutating), then added it anyway as an accepted no-op for CLI-shape
   uniformity -- **commit `5f5b854`.** `test_cli_contract.py` now checks both
   the plain and `--dry-run` forms of `verify`.

**Also fixed along the way (commit `0043bf4`, before the above):**
`classnotes/density.py` had `~/class-notes/models/...` hardcoded as
module-level constants, ignoring `CLASSNOTES_ROOT` -- inconsistent with
every other module. Model paths now resolve from `config.default_root()` at call
time, with `WHISPER_MODEL`/`WHISPER_VAD_MODEL` still overriding explicitly.
`test_density_guard.py::test_model_path_resolves_under_classnotes_root_not_real_home`
covers this directly.
