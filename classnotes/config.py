"""Course config, .env loading, and root-path resolution.

Parses courses.yaml with the same tolerant regex approach term-coverage.py and
class-watch.sh already use (see scripts/term-coverage.py) so this package can
never disagree with them about what's scheduled -- and so we don't add a
pyyaml dependency that isn't already installed.
"""
from __future__ import annotations

import dataclasses
import os
import re
from pathlib import Path

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Per-course whisper language override. NOT stored in courses.yaml -- that file
# is real config other scripts (class-watch.sh, term-coverage.py, gen-calendar.py)
# parse and the user hand-maintains; this pipeline is additive and keeps its own
# knobs separate rather than editing a file it didn't create. Easy to relocate
# into a `language:` field in courses.yaml later if that's preferred -- the
# loader below checks there first and only falls back to this dict.
#
# policy-ethics-legal: LESSONS.md records "Lectures in English throughout -- no
# Hindi. Force -l en for gap recovery" for Dr. Karan's course (MB-GAI-505).
LANG_OVERRIDES = {
    "policy-ethics-legal": "en",
}


@dataclasses.dataclass
class Course:
    slug: str
    code: str
    name: str
    professor: str
    exam: str
    aliases: list[str]


class ConfigError(Exception):
    pass


def load_env(root: Path) -> None:
    """Load ~/class-notes/.env into os.environ (does not overwrite existing)."""
    p = root / ".env"
    if not p.exists():
        return
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def default_root() -> Path:
    return Path(os.environ.get("CLASSNOTES_ROOT", "~/class-notes")).expanduser()


def load_courses(root: Path) -> list[Course]:
    path = root / "courses.yaml"
    if not path.exists():
        raise ConfigError(f"no courses.yaml at {path}")
    txt = path.read_text(encoding="utf-8")
    out = []
    for blk in txt.split("- slug:")[1:]:
        slug = blk.split("\n")[0].strip()

        def field(name, default=""):
            m = re.search(rf"^\s*{name}:\s*(.+)$", blk, re.M)
            return m.group(1).strip() if m else default

        aliases_raw = field("aliases", "[]")
        aliases = [a.strip() for a in aliases_raw.strip("[]").split(",") if a.strip()]
        out.append(Course(
            slug=slug,
            code=field("code"),
            name=field("name"),
            professor=field("professor"),
            exam=field("exam", "TBD"),
            aliases=aliases,
        ))
    if not out:
        raise ConfigError(f"no courses parsed from {path}")
    return out


def resolve_course(root: Path, needle: str) -> Course:
    """Match a slug, alias, or course code (case-insensitive)."""
    needle_l = needle.strip().lower()
    courses = load_courses(root)
    for c in courses:
        if c.slug.lower() == needle_l:
            return c
    # alias/code match -- same rule as the substring fallback below: only resolve
    # if exactly one course matches. Two courses sharing an alias used to
    # silently resolve to whichever was listed first in courses.yaml.
    alias_hits = [c for c in courses
                  if needle_l in [a.lower() for a in c.aliases] or needle_l == c.code.lower()]
    if len(alias_hits) == 1:
        return alias_hits[0]
    if len(alias_hits) > 1:
        names = ", ".join(c.slug for c in alias_hits)
        raise ConfigError(f"'{needle}' matches more than one course by alias/code: {names}")
    # substring fallback on slug, but only if exactly one match -- never guess silently
    substr = [c for c in courses if needle_l in c.slug.lower()]
    if len(substr) == 1:
        return substr[0]
    known = ", ".join(c.slug for c in courses)
    raise ConfigError(f"no unique course match for '{needle}'. Known: {known}")


def course_lang(course: Course) -> str:
    return LANG_OVERRIDES.get(course.slug, "auto")


def load_cancellations(root: Path):
    """-> (whole_days:set[str], per_course:set[(date,slug)], per_slot:set[(date,slug,slot)])

    Mirrors scripts/term-coverage.py's parser exactly -- kept in this package too
    since `status` shells out to term-coverage.py directly rather than reading
    this, but other commands may want the same info later without a subprocess.
    """
    days, per_course, per_slot = set(), set(), set()
    path = root / "cancellations.yaml"
    if not path.exists():
        return days, per_course, per_slot
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line.startswith("- "):
            continue
        parts = line[2:].split()
        if not parts or not re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0]):
            continue
        if len(parts) == 1:
            days.add(parts[0])
        elif len(parts) == 2:
            per_course.add((parts[0], parts[1]))
        else:
            per_slot.add((parts[0], parts[1], parts[2]))
    return days, per_course, per_slot


class Paths:
    """Resolves read paths (always the real root) and write paths (optionally
    redirected via --out-root, so tests never touch the real class-notes tree).
    """

    def __init__(self, root: Path, out_root: Path | None = None):
        self.root = root
        self.write_root = out_root if out_root is not None else root

    # -- reads: transcripts, raw media, LESSONS.md, existing notes -- always real root
    def course_dir(self, slug: str) -> Path:
        return self.root / slug

    def transcripts_dir(self, slug: str) -> Path:
        return self.course_dir(slug) / "transcripts"

    def transcript(self, slug: str, date: str) -> Path:
        return self.transcripts_dir(slug) / f"{date}.txt"

    def digest(self, slug: str, date: str) -> Path:
        return self.transcripts_dir(slug) / f"{date}-digest.md"

    def raw_live_dir(self, slug: str, date: str) -> Path:
        return self.course_dir(slug) / "raw" / f"{date}-live"

    def lessons(self, slug: str) -> Path:
        return self.course_dir(slug) / "LESSONS.md"

    # -- writes AND their own reads: lecture notes, SYNTHESIS.md, ASSIGNMENTS.md,
    # QUESTIONS.md. These are the pipeline's own output artefacts -- synthesis
    # harvests lecture notes back in, so both sides must agree on write_root, or
    # a test run with --out-root would silently harvest real notes instead of
    # the ones it just wrote. In normal use write_root == root, so this is a
    # no-op split.
    def write_course_dir(self, slug: str) -> Path:
        return self.write_root / slug

    def lectures_dir_write(self, slug: str) -> Path:
        return self.write_course_dir(slug) / "lectures"

    # alias: lecture notes are only ever produced by this pipeline, so "read"
    # and "write" are the same tree.
    def lectures_dir_read(self, slug: str) -> Path:
        return self.lectures_dir_write(slug)

    def lecture_note(self, slug: str, date: str, topic_slug: str) -> Path:
        return self.lectures_dir_write(slug) / f"{date}-{topic_slug}.md"

    def synthesis(self, slug: str) -> Path:
        return self.write_course_dir(slug) / "SYNTHESIS.md"

    def synthesis_concepts(self, slug: str) -> Path:
        return self.write_course_dir(slug) / "SYNTHESIS-concepts.md"

    def assignments(self, slug: str) -> Path:
        return self.write_course_dir(slug) / "ASSIGNMENTS.md"

    def questions(self, slug: str) -> Path:
        return self.write_course_dir(slug) / "QUESTIONS.md"
