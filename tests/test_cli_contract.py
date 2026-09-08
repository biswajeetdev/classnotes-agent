"""Contract tests: the classnotes/ package must expose the published CLI
surface. Skips cleanly until pybuild's feat/python-pipeline branch lands.

    python3 -m classnotes run <course-slug> [<input.mp4>|--date YYYY-MM-DD]
    python3 -m classnotes note <course-slug> <date>
    python3 -m classnotes synthesis <course-slug>
    python3 -m classnotes verify <note.md> <transcript.txt>
    python3 -m classnotes status

All five commands accept --dry-run (as of pybuild's commit 5f5b854): verify
and status are read-only by nature, so their --dry-run is an accepted no-op
for CLI-shape uniformity rather than an omission -- see tests/README.md.

`status` is now safe to exercise via the CLI too: pybuild's same commit
fixed scripts_bridge.term_coverage() to set CLASSNOTES_ROOT explicitly for
the term-coverage.py subprocess (it used to only set `cwd=`, which that
script never read, so `status` silently always read the real
~/class-notes/courses.yaml regardless of root override -- see
tests/README.md's now-resolved findings).
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
    result = run_cli(
        "verify", str(FIXTURES / "sample_note_clean.md"),
        str(FIXTURES / "sample_transcript.txt"),
    )
    assert "Traceback" not in result.stderr


def test_verify_supports_dry_run_flag():
    """verify --dry-run must be accepted (not 'unrecognized arguments') and
    must skip actually running verify-notes.py -- passing a note that would
    normally fail verification must not surface that failure under
    --dry-run, since nothing was checked."""
    result = run_cli(
        "verify", str(FIXTURES / "sample_note_bad.md"),
        str(FIXTURES / "sample_transcript.txt"), "--dry-run",
    )
    assert "unrecognized arguments" not in result.stderr
    assert "Traceback" not in result.stderr
    assert result.returncode == 0
    assert "dry-run" in result.stdout.lower()


def test_status_reads_the_configured_root_not_real_data(classnotes_root, monkeypatch):
    """The root-cause regression test for the finding pybuild just fixed:
    status must report on the fixture course under CLASSNOTES_ROOT, and must
    never fall back to (or additionally report on) the real
    ~/class-notes/courses.yaml."""
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    result = run_cli("status")
    assert "Traceback" not in result.stderr
    assert "intro-statistics" in result.stdout
    assert "microeconomics" in result.stdout


def test_status_supports_dry_run_flag(classnotes_root, monkeypatch):
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    result = run_cli("status", "--dry-run")
    assert "unrecognized arguments" not in result.stderr
    assert "Traceback" not in result.stderr
    assert result.returncode == 0
    assert "dry-run" in result.stdout.lower()
