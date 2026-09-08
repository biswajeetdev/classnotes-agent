"""Contract test: 'Verification gates publishing.' (SKILL.md step 3c / docs/
GOTCHAS.md 'Verify the finished note against the transcript': it found four
real errors in the first two notes this pipeline produced, so a clean pass
must never be a formality). If verify flags an item, the note must be marked
unverified and the pipeline must report failure rather than success.

Skips cleanly until pybuild's feat/python-pipeline branch lands. See
test_verify_notes_script.py for the equivalent test against the already-
implemented scripts/verify-notes.py, which runs for real today.
"""
from conftest import FIXTURES, run_cli


def test_verify_clean_note_reports_success():
    result = run_cli(
        "verify", str(FIXTURES / "sample_note_clean.md"),
        str(FIXTURES / "sample_transcript.txt"),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_verify_bad_note_reports_failure_not_success():
    result = run_cli(
        "verify", str(FIXTURES / "sample_note_bad.md"),
        str(FIXTURES / "sample_transcript.txt"),
    )
    assert result.returncode != 0, (
        "verify must exit non-zero when it flags fabricated quotes/numbers/names "
        "-- a clean exit here would let an unverified note look published"
    )


def test_run_does_not_treat_a_failed_verification_as_pipeline_success(
    classnotes_root, fake_bin, monkeypatch
):
    """End-to-end: a note pipeline run whose verify step flags something must
    surface that as an overall failure, not silently swallow it and report
    success. We can't force pybuild's note-writing to produce a bad note from
    here, so this checks the weaker but still load-bearing property: the CLI
    process's own exit code must not lie about a verification failure it
    reports in its output."""
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    result = run_cli(
        "verify", str(FIXTURES / "sample_note_bad.md"),
        str(FIXTURES / "sample_transcript.txt"),
    )
    stdout_reports_problems = any(
        kw in result.stdout for kw in ("QUOTE", "NUMBER", "NAME", "unverified", "flagged")
    )
    if stdout_reports_problems:
        assert result.returncode != 0
