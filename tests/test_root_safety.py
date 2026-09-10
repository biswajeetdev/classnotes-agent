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


def test_digest_reads_its_env_from_the_configured_root(tmp_path, monkeypatch):
    """digest.py used to open ~/class-notes/.env unconditionally, so a run under a
    throwaway CLASSNOTES_ROOT still picked up the user's real GROQ_API_KEY and
    spent real quota. The test suite was doing exactly that."""
    import subprocess
    import sys

    from conftest import SCRIPTS

    fake_root = tmp_path / "root"
    fake_root.mkdir()
    (fake_root / ".env").write_text("GROQ_API_KEY=from-the-configured-root\n", encoding="utf-8")

    probe = (
        "import os, sys, importlib.util;"
        f"spec=importlib.util.spec_from_file_location('d', {str(SCRIPTS / 'digest.py')!r});"
        "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
        "m.load_env(); print(os.environ.get('GROQ_API_KEY', ''))"
    )
    # Drop the key entirely rather than blanking it: load_env uses setdefault, and
    # an empty string already counts as set.
    env = {k: v for k, v in os.environ.items() if k != "GROQ_API_KEY"}
    env["CLASSNOTES_ROOT"] = str(fake_root)
    out = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True, text=True, timeout=30, env=env,
    )
    assert out.stdout.strip() == "from-the-configured-root", out.stdout + out.stderr
