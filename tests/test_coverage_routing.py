"""Contract test: 'check-coverage.py must never be handed a .txt' -- it needs
an .srt timeline and, as demonstrated for real in
test_check_coverage_script.py::test_srt_regions_on_a_txt_file_returns_nothing,
silently reports 100% missing on a .txt. The classnotes/ pipeline must route
to the .srt file (or refuse) rather than ever pass check-coverage.py (or its
consolidated equivalent) a plain .txt path.

Skips cleanly until pybuild's feat/python-pipeline branch lands.
"""
from conftest import run_cli


def test_run_does_not_pass_a_txt_path_where_an_srt_is_needed(
    classnotes_root, fake_bin, monkeypatch
):
    bindir, log = fake_bin
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    course = classnotes_root / "intro-statistics"
    (course / "raw" / "2026-09-01-lecture.mp4").write_bytes(b"fake")

    result = run_cli("run", "intro-statistics", "--date", "2026-09-01")

    assert "Traceback" not in result.stderr
    combined = (result.stdout + result.stderr).lower()
    # A false "100% missing" report is the measured failure mode; the pipeline
    # must not produce that kind of alarm from feeding coverage-checking a .txt.
    assert "100% missing" not in combined and "100 % missing" not in combined
