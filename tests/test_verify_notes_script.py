"""Real tests against scripts/verify-notes.py -- gotcha: 'verify the finished
note against the transcript', 'a summariser/paraphrase presented as a quote',
'a fabricated figure is worse than a gap'. Runs for real today (this script
already exists), not gated on the classnotes/ package.
"""
import subprocess
import sys

from conftest import FIXTURES, SCRIPTS, import_script


def test_norm_equates_spoken_and_written_notation():
    """norm() is used for substring containment checks in the real script,
    not exact equality, so we compare stripped forms here -- norm("99%")
    legitimately keeps an inconsequential trailing space from the "%" ->
    " percent " substitution that a containment check never notices."""
    vn = import_script("verify-notes.py")
    assert vn.norm("99%").strip() == vn.norm("99 percent").strip()
    assert vn.norm("y = mx").strip() == vn.norm("y is equal to mx").strip()


def test_num_variants_covers_common_forms():
    vn = import_script("verify-notes.py")
    variants = vn.num_variants("1,234")
    assert "1234" in variants
    assert "1,234" in variants


def test_clean_note_passes_verification():
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "verify-notes.py"),
         str(FIXTURES / "sample_note_clean.md"),
         str(FIXTURES / "sample_transcript.txt")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "grounded in the transcript" in result.stdout


def test_bad_note_is_flagged_and_fails():
    """Fabricated quote, fabricated number, and a fabricated proper name in
    sample_note_bad.md must all be caught -- verify-notes.py exits non-zero
    and the pipeline must gate publishing on this (see the classnotes/
    contract test in test_verification_gate.py)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "verify-notes.py"),
         str(FIXTURES / "sample_note_bad.md"),
         str(FIXTURES / "sample_transcript.txt")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 1
    assert "QUOTE" in result.stdout
    assert "NUMBER" in result.stdout
    assert "NAME" in result.stdout
