"""Contract test: the classnotes/ package's own cancellations.yaml awareness
must never silently capture and count a cancelled session as a normal one --
whether that's the `run` pipeline transcribing on a cancelled date, or
`status`'s term-coverage report.

See test_term_coverage_script.py for real, safely-isolated tests of the
underlying parsing logic (already implemented in scripts/term-coverage.py),
which is not gated on this. Skips cleanly until pybuild's
feat/python-pipeline branch lands.

`status` used to be untestable here safely -- cmd_status ignored
CLASSNOTES_ROOT and always read the real ~/class-notes/courses.yaml (see
tests/README.md's now-resolved findings). Fixed in pybuild's commit
5f5b854, so it's exercised directly below now.
"""
from conftest import run_cli


def test_cancelled_session_is_not_silently_captured(classnotes_root, fake_bin, monkeypatch):
    """2026-09-02 is cancelled whole-day in the fixture cancellations.yaml.
    Running the pipeline for that date must surface a cancellation signal --
    it must not silently transcribe a recording and treat it as a normal
    capture, which is exactly what hides the fact that nothing was taught
    (docs/GOTCHAS.md; class-watch.sh's is_cancelled() comment makes the same
    point for the live-capture side of the pipeline).

    As of this writing cmd_run in __main__.py has no cancellations.yaml
    check at all, so this is expected to genuinely fail until that's added
    -- see tests/README.md.
    """
    bindir, log = fake_bin
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    course = classnotes_root / "intro-statistics"
    mp4 = course / "raw" / "2026-09-02-lecture.mp4"
    mp4.write_bytes(b"fake")

    result = run_cli("run", "intro-statistics", str(mp4), "--date", "2026-09-02")

    combined = (result.stdout + result.stderr).lower()
    assert "cancel" in combined, (
        "running a course on a cancelled date produced no cancellation "
        "signal in the output at all"
    )


def test_status_reports_a_cancellation_not_a_gap(classnotes_root, monkeypatch):
    """intro-statistics has a Saturday 15:00 session (sample_courses.yaml).
    2026-09-05 is a Saturday and is cancelled whole-day here -- status --all
    must report it as cancelled, not count it among missing/uncaptured
    sessions (docs/GOTCHAS.md: 'a report that cries wolf is a report nobody
    reads' -- the whole point of cancellations.yaml)."""
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    (classnotes_root / "cancellations.yaml").write_text(
        "cancelled:\n  - 2026-09-05   # matches intro-statistics' Sat 15:00\n",
        encoding="utf-8",
    )

    result = run_cli("status", "--all")

    assert "Traceback" not in result.stderr
    matching_lines = [l for l in result.stdout.splitlines() if "2026-09-05" in l]
    assert matching_lines, f"no report line for 2026-09-05 at all:\n{result.stdout}"
    assert all("cancelled" in l for l in matching_lines)
    assert not any("NO TRANSCRIPT" in l for l in matching_lines), (
        "a cancelled session must not also be reported as a missing one"
    )
