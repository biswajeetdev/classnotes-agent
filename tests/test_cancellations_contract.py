"""Contract test: the classnotes/ package's own cancellations.yaml awareness
(if it consolidates class-watch.sh's is_cancelled() / term-coverage.py's
load_cancellations() into the `run` pipeline) must never silently capture and
count a cancelled session as a normal one.

See test_term_coverage_script.py for real, safely-isolated tests of the
underlying parsing logic (already implemented in scripts/term-coverage.py),
which is not gated on this. This file is the pipeline-level (`run`) version.
Skips cleanly until pybuild's feat/python-pipeline branch lands.

NOT tested here: `status`. cmd_status shells out to scripts/term-coverage.py,
whose ROOT is hardcoded to the real ~/class-notes and ignores
CLASSNOTES_ROOT -- see test_cli_contract.py's module docstring for the full
explanation and tests/README.md for the flag raised with pybuild.
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
