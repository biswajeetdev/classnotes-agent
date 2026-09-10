"""Rebuild <course>/SYNTHESIS.md from every lecture note in the course.

Never appended -- always regenerated from scratch (SKILL.md: "Appending gives
you 100 files and no study material"). Harvesting is deterministic Python
(regex over the already-structured lecture notes); only the connective prose
-- "How it fits together", ranked exam questions, "Revised or contradicted"
-- goes through Groq, because that's genuine cross-lecture judgement, not
something a template can produce.

Feeding Groq the harvested per-lecture digest (title/one-liner/concepts/⚡
signals/open questions) rather than the full notes is the right level of detail
anyway -- the synthesis argument is built from what each lecture judged
important, not from re-reading every paragraph.

That harvest is NOT unconditionally small, though, and this docstring used to
claim it was. Measured 10 Sep 2026: a 6-lecture course harvests to ~3,690 tokens,
and asking for all five sections beside that needs more of the free tier's
8,000-token/minute budget than remains -- unservable at any pacing. So the pass
is split in two, each half carrying only the fields it uses (concepts and links
for the index; signals and open questions for the prose). Two trimmed calls send
less input in total than one combined one.
"""
from __future__ import annotations

import dataclasses
import datetime
import re

from . import groq_client

MAX_LINES = 500

SYSTEM_PROMPT = """You write a rolling exam-prep synthesis for a university course, from a
structured harvest of that course's lecture notes (title, one-line summary, key concepts,
flagged exam signals, and open questions for each lecture, in chronological order).

Output ONLY markdown in this exact shape, nothing before or after:

## Concept index
Every concept across the term, one line each, grouped by theme (not by date). Each line
ends with a link to the lecture that covers it best, using the exact markdown link given
to you for that lecture. Shape (angle brackets are placeholders -- replace them, don't
copy them literally): "- *<concept name>* -- <your own one-clause description of it> ->
<the lecture link>". Example with real content filled in: "- *Human-in-the-loop* -- a
human approves each prediction before it takes effect -> [2026-08-30](lectures/foo.md)".

## How it fits together
Cross-lecture connections -- explicitly name which week's idea connects to which other
week's, and why. This is the part no single lecture note can give you; that's the point of
rebuilding this file. If there is only one lecture so far, say so plainly and explain this
section will fill in as more lectures are added, rather than inventing connections.

## Likely exam questions
Ranked by how much exam-signal weight the source lectures gave the underlying material.
For each: the question, and which lecture(s) to answer it from (link them).

## Revised or contradicted
Places where a later lecture corrected, refined or contradicted an earlier one. If none
yet, say so plainly -- do not invent a contradiction.

## Thin ice
Concepts mentioned once and never revisited, and unresolved items pulled from the open
questions given to you. This is the revision to-do list.

Rules: never invent a concept, connection or exam question not supported by what you were
given. Use the professor's/lecture's own terms. Keep it usable, not exhaustive."""

_RULES = ("Rules: never invent a concept, connection or exam question not supported by what "
          "you were given. Use the professor's/lecture's own terms. Keep it usable, not "
          "exhaustive.")


def _sections_of(prompt: str, *names: str) -> str:
    """Lift named sections verbatim out of SYSTEM_PROMPT.

    The two passes below must describe each section exactly as the combined prompt
    did, or the output contract quietly drifts from what the parser and the tests
    expect. Deriving them beats maintaining three copies of the same wording."""
    out = []
    for name in names:
        m = re.search(rf"^## {re.escape(name)}\n(.*?)(?=\n## |\nRules:|\Z)", prompt, re.S | re.M)
        if not m:
            raise ValueError(f"section {name!r} not found in SYSTEM_PROMPT")
        out.append(f"## {name}\n{m.group(1).strip()}")
    return "\n\n".join(out)


CONCEPT_PROMPT = (
    "You write the concept index of a rolling exam-prep synthesis for a university course, "
    "from a structured harvest of that course's lecture notes (title, one-line summary and "
    "key concepts for each lecture, in chronological order).\n\n"
    "Output ONLY markdown in this exact shape, nothing before or after:\n\n"
    + _sections_of(SYSTEM_PROMPT, "Concept index") + "\n\n" + _RULES
)

NARRATIVE_PROMPT = (
    "You write the analytical half of a rolling exam-prep synthesis for a university course, "
    "from a structured harvest of that course's lecture notes (title, one-line summary, "
    "flagged exam signals and open questions for each lecture, in chronological order). The "
    "concept index is written separately -- do not produce one.\n\n"
    "Output ONLY markdown in this exact shape, nothing before or after:\n\n"
    + _sections_of(SYSTEM_PROMPT, "How it fits together", "Likely exam questions",
                   "Revised or contradicted", "Thin ice")
    + "\n\n" + _RULES
)


@dataclasses.dataclass
class LectureHarvest:
    path: object
    date: str
    title: str
    one_line: str
    concepts: list[str]
    signals: list[str]
    open_questions: list[str]

    @property
    def link(self) -> str:
        return f"[{self.date}](lectures/{self.path.name})"


def _section(text: str, name: str) -> str:
    m = re.search(rf"## {re.escape(name)}\n(.*?)(\n## |\Z)", text, re.S)
    return m.group(1).strip() if m else ""


def _bullets(text: str) -> list[str]:
    return [l.lstrip("-* ").strip() for l in text.splitlines() if l.strip().startswith(("-", "*"))]


def harvest_lecture(path) -> LectureHarvest:
    text = path.read_text(encoding="utf-8", errors="replace")
    title_m = re.match(r"#\s*(.+?)\s*—", text)
    title = title_m.group(1).strip() if title_m else path.stem
    date_m = re.search(r"\*\*Date:\*\*\s*(\d{4}-\d{2}-\d{2})", text)
    date = date_m.group(1) if date_m else path.stem[:10]
    one_line = _section(text, "In one line")
    concepts = re.findall(r"^### (.+)$", text, re.M)
    signals = _bullets(_section(text, "⚡ Exam signals"))
    open_qs = _bullets(_section(text, "Open questions"))
    return LectureHarvest(path=path, date=date, title=title, one_line=one_line,
                           concepts=concepts, signals=signals, open_questions=open_qs)


def _harvest_text(lectures: list[LectureHarvest]) -> str:
    parts = []
    for lec in lectures:
        parts.append(
            f"### Lecture {lec.date} -- {lec.title}  (link: {lec.link})\n"
            f"One line: {lec.one_line or '(none)'}\n"
            f"Key concepts: {', '.join(lec.concepts) or '(none)'}\n"
            f"Exam signals:\n" + "\n".join(f"  - {s}" for s in lec.signals[:12]) +
            ("\nOpen questions:\n" + "\n".join(f"  - {q}" for q in lec.open_questions) if lec.open_questions else "")
        )
    return "\n\n".join(parts)


def _concept_harvest(lectures: list[LectureHarvest]) -> str:
    """Just what the concept index needs: title, one-liner, concepts, link.

    Dropping signals and open questions cuts a 6-lecture course from ~3,690 tokens
    to ~820, which is what buys the completion budget back."""
    return "\n\n".join(
        f"### Lecture {lec.date} -- {lec.title}  (link: {lec.link})\n"
        f"One line: {lec.one_line or '(none)'}\n"
        f"Key concepts: {', '.join(lec.concepts) or '(none)'}"
        for lec in lectures
    )


def _narrative_harvest(lectures: list[LectureHarvest]) -> str:
    """Just what the four prose sections need: the exam signals they rank by and
    the open questions Thin ice is built from. The concept lists are not needed
    again -- the concept index pass already used them."""
    parts = []
    for lec in lectures:
        block = (f"### Lecture {lec.date} -- {lec.title}  (link: {lec.link})\n"
                 f"One line: {lec.one_line or '(none)'}\n"
                 "Exam signals:\n" + "\n".join(f"  - {s}" for s in lec.signals[:12]))
        if lec.open_questions:
            block += "\nOpen questions:\n" + "\n".join(f"  - {q}" for q in lec.open_questions)
        parts.append(block)
    return "\n\n".join(parts)


def _split_if_too_long(body_by_section: dict, slug: str) -> tuple[str, str | None]:
    """If the assembled file exceeds MAX_LINES, move the Concept index out to
    SYNTHESIS-concepts.md and link it (SKILL.md constraint)."""
    full = "\n\n".join(body_by_section[k] for k in body_by_section)
    if len(full.splitlines()) <= MAX_LINES:
        return full, None
    concepts_doc = body_by_section["## Concept index"]
    replacement = "## Concept index\nSplit out -- see [SYNTHESIS-concepts.md](SYNTHESIS-concepts.md).\n"
    rest = dict(body_by_section)
    rest["## Concept index"] = replacement
    return "\n\n".join(rest[k] for k in rest), concepts_doc


def rebuild(paths, course, *, dry_run: bool = False, model: str | None = None) -> tuple[object, list]:
    warnings: list[str] = []
    lectures_dir = paths.lectures_dir_read(course.slug)
    note_paths = sorted(lectures_dir.glob("*.md")) if lectures_dir.exists() else []
    if not note_paths:
        raise FileNotFoundError(f"no lecture notes under {lectures_dir}")

    lectures = [harvest_lecture(p) for p in note_paths]
    lectures.sort(key=lambda l: l.date)

    if dry_run:
        return None, warnings + [
            f"dry-run: would rebuild from {len(lectures)} lecture(s), "
            "no Groq call, no file written"
        ]

    # Two passes rather than one. A 6-lecture course harvests to ~3,690 tokens, and
    # asking for a five-section synthesis beside that needs more completion budget
    # than the 8,000-token/minute bucket has left -- unservable at any pacing, which
    # is why foundations-ai-models only ever failed "rate limited".
    #
    # Splitting by SECTION and trimming each pass to the fields it actually uses
    # sends LESS input in total (~820 + ~2,860 against ~3,690 for one combined call),
    # because neither pass carries the fields the other one needs. Both halves then
    # fit with room for a full answer.
    raw = groq_client.chat(CONCEPT_PROMPT, _concept_harvest(lectures), model=model,
                           max_tokens=groq_client.TPM_CEILING)
    raw += "\n\n" + groq_client.chat(NARRATIVE_PROMPT, _narrative_harvest(lectures),
                                      model=model, max_tokens=groq_client.TPM_CEILING)

    sections = {}
    for name in ["## Concept index", "## How it fits together", "## Likely exam questions",
                 "## Revised or contradicted", "## Thin ice"]:
        m = re.search(rf"{re.escape(name)}\n(.*?)(?=\n## |\Z)", raw, re.S)
        sections[name] = f"{name}\n{m.group(1).strip()}" if m else f"{name}\n(not generated)"

    # A SYNTHESIS.md is the accumulated exam-prep value of a whole course, and this
    # rebuild is a whole-file overwrite. If the model pass produced nothing usable,
    # writing the skeleton anyway destroys that in exchange for nothing. Refuse.
    # (Measured 10 Sep 2026: a reasoning GROQ_MODEL returned empty content and this
    # replaced an 18 KB synthesis with five "(not generated)" headings.)
    missing = [n for n in sections if "(not generated)" in sections[n]]
    out_path = paths.synthesis(course.slug)
    if missing:
        names = ", ".join(n.lstrip("# ") for n in missing)
        if out_path.exists():
            raise RuntimeError(
                f"synthesis: the model pass did not return {names}; refusing to "
                f"overwrite the existing {out_path} with '(not generated)' "
                "headings. Nothing was written -- re-run to try again."
            )
        warnings.append(f"first build is missing section(s): {names}")

    exam = course.exam or "TBD"
    today = datetime.datetime.now().astimezone().date().isoformat()
    header = (f"# {course.name} — Exam Synthesis\n"
              f"*Rebuilt {today} · {len(lectures)} lecture(s) · exam {exam} · "
              f"Prof. {course.professor}*\n\n")

    body, concepts_doc = _split_if_too_long(sections, course.slug)
    full = header + body + "\n"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".md.tmp")
    tmp.write_text(full, encoding="utf-8")
    tmp.replace(out_path)


    if concepts_doc:
        cpath = paths.synthesis_concepts(course.slug)
        cpath.write_text(f"# {course.name} — Concept index\n\n{concepts_doc}\n", encoding="utf-8")
        warnings.append(f"SYNTHESIS.md exceeded {MAX_LINES} lines; concept index split to {cpath.name}")

    return out_path, warnings
