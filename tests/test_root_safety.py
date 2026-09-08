"""Contract test: 'Never writes outside ~/class-notes/' (docs/GOTCHAS.md /
SKILL.md Constraints) and 'Never delete anything under raw/ or transcripts/'.
Asserted with a temp root -- classnotes_root -- so this never touches the
user's real data even if the assertion were to fail.

Assumes CLASSNOTES_ROOT is how the pipeline's root is overridden for testing
(see tests/README.md for this assumption and how to adjust it if pybuild
used a different mechanism). Skips cleanly until pybuild's
feat/python-pipeline branch lands.
"""
import os

from conftest import run_cli


def _snapshot(root):
    """Every file under root, with its size and mtime, so we can detect
    anything written, moved or deleted."""
    out = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for f in filenames:
            p = os.path.join(dirpath, f)
            st = os.stat(p)
            out[p] = (st.st_size, st.st_mtime_ns)
    return out


def test_raw_files_are_never_deleted(classnotes_root, fake_bin, monkeypatch):
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    course = classnotes_root / "intro-statistics"
    raw_file = course / "raw" / "2026-09-01-lecture.mp4"
    raw_file.write_bytes(b"fake video bytes")

    run_cli("run", "intro-statistics", str(raw_file), "--date", "2026-09-01")

    assert raw_file.exists(), "a file under raw/ was deleted by the pipeline"


def test_existing_transcripts_are_never_deleted(classnotes_root, fake_bin, monkeypatch):
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    course = classnotes_root / "intro-statistics"
    raw_file = course / "raw" / "2026-09-01-lecture.mp4"
    raw_file.write_bytes(b"fake")
    other_date = course / "transcripts" / "2026-08-25.txt"
    other_date.write_text("an unrelated earlier transcript\n")

    run_cli("run", "intro-statistics", str(raw_file), "--date", "2026-09-01")

    assert other_date.exists(), "a file under transcripts/ was deleted by the pipeline"


def test_nothing_is_written_outside_the_root(classnotes_root, fake_bin, monkeypatch, tmp_path):
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    mp4 = classnotes_root / "intro-statistics" / "raw" / "2026-09-01-lecture.mp4"
    mp4.write_bytes(b"fake")
    sibling = tmp_path / "sibling-should-stay-empty"
    sibling.mkdir()
    before = _snapshot(sibling)

    # These will fail partway through (no GROQ_API_KEY -- deliberately never
    # set in this suite) once they reach note-drafting, but everything up to
    # that point (transcription, density check) is real pipeline work and
    # must still respect root isolation.
    run_cli("run", "intro-statistics", str(mp4), "--date", "2026-09-01")
    run_cli("note", "intro-statistics", "2026-09-01")
    run_cli("synthesis", "intro-statistics")

    after = _snapshot(sibling)
    assert after == before, "the pipeline wrote outside its configured root"
