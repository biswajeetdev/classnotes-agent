"""scripts/digest.py must never return an empty or truncated digest silently.

A reasoning model can answer HTTP 200 with finish_reason="length" and an empty
content once its budget goes on reasoning. Returned as-is, that became a digest
file that looked short but valid. These tests pin the loud failure instead.
No network: urlopen is replaced with a canned response.
"""
import importlib.util
import io
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "digest.py"


def _load():
    spec = importlib.util.spec_from_file_location("digest_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(content, finish_reason, seen):
    def urlopen(req, timeout=None):
        seen.append(json.loads(req.data))
        body = {"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]}
        return _Resp(json.dumps(body).encode())
    return urlopen


def test_returns_content_on_a_complete_reply(monkeypatch):
    mod = _load()
    seen = []
    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake_urlopen("## Topics\n- x", "stop", seen))
    assert mod.call("chunk", "key", "openai/gpt-oss-120b") == "## Topics\n- x"


@pytest.mark.parametrize("content", [None, "", "   "])
def test_empty_content_raises(monkeypatch, content):
    mod = _load()
    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake_urlopen(content, "length", []))
    with pytest.raises(RuntimeError, match="empty content"):
        mod.call("chunk", "key", "openai/gpt-oss-120b")


def test_truncated_content_raises(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake_urlopen("## Topics\n- half", "length", []))
    with pytest.raises(RuntimeError, match="truncated"):
        mod.call("chunk", "key", "openai/gpt-oss-120b")


def test_reasoning_effort_only_sent_to_reasoning_models(monkeypatch):
    mod = _load()
    seen = []
    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake_urlopen("ok", "stop", seen))
    mod.call("chunk", "key", "openai/gpt-oss-120b")
    mod.call("chunk", "key", "llama-3.1-8b-instant")
    assert seen[0].get("reasoning_effort") == "low"
    assert "reasoning_effort" not in seen[1]
