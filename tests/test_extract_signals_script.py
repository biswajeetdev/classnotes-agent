"""Real tests against scripts/extract-signals.py -- gotcha: 'a summariser will
drop the single most important sentence' and 'live-coding narration is not
emphasis'. Runs for real today against the already-implemented script.
"""
import subprocess
import sys

from conftest import FIXTURES, SCRIPTS


def _run():
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "extract-signals.py"),
         str(FIXTURES / "sample_transcript.txt")],
        capture_output=True, text=True, timeout=30,
    )


def test_signal_words_are_extracted_verbatim():
    result = _run()
    assert result.returncode == 0
    assert "This is important, it will come in the exam." in result.stdout


def test_absolute_statement_without_a_signal_word_is_still_caught():
    """'we can change the model, but we cannot change the data' carries no
    signal WORD (no 'exam', 'important', etc) -- it is caught only because
    the SIGNAL regex also matches absolute/negated framing ('cannot change').
    This is the exact real case from GOTCHAS.md that a keyword-only grep
    would have missed."""
    result = _run()
    assert "cannot change the data" in result.stdout


def test_noise_lines_are_dropped():
    result = _run()
    # "Okay." and "Thank you." are pure filler and must never surface as signal
    assert "- Okay." not in result.stdout
    assert "- Thank you." not in result.stdout


def test_repeated_narration_line_is_flagged_as_repetition_not_lost():
    """'Now I am going to write a comment.' appears 3x in the fixture -- the
    live-coding-narration gotcha says repetition detectors will rank this as
    emphasis (correctly, mechanically) even though a human would discard it
    by hand. We assert the mechanism works; discarding by hand is a note-
    writing step, not something this script should silently do."""
    result = _run()
    assert "Repeated lines" in result.stdout
    assert "Now I am going to write a comment." in result.stdout
    assert "(3x)" in result.stdout
