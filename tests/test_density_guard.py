"""Contract test: the density guard (classnotes/density.py, confirmed present
in pybuild's in-progress package) -- re-transcribing the densest live-capture
chunk with the language forced and comparing its word count against the kept
transcript's word count for that chunk. A close match ("verified") proceeds;
a mismatch ("mismatch") must flag loudly. Measured case from the module's own
docstring: chunk-0017 on 2026-09-06, 451 words against 451 -- an exact match
that correctly cleared a false alarm.

Imports classnotes.density directly (a unit test with a fake, per the task's
own guidance) rather than going through the CLI, so this never needs a real
whisper model or a real Groq call -- only fake_bin's stubbed whisper-cli,
whose output word count is dialled in via CLASSNOTES_TEST_WHISPER_WORDS.

Skips cleanly until pybuild's feat/python-pipeline branch lands.
"""
import pytest

from conftest import require_classnotes


def _make_live_chunk(live_dir, original_words):
    live_dir.mkdir(parents=True, exist_ok=True)
    wav = live_dir / "chunk-0001.wav"
    txt = live_dir / "chunk-0001.txt"
    wav.write_bytes(b"fake wav bytes")
    txt.write_text(" ".join(f"kept{i}" for i in range(original_words)) + "\n", encoding="utf-8")
    return wav, txt


def test_matching_word_counts_is_verified(tmp_path, fake_bin, monkeypatch):
    require_classnotes()
    from classnotes import density

    bindir, log = fake_bin
    # need a WHISPER_MODEL path that exists, or _whisper_transcribe_wav bails
    # out to "unverifiable" before ever running the (stubbed) whisper-cli
    fake_model = tmp_path / "fake-model.bin"
    fake_model.write_bytes(b"not a real model")
    monkeypatch.setenv("WHISPER_MODEL", str(fake_model))
    monkeypatch.setenv("CLASSNOTES_TEST_WHISPER_WORDS", "25")

    live_dir = tmp_path / "raw" / "2026-09-06-live"
    _make_live_chunk(live_dir, original_words=25)

    result = density.check(live_dir, "en")

    assert result.status == "verified", result.detail
    assert result.original_words == 25
    assert result.recheck_words == 25


def test_mismatched_word_counts_is_flagged(tmp_path, fake_bin, monkeypatch):
    require_classnotes()
    from classnotes import density

    bindir, log = fake_bin
    fake_model = tmp_path / "fake-model.bin"
    fake_model.write_bytes(b"not a real model")
    monkeypatch.setenv("WHISPER_MODEL", str(fake_model))
    # kept chunk has 25 words; the forced-language recheck only finds 10 --
    # a real gap, not cadence (tolerance is max(3, 5% of 25) = 3).
    monkeypatch.setenv("CLASSNOTES_TEST_WHISPER_WORDS", "10")

    live_dir = tmp_path / "raw" / "2026-09-06-live"
    _make_live_chunk(live_dir, original_words=25)

    result = density.check(live_dir, "en")

    assert result.status == "mismatch"
    assert "DENSITY MISMATCH" in result.detail
    assert result.original_words == 25
    assert result.recheck_words == 10


def test_no_live_capture_is_unverifiable_not_silently_ok(tmp_path):
    """No chunked live capture (e.g. a plain Teams .mp4 download) means the
    density guard cannot mechanically re-verify anything. It must say so
    explicitly rather than reporting a silent 'ok'."""
    require_classnotes()
    from classnotes import density

    result = density.check(tmp_path / "raw" / "does-not-exist-live", "auto")
    assert result.status == "unverifiable"
