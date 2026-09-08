"""Contract tests: the classnotes/ package must never build a whisper-cli
invocation that includes -bs 1 (silent total failure: exits rc=0 in <1s,
writes no transcript at all) or -tr/--translate (destroys technical terms
and emphasis in code-switched audio). See docs/GOTCHAS.md 'Never pass -bs 1'
and 'Never use translation mode'.

Uses fake_bin to stub whisper-cli on PATH and inspect exactly what argv the
pipeline built, without ever invoking real whisper or touching audio.
Skips cleanly until pybuild's feat/python-pipeline branch lands.
"""
from conftest import run_cli


def _logged_invocations(log_path):
    if not log_path.exists():
        return []
    return [l for l in log_path.read_text().splitlines() if l.strip()]


def _run_transcription(classnotes_root, fake_bin, monkeypatch):
    """`run` with no existing transcript and a real input file forces the
    transcribe.sh -> whisper-cli path. Returns the whisper-cli invocations."""
    bindir, log = fake_bin
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    mp4 = classnotes_root / "intro-statistics" / "raw" / "2026-09-01-lecture.mp4"
    mp4.write_bytes(b"fake")
    run_cli("run", "intro-statistics", str(mp4), "--date", "2026-09-01")
    return [l for l in _logged_invocations(log) if "whisper-cli" in l]


def test_run_never_passes_bs_1(classnotes_root, fake_bin, monkeypatch):
    whisper_calls = _run_transcription(classnotes_root, fake_bin, monkeypatch)
    assert whisper_calls, "expected at least one whisper-cli invocation"
    for call in whisper_calls:
        args = call.split()
        assert not ("-bs" in args and args[args.index("-bs") + 1] == "1")


def test_run_never_passes_translate_flag(classnotes_root, fake_bin, monkeypatch):
    whisper_calls = _run_transcription(classnotes_root, fake_bin, monkeypatch)
    assert whisper_calls, "expected at least one whisper-cli invocation"
    for call in whisper_calls:
        args = call.split()
        assert "-tr" not in args
        assert "--translate" not in args


def test_run_language_defaults_to_auto(classnotes_root, fake_bin, monkeypatch):
    """GOTCHAS.md: 'auto' is the documented default and the only mode that
    doesn't require the caller to already know the dominant language."""
    whisper_calls = _run_transcription(classnotes_root, fake_bin, monkeypatch)
    assert whisper_calls
    for call in whisper_calls:
        args = call.split()
        if "-l" in args:
            assert args[args.index("-l") + 1] == "auto"
