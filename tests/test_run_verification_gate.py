"""`run` must not publish an unverified note.

verify-notes.py flags a note whose figures, quotes or names are not grounded in the
transcript. The note is still written to disk so it can be fixed, but `run` has to
stop there: appending its questions/admin to QUESTIONS.md / ASSIGNMENTS.md, or
rebuilding SYNTHESIS.md from it, would carry an unverified claim into exam prep.

No whisper, no Groq, no network -- every stage after transcription is monkeypatched.
"""
import argparse
import types

import pytest
from conftest import require_classnotes

DATE = "2026-09-01"


def _args(**over):
    base = dict(course="intro-statistics", input=None, date=DATE, lang=None, out_root=None,
                dry_run=False, force=False, no_groq_signals=True, regenerate_digest=False,
                model=None)
    base.update(over)
    return argparse.Namespace(**base)


@pytest.fixture
def cli(classnotes_root, monkeypatch, tmp_path):
    require_classnotes()
    import classnotes.__main__ as cli
    from classnotes import notewriter

    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    (classnotes_root / "intro-statistics" / "transcripts" / f"{DATE}.txt").write_text("kept transcript\n")
    monkeypatch.setattr(cli.config, "load_env", lambda root: None)
    monkeypatch.setattr(cli.notewriter, "density_check",
                        lambda *a, **k: types.SimpleNamespace(status="ok", detail="stubbed"))

    calls = []
    monkeypatch.setattr(cli.notewriter, "append_admin_and_questions", lambda *a, **k: calls.append("append"))
    monkeypatch.setattr(cli.synthesis, "rebuild", lambda *a, **k: (calls.append("synthesis") or (tmp_path / "S.md", [])))

    def set_verified(verified):
        note = tmp_path / f"{DATE}-topic.md"
        note.write_text("# note\n")
        result = notewriter.NoteResult(path=note, verified=verified, verify_output="(stub)",
                                       warnings=[], topic_slug="topic", title="Topic")
        monkeypatch.setattr(cli.notewriter, "write_note", lambda *a, **k: result)

    return cli, calls, set_verified


def test_unverified_note_stops_before_questions_assignments_and_synthesis(cli, capsys):
    mod, calls, set_verified = cli
    set_verified(False)
    with pytest.raises(SystemExit) as exc:
        mod.cmd_run(_args())
    assert exc.value.code == 1
    assert calls == [], "an unverified note must not be appended or fed into SYNTHESIS.md"
    assert "failed verification" in capsys.readouterr().out


def test_verified_note_is_published_and_synthesis_rebuilt(cli):
    mod, calls, set_verified = cli
    set_verified(True)
    mod.cmd_run(_args())
    assert calls == ["append", "synthesis"]
