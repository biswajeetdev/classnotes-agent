"""Real tests against scripts/check-coverage.py -- gotcha: 'whisper locks onto
ONE language per file and silently drops speech in the other' plus the CLI-
contract gotcha 'check-coverage.py must never be handed a .txt'.

These import the actual, already-implemented script (not the future
classnotes/ package) so they run for real today, not skipped.
"""
from conftest import FIXTURES, import_script


def test_srt_regions_parses_timestamps_correctly():
    cc = import_script("check-coverage.py")
    regions = cc.srt_regions(str(FIXTURES / "sample_transcript.srt"))
    assert regions == [(0.0, 5.5), (10.0, 20.25)]


def test_srt_regions_on_a_txt_file_returns_nothing():
    """The measured failure mode: check-coverage.py expects an .srt timeline.
    Handed a plain .txt transcript instead, srt_regions() finds no timestamp
    lines and silently returns an empty list -- which, fed into uncovered(),
    would report ALL speech as missing ("100% missing" false alarm). This
    documents that the script itself cannot tell the difference, so the
    caller (the classnotes pipeline) MUST route .srt vs .txt correctly and
    never hand this function a .txt path.
    """
    cc = import_script("check-coverage.py")
    regions = cc.srt_regions(str(FIXTURES / "sample_transcript.txt"))
    assert regions == []


def test_uncovered_reports_no_gaps_when_speech_is_fully_covered():
    cc = import_script("check-coverage.py")
    speech = [(0.0, 30.0)]
    covered = [(0.0, 30.0)]
    assert cc.uncovered(speech, covered, min_gap=3.0) == []


def test_uncovered_reports_a_real_gap():
    cc = import_script("check-coverage.py")
    # speech runs 0-30s, but the transcript only covers 0-10s and 25-30s --
    # a 15s stretch (10-25) went untranscribed, exactly the whisper
    # language-lock failure mode this script exists to catch.
    speech = [(0.0, 30.0)]
    covered = [(0.0, 10.0), (25.0, 30.0)]
    gaps = cc.uncovered(speech, covered, min_gap=3.0)
    assert gaps == [(10.0, 25.0)]


def test_uncovered_ignores_gaps_below_min_gap():
    """Calibration caveat from GOTCHAS.md: many small flagged gaps are almost
    always false alarms from room tone, not real loss -- min_gap exists to
    filter those out."""
    cc = import_script("check-coverage.py")
    speech = [(0.0, 10.0)]
    covered = [(0.0, 4.0), (5.5, 10.0)]  # 1.5s gap
    assert cc.uncovered(speech, covered, min_gap=3.0) == []


def test_hms_formatting():
    cc = import_script("check-coverage.py")
    assert cc.hms(65.5) == "01:05.50"
    assert cc.hms(0) == "00:00.00"
