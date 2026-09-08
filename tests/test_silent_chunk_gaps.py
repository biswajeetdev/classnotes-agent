"""Contract test: 'Silent-chunk sequence gaps are explained, not treated as
loss.' Live capture deletes chunks below ~-45 dB (see scripts/live-notes.sh
transcribe_chunk(), which does `rm -f "$w"` on a silent chunk) -- this leaves
numbering holes like chunk-0001.wav, chunk-0003.wav with 0002 missing. That
is expected behaviour, not evidence of a lost or corrupted chunk, and the
classnotes/ package's consolidated version of this logic must say so rather
than flagging a numbering gap as data loss.

Skips cleanly until pybuild's feat/python-pipeline branch lands. The exact
function isn't part of the published CLI contract, so this tries a couple of
plausible import paths and skips with a clear message if none match yet.
"""
import pytest

from conftest import require_classnotes


def _find_gap_explainer():
    candidates = [
        ("classnotes.chunks", "explain_gaps"),
        ("classnotes.transcribe", "explain_gaps"),
        ("classnotes.chunks", "classify_gap"),
    ]
    for modname, funcname in candidates:
        try:
            mod = __import__(modname, fromlist=[funcname])
        except ImportError:
            continue
        fn = getattr(mod, funcname, None)
        if fn is not None:
            return fn
    return None


def test_a_numbering_gap_from_deleted_silent_chunks_is_not_reported_as_loss():
    require_classnotes()
    fn = _find_gap_explainer()
    if fn is None:
        pytest.skip(
            "no chunk-gap-explainer function found yet at any of the candidate "
            "locations tried in _find_gap_explainer() -- update that list once "
            "pybuild names the real one"
        )
    # chunk-0002.wav is missing because it was silent and deleted, not lost.
    present = ["chunk-0001.wav", "chunk-0003.wav", "chunk-0004.wav"]
    result = fn(present)
    assert result is not None
    # whatever the shape, it must not flag this as an unexplained loss
    text = str(result).lower()
    assert "lost" not in text and "corrupt" not in text and "error" not in text
