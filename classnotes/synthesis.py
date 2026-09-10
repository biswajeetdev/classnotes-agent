"""Rebuild <course>/SYNTHESIS.md from every lecture note in the course.

Never appended -- always regenerated from scratch (SKILL.md: "Appending gives
you 100 files and no study material"). Harvesting is deterministic Python
(regex over the already-structured lecture notes); only the connective prose
-- "How it fits together", ranked exam questions, "Revised or contradicted"
-- goes through Groq, because that's genuine cross-lecture judgement, not
something a template can produce.

Feeding Groq the harvested per-lecture digest (title/one-liner/concepts/⚡
signals/open questions) rather than the full notes keeps this well under the
free-tier TPM cap even as a course accumulates many lectures, and it's the
right level of detail anyway -- the synthesis argument is built from what
each lecture judged important, not from re-reading every paragraph.
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

    harvest_text = _harvest_text(lectures)
    raw = groq_client.chat(SYSTEM_PROMPT, harvest_text, model=model, max_tokens=3000)

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
