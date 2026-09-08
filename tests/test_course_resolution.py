"""Contract test: course resolution by slug, alias, and unresolvable-course
handling -- 'an unresolvable course must ask/fail, never silently guess'
(SKILL.md step 1: 'Never guess a course silently; a note filed under the
wrong course corrupts that course's synthesis.').

Skips cleanly until pybuild's feat/python-pipeline branch lands.
"""
from conftest import FIXTURES, run_cli


def _seed_lecture_note(classnotes_root, slug="intro-statistics"):
    """synthesis --dry-run still requires at least one lecture note to exist
    (it raises FileNotFoundError before checking dry_run otherwise) -- seed
    one so a resolved course reaches a clean dry-run rather than a
    lecture-notes error that would mask what we're actually testing."""
    lectures = classnotes_root / slug / "lectures"
    lectures.mkdir(parents=True, exist_ok=True)
    (lectures / "2026-09-01-cross-validation.md").write_text(
        (FIXTURES / "sample_note_clean.md").read_text(encoding="utf-8"), encoding="utf-8"
    )


def test_exact_slug_resolves(classnotes_root, monkeypatch):
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    _seed_lecture_note(classnotes_root)
    result = run_cli("synthesis", "intro-statistics", "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr


def test_alias_resolves_to_the_right_course(classnotes_root, monkeypatch):
    """sample_courses.yaml gives intro-statistics the alias 'stats'."""
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    _seed_lecture_note(classnotes_root)
    result = run_cli("synthesis", "stats", "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr


def test_unresolvable_course_fails_rather_than_guessing(classnotes_root, monkeypatch):
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    result = run_cli("synthesis", "totally-not-a-real-course-slug")
    assert result.returncode != 0, (
        "an unresolvable course slug must fail (or prompt), never silently "
        "fall through to some default course"
    )
    assert "no unique course match" in (result.stdout + result.stderr).lower() or \
           "no course" in (result.stdout + result.stderr).lower()


def test_ambiguous_alias_does_not_silently_pick_one(classnotes_root, monkeypatch):
    """Give both fixture courses the alias 'stats' and require that resolving
    it fails rather than silently committing to one of the two -- filing a
    note under the wrong course corrupts that course's synthesis.

    Fixed in pybuild's commit 5f5b854: config.resolve_course()'s alias-match
    now collects every hit and raises ConfigError listing all of them when
    there's more than one, the same rule the slug-substring fallback already
    used (len(matches) == 1 required).
    """
    monkeypatch.setenv("CLASSNOTES_ROOT", str(classnotes_root))
    courses_yaml = classnotes_root / "courses.yaml"
    courses_yaml.write_text(
        courses_yaml.read_text(encoding="utf-8").replace(
            "aliases: [econ, micro, 102]", "aliases: [econ, micro, 102, stats]"
        ),
        encoding="utf-8",
    )
    _seed_lecture_note(classnotes_root, "intro-statistics")
    _seed_lecture_note(classnotes_root, "microeconomics")

    result = run_cli("synthesis", "stats")

    assert result.returncode != 0, (
        "an alias matching two courses must not be silently resolved to either one"
    )
    combined = (result.stdout + result.stderr).lower()
    assert "more than one course" in combined
    assert "intro-statistics" in combined and "microeconomics" in combined
