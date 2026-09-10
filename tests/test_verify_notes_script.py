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


def _verify(tmp_path, note_body):
    note = tmp_path / "note.md"
    note.write_text(note_body, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "verify-notes.py"),
         str(note), str(FIXTURES / "sample_transcript.txt")],
        capture_output=True, text=True, timeout=30,
    )


def test_sentence_case_after_a_heading_is_not_read_as_a_name(tmp_path):
    """The NAME check looks for mid-sentence capitals, but \\s spans newlines,
    so a heading ending in a lowercase letter (or ")") used to make the next
    line's first word look mid-sentence. That flagged ordinary verbs opening a
    paragraph -- 'Maps ordered categories...' -- as unverified proper names,
    which is the cry-wolf failure the codebase explicitly rejects."""
    result = _verify(tmp_path, (
        "### Categorical-to-numeric encoding - ordinal encoder\n"
        "Maps ordered categories to integer codes.\n\n"
        "### Standardization (z-score scaling)\n"
        "Centers each feature to mean zero.\n"
    ))
    assert "NAME" not in result.stdout, result.stdout


def test_ungrounded_name_on_a_wrapped_line_is_still_caught(tmp_path):
    """The narrower rule must not blind the gate: a capital opening a wrapped
    continuation line is genuinely mid-sentence and still has to be checked."""
    result = _verify(tmp_path, (
        "The professor credited the result to\n"
        "Kolmogorov during the second half.\n"
    ))
    assert result.returncode == 1
    assert "NAME" in result.stdout and "Kolmogorov" in result.stdout
