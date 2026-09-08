"""Contract test: 'Skip this if a transcripts/<date>.txt already exists --
reuse it. Re-running a 90-minute lecture costs many minutes for nothing.'
(SKILL.md, step 2). Skips cleanly until pybuild's feat/python-pipeline
branch lands.
"""
from conftest import run_cli


def test_run_does_not_retranscribe_when_transcript_already_exists(
    classnotes_root, fake_bin, monkeypatch
):
    bindir, log = fake_bin
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    course = classnotes_root / "intro-statistics"
    (course / "raw" / "2026-09-01-lecture.mp4").write_bytes(b"fake")
    (course / "transcripts" / "2026-09-01.txt").write_text(
        "an existing transcript that must be reused, not overwritten\n"
    )
    before = (course / "transcripts" / "2026-09-01.txt").read_text()

    run_cli("run", "intro-statistics", "--date", "2026-09-01")

    after = (course / "transcripts" / "2026-09-01.txt").read_text()
    assert after == before, "existing transcript was overwritten instead of reused"
    invocations = log.read_text().splitlines() if log.exists() else []
    assert not any("whisper-cli" in l for l in invocations), (
        "whisper-cli was invoked even though a transcript already existed"
    )
