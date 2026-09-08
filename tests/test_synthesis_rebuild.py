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
