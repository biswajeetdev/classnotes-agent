"""Contract tests: the classnotes/ package must expose the published CLI
surface. Skips cleanly until pybuild's feat/python-pipeline branch lands.

    python3 -m classnotes run <course-slug> [<input.mp4>|--date YYYY-MM-DD]
    python3 -m classnotes note <course-slug> <date>
    python3 -m classnotes synthesis <course-slug>
    python3 -m classnotes verify <note.md> <transcript.txt>
    python3 -m classnotes status

All commands support --dry-run -- clarified by pybuild: this means the
writing commands (run/note/synthesis). verify and status are already
non-mutating, so they were never given the flag by design, not by omission
-- see tests/README.md.

NOTE on `status`: as implemented, `cmd_status` shells out to
scripts/term-coverage.py, whose ROOT is hardcoded to
os.path.expanduser("~/class-notes") at import time -- it does NOT honour
CLASSNOTES_ROOT (only the `cwd=` of the subprocess is set, which
term-coverage.py never reads). Invoking `status` from a test would read the
user's REAL ~/class-notes/courses.yaml, which this suite must never do. So
`status` is deliberately not exercised here via subprocess; see
test_term_coverage_script.py for real, safely-isolated tests of the same
parsing logic, and tests/README.md for the flag raised with pybuild.
"""
from conftest import FIXTURES, run_cli


def test_no_args_does_not_crash_with_a_traceback():
    result = run_cli()
    assert "Traceback" not in result.stderr


def test_unknown_command_fails_cleanly():
    result = run_cli("bogus-command-xyz")
    assert result.returncode != 0
    assert "Traceback" not in result.stderr


def test_run_supports_dry_run_flag(classnotes_root, monkeypatch):
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    mp4 = classnotes_root / "intro-statistics" / "raw" / "2026-09-01-lecture.mp4"
    mp4.write_bytes(b"fake")
    result = run_cli("run", "intro-statistics", str(mp4), "--date", "2026-09-01", "--dry-run")
    assert "Traceback" not in result.stderr
    # dry-run must not write a transcript
    assert not (classnotes_root / "intro-statistics" / "transcripts" / "2026-09-01.txt").exists()


def test_note_supports_dry_run_flag(classnotes_root, monkeypatch):
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    (classnotes_root / "intro-statistics" / "transcripts" / "2026-09-01.txt").write_text(
        "a transcript that already exists\n"
    )
    result = run_cli("note", "intro-statistics", "2026-09-01", "--dry-run")
    assert "Traceback" not in result.stderr
    assert not list((classnotes_root / "intro-statistics" / "lectures").glob("*.md"))


def test_synthesis_supports_dry_run_flag(classnotes_root, monkeypatch):
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    lectures = classnotes_root / "intro-statistics" / "lectures"
    lectures.mkdir(parents=True, exist_ok=True)
    (lectures / "2026-09-01-cross-validation.md").write_text(
        (FIXTURES / "sample_note_clean.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    result = run_cli("synthesis", "intro-statistics", "--dry-run")
    assert "Traceback" not in result.stderr


def test_verify_runs_without_dry_run():
    """verify is read-only by nature and intentionally has no --dry-run flag
    (confirmed with pybuild -- see tests/README.md). It should just work
    plainly, with no flag needed."""
    result = run_cli(
        "verify", str(FIXTURES / "sample_note_clean.md"),
        str(FIXTURES / "sample_transcript.txt"),
    )
    assert "Traceback" not in result.stderr
