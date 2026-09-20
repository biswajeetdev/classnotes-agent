"""A digest part must never be accepted empty or truncated.

This is the regression guard for the failure that silently gutted two
SYNTHESIS.md files: a reasoning model spends its token budget on hidden
reasoning, returns `content: ""`, and the caller appends nothing, prints
"ok", and writes a digest with the middle missing. Nothing in the output
says anything went wrong.

`call()` must raise on both shapes so the run fails loudly and the previous
digest, which is still on disk, survives.
"""
import io
import json

import pytest

from conftest import import_script

digest = import_script("digest.py")


def _response(payload):
    """Stand in for urlopen's context manager with a canned Groq reply."""
    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    return _Resp(json.dumps(payload).encode())


def _patch(monkeypatch, payload):
    monkeypatch.setattr(digest.urllib.request, "urlopen",
                        lambda *a, **k: _response(payload))


def test_empty_content_raises(monkeypatch):
    _patch(monkeypatch, {"choices": [{"message": {"content": ""},
                                      "finish_reason": "stop"}]})
    with pytest.raises(RuntimeError, match="empty reply"):
        digest.call("some transcript", "key", "some-model")


def test_reasoning_only_reply_says_so(monkeypatch):
    """The specific gpt-oss failure: reasoning present, content empty."""
    _patch(monkeypatch, {"choices": [{"message": {"content": "",
                                                  "reasoning": "thinking..."},
                                      "finish_reason": "stop"}]})
    with pytest.raises(RuntimeError, match="reasoning"):
        digest.call("some transcript", "key", "some-model")


def test_whitespace_only_content_is_still_empty(monkeypatch):
    _patch(monkeypatch, {"choices": [{"message": {"content": "   \n  "},
                                      "finish_reason": "stop"}]})
    with pytest.raises(RuntimeError, match="empty reply"):
        digest.call("some transcript", "key", "some-model")


def test_truncated_reply_raises(monkeypatch):
    """finish_reason 'length' means the part stops mid-sentence."""
    _patch(monkeypatch, {"choices": [{"message": {"content": "a partial digest that"},
                                      "finish_reason": "length"}]})
    with pytest.raises(RuntimeError, match="truncated"):
        digest.call("some transcript", "key", "some-model")


def test_good_reply_is_returned(monkeypatch):
    _patch(monkeypatch, {"choices": [{"message": {"content": "  real content  "},
                                      "finish_reason": "stop"}]})
    assert digest.call("some transcript", "key", "some-model") == "real content"


def test_default_model_is_not_a_reasoning_model():
    """The default must answer directly, or the failure above comes back."""
    src = (digest.__file__)
    text = open(src, encoding="utf-8").read()
    assert 'GROQ_MODEL", "qwen/qwen3.8-27b"' in text, \
        "default model changed -- confirm the replacement is not a reasoning model"
