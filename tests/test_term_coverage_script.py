"""Real tests against scripts/term-coverage.py's load_courses() and
load_cancellations() -- gotcha 11 ('cancellations parsing: whole-day,
per-course, and per-slot forms; # comments ignored') and the session-schedule
half of gotcha 10 (course resolution). This is the same tolerant parser
class-watch.sh uses (by design, per the script's own docstring), so testing
it here exercises real, already-implemented behaviour today.

Never touches the user's real ~/class-notes/courses.yaml -- ROOT is
monkeypatched to point at the fixtures directory for the duration of each
test.
"""
from conftest import FIXTURES, import_script


def _tc(monkeypatch, tmp_path):
    """load_courses()/load_cancellations() read <ROOT>/courses.yaml and
    <ROOT>/cancellations.yaml by fixed name. Materialise the fixtures under
    those exact names in a throwaway tmp_path and point ROOT at it, so we
    never touch the user's real ~/class-notes/courses.yaml."""
    tc = import_script("term-coverage.py")
    (tmp_path / "courses.yaml").write_text(
        (FIXTURES / "sample_courses.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "cancellations.yaml").write_text(
        (FIXTURES / "sample_cancellations.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setattr(tc, "ROOT", str(tmp_path))
    return tc


def test_load_courses_parses_slugs_and_sessions(monkeypatch, tmp_path):
    tc = _tc(monkeypatch, tmp_path)
    courses = dict(tc.load_courses())
    assert set(courses) == {"intro-statistics", "microeconomics"}
    # "Mon 20:30-21:30 · Sat 15:00-17:00" -> two (day, start, end) sessions.
    # The END time is load-bearing, not decoration: term-coverage.py only treats a
    # slot as assessable once `now >= end`, which is what stops a class scheduled
    # later today -- or one still in progress -- from being reported as missed.
    assert ("Mon", "2030", "2130") in courses["intro-statistics"]
    assert ("Sat", "1500", "1700") in courses["intro-statistics"]
    assert ("Tue", "2000", "2130") in courses["microeconomics"]
    assert ("Thu", "2000", "2130") in courses["microeconomics"]


def test_cancellations_whole_day(monkeypatch, tmp_path):
    tc = _tc(monkeypatch, tmp_path)
    days, per_course, per_slot = tc.load_cancellations()
    assert "2026-09-02" in days


def test_cancellations_per_course(monkeypatch, tmp_path):
    tc = _tc(monkeypatch, tmp_path)
    _, per_course, _ = tc.load_cancellations()
    assert ("2026-09-03", "intro-statistics") in per_course


def test_cancellations_per_slot(monkeypatch, tmp_path):
    tc = _tc(monkeypatch, tmp_path)
    _, _, per_slot = tc.load_cancellations()
    assert ("2026-09-05", "intro-statistics", "2000") in per_slot


def test_cancellations_comment_only_line_is_ignored(monkeypatch, tmp_path):
    """The fixture has a line that is entirely a '#' comment after stripping
    ('# 2026-09-06 this whole line is a comment and must be ignored'). It
    must not be parsed as a cancellation of any kind."""
    tc = _tc(monkeypatch, tmp_path)
    days, per_course, per_slot = tc.load_cancellations()
    assert "2026-09-06" not in days
    assert not any(d == "2026-09-06" for d, *_ in per_course)
    assert not any(d == "2026-09-06" for d, *_ in per_slot)


def test_cancellations_trailing_comment_on_a_real_line_is_stripped(monkeypatch, tmp_path):
    """'- 2026-09-02   # public holiday' -- the comment after '#' must not
    leak into the parsed date/slug fields."""
    tc = _tc(monkeypatch, tmp_path)
    days, _, _ = tc.load_cancellations()
    assert days == {"2026-09-02"}  # exact date, no trailing comment text
