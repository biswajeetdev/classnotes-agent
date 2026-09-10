"""Contract test: 'Synthesis is REBUILT, never appended.' (SKILL.md step 4 --
appending gives 100 files and no study material). Given an existing
SYNTHESIS.md, the pipeline must replace it: new content in, old unique
strings gone.

synthesis.rebuild() always calls Groq for the connective prose, so this is a
unit test importing classnotes.synthesis directly and monkeypatching
classnotes.groq_client.chat with a fake -- exactly the "pure unit tests with
fixtures and fakes, no network, no Groq calls" the task asked for. See
test_cli_contract.py's docstring for why the CLI-subprocess route can't be
used for this without a real GROQ_API_KEY (which this suite deliberately
never sets).

Skips cleanly until pybuild's feat/python-pipeline branch lands.
"""
from conftest import FIXTURES, require_classnotes

FAKE_SYNTHESIS_RESPONSE = """## Concept index
- *Cross validation* -- checking generalisation -> [2026-09-01](lectures/2026-09-01-cross-validation.md)

## How it fits together
Only one lecture so far; this section fills in as more are added.

## Likely exam questions
- What is cross validation used for? -> [2026-09-01](lectures/2026-09-01-cross-validation.md)

## Revised or contradicted
None yet.

## Thin ice
None yet.
"""


def _seeded_paths_and_course(classnotes_root, monkeypatch):
    from classnotes import config

    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    course = config.resolve_course(classnotes_root, "intro-statistics")
    paths = config.Paths(classnotes_root)

    old_synthesis = (FIXTURES / "sample_synthesis_old.md").read_text(encoding="utf-8")
    paths.synthesis(course.slug).write_text(old_synthesis, encoding="utf-8")
    lectures = paths.lectures_dir_write(course.slug)
    lectures.mkdir(parents=True, exist_ok=True)
    (lectures / "2026-09-01-cross-validation.md").write_text(
        (FIXTURES / "sample_note_clean.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return paths, course, old_synthesis


def test_synthesis_replaces_not_appends(classnotes_root, monkeypatch):
    require_classnotes()
    from classnotes import groq_client, synthesis

    paths, course, old_synthesis = _seeded_paths_and_course(classnotes_root, monkeypatch)
    monkeypatch.setattr(groq_client, "chat", lambda *a, **k: FAKE_SYNTHESIS_RESPONSE)

    out_path, warnings = synthesis.rebuild(paths, course)

    rebuilt = out_path.read_text(encoding="utf-8")
    assert "OLD_UNIQUE_MARKER_ZZZ" not in rebuilt, (
        "synthesis rebuild left stale content from the previous version -- "
        "it must be a full rewrite, not an append"
    )
    assert rebuilt != old_synthesis
    assert "Cross validation" in rebuilt


def test_synthesis_dry_run_does_not_touch_the_file(classnotes_root, monkeypatch):
    require_classnotes()
    from classnotes import groq_client, synthesis

    paths, course, old_synthesis = _seeded_paths_and_course(classnotes_root, monkeypatch)
    called = []
    monkeypatch.setattr(groq_client, "chat", lambda *a, **k: called.append(1) or FAKE_SYNTHESIS_RESPONSE)

    out_path, warnings = synthesis.rebuild(paths, course, dry_run=True)

    assert out_path is None
    assert not called, "dry-run must not call Groq at all"
    assert paths.synthesis(course.slug).read_text(encoding="utf-8") == old_synthesis


def test_rebuild_refuses_to_overwrite_when_the_model_returns_nothing(classnotes_root, monkeypatch):
    """A SYNTHESIS.md is a whole course's accumulated exam-prep value and rebuild
    is a full overwrite, so an unusable model reply must not be written over it.

    Measured 10 Sep 2026: GROQ_MODEL was a reasoning model, its `reasoning` field
    ate the completion budget, the API returned 200 with empty content, and this
    replaced an 18 KB synthesis with five "(not generated)" headings. The file
    must come out byte-identical instead."""
    require_classnotes()

    import pytest

    from classnotes import groq_client, synthesis

    paths, course, old_synthesis = _seeded_paths_and_course(classnotes_root, monkeypatch)
    monkeypatch.setattr(groq_client, "chat", lambda *a, **k: "")

    with pytest.raises(RuntimeError):
        synthesis.rebuild(paths, course)

    assert paths.synthesis(course.slug).read_text(encoding="utf-8") == old_synthesis, (
        "rebuild overwrote a real SYNTHESIS.md with an empty skeleton"
    )


def test_rebuild_refuses_a_partial_overwrite(classnotes_root, monkeypatch):
    """A truncated reply is the common case, not the rare one: the model runs out
    of budget partway down and the trailing sections go missing. Writing those as
    "(not generated)" over an existing synthesis loses real material, so a partial
    result must be refused too -- not just a wholly empty one."""
    require_classnotes()

    import pytest

    from classnotes import groq_client, synthesis

    paths, course, old_synthesis = _seeded_paths_and_course(classnotes_root, monkeypatch)
    truncated = FAKE_SYNTHESIS_RESPONSE.split("## Revised or contradicted")[0]
    monkeypatch.setattr(groq_client, "chat", lambda *a, **k: truncated)

    with pytest.raises(RuntimeError):
        synthesis.rebuild(paths, course)

    assert paths.synthesis(course.slug).read_text(encoding="utf-8") == old_synthesis


def test_chat_raises_instead_of_returning_empty_content(monkeypatch):
    """groq_client.chat() must never hand a caller "" as if it were a reply --
    that is the success-shaped failure that made the overwrite above possible.
    One retry at a bigger budget, then a loud GroqError."""
    require_classnotes()

    import json

    import pytest

    from classnotes import groq_client

    budgets = []

    class _Resp:
        def __init__(self, payload): self._p = payload
        def read(self): return json.dumps(self._p).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        budgets.append(json.loads(req.data)["max_completion_tokens"])
        return _Resp({"choices": [{"finish_reason": "length",
                                   "message": {"content": "", "reasoning": "thinking..."}}]})

    monkeypatch.setattr(groq_client.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(groq_client.GroqError):
        groq_client.chat("sys", "user", max_tokens=500, key="test-key")

    assert len(budgets) == 2, f"expected one retry at a larger budget, got {budgets}"
    assert budgets[1] > budgets[0]
