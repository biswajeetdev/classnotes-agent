"""Write ~/class-notes/<course>/lectures/<date>-<topic>.md from a kept transcript.

Division of labour, deliberately:
  - Groq drafts the prose sections (In one line, Key concepts, Formulas/frameworks,
    Worked examples, Q&A, Open questions, Admin) from the digest + LESSONS.md.
  - Python assembles '## ⚡ Exam signals' from extract-signals.py + LESSONS.md
    phrase-grep (see signals.py) -- never from the digest, and never something
    an LLM call could silently drop a line from.
  - verify-notes.py gates the result against the FULL transcript. A flagged
    note is written to disk (so it can be inspected/fixed) but reported and
    returned as unverified -- never silently treated as published. No
    auto-repair: an LLM asked to fix a flagged quote will usually just drop
    the quotation marks, which is the dodge the spec explicitly forbids.
"""
from __future__ import annotations

import dataclasses
import re

from . import density, groq_client, scripts_bridge, signals

SECTION_ORDER = [
    "In one line", "Key concepts", "Formulas / frameworks", "Worked examples",
    "Open questions", "Admin", "Transcription notes",
]

NOTE_SYSTEM_PROMPT = """You write university lecture notes for exam prep from a lecture digest.

Output format -- plain markdown, in EXACTLY this shape, nothing before or after:

TITLE: <short topic phrase, 3-8 words, no course name, no date>

## In one line
<one sentence: what this lecture was actually about>

## Key concepts
### <Concept>
<Plain-English definition. Structure, never a transcript dump.>
(repeat ### per concept)

## Formulas / frameworks
<Written out properly, what each part means, when it applies. Omit this heading
entirely if the lecture had none.>

## Worked examples
<The examples actually walked through, with the real numbers/names from the
digest. Omit entirely if none.>

## Open questions
- <asked and not answered, or genuinely unclear>

## Admin
<Deadlines, assignments, next-class announcements. Omit the heading if none.>

## Transcription notes
<Anything you are unsure about or had to guess at from the digest. Use
"[unclear: your best guess]" rather than inventing content -- a wrong note found
before an exam is worse than a gap. Omit the heading if nothing applies.>

Rules:
- Base every claim ONLY on the digest and lessons text given to you. Never add a
  fact, number or name that isn't in them.
- No speaker diarization is available. Never attribute a line to a named student --
  write Q&A as "a student asked ... the professor answered ...".
- Do NOT include a '## ⚡ Exam signals' section -- that is assembled separately.
- Numbers and quotes from the digest should be reproduced exactly as given, not
  rounded or paraphrased -- they will be checked against the source transcript.
"""


@dataclasses.dataclass
class NoteResult:
    path: object
    verified: bool
    verify_output: str
    warnings: list
    topic_slug: str
    title: str


def _slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "lecture"


def _parse_title_and_body(raw: str) -> tuple[str, str]:
    lines = raw.strip().splitlines()
    title = "Lecture"
    if lines and lines[0].upper().startswith("TITLE:"):
        title = lines[0].split(":", 1)[1].strip()
        lines = lines[1:]
    return title, "\n".join(lines).strip() + "\n"


def write_note(paths, course, date: str, *, use_groq_signals: bool = True,
                digest_force: bool = False, dry_run: bool = False,
                model: str | None = None) -> NoteResult:
    transcript_path = paths.transcript(course.slug, date)
    if not transcript_path.exists():
        raise FileNotFoundError(f"no transcript at {transcript_path} -- run transcription first")
    transcript_text = transcript_path.read_text(encoding="utf-8", errors="replace")

    lessons_path = paths.lessons(course.slug)
    lessons_text = lessons_path.read_text(encoding="utf-8") if lessons_path.exists() else ""

    warnings: list[str] = []

    # digest: reuse the cached one unless forced -- avoids re-spending Groq quota
    digest_path = paths.digest(course.slug, date)
    if digest_path.exists() and not digest_force:
        digest_text = digest_path.read_text(encoding="utf-8")
        warnings.append(f"reused cached digest at {digest_path}")
    else:
        digest_path, digest_log = scripts_bridge.digest(transcript_path, digest_path)
        digest_text = digest_path.read_text(encoding="utf-8")

    if dry_run:
        return NoteResult(path=None, verified=False, verify_output="(dry run)",
                           warnings=warnings + ["dry-run: no Groq call, no file written"],
                           topic_slug="(dry-run)", title="(dry-run)")

    sig_md, sig_warnings = signals.build_section(transcript_text, lessons_text, transcript_path,
                                                  use_groq=use_groq_signals)
    warnings.extend(sig_warnings)

    user_content = (
        f"COURSE: {course.name} ({course.code}), professor {course.professor}\n\n"
        f"LESSONS FROM PRIOR SESSIONS (ASR corrections, this professor's patterns):\n"
        f"{lessons_text or '(none yet)'}\n\n"
        f"LECTURE DIGEST (lossy summary of the transcript -- structure and navigation "
        f"only; do not treat as more precise than it is):\n{digest_text}\n"
    )
    raw = groq_client.chat(NOTE_SYSTEM_PROMPT, user_content, model=model,
                            max_tokens=3000)
    title, body = _parse_title_and_body(raw)
    topic_slug = _slugify(title)

    # splice the Python-assembled ⚡ section in after Worked examples / before Open questions
    if "## Open questions" in body:
        body = body.replace("## Open questions", sig_md + "\n## Open questions", 1)
    else:
        body = body.rstrip() + "\n\n" + sig_md

    if warnings:
        note_block = "## Transcription notes\n" if "## Transcription notes" not in body else ""
        auto_notes = "\n".join(f"- [pipeline] {w}" for w in warnings)
        if "## Transcription notes" in body:
            body = body.replace("## Transcription notes\n", "## Transcription notes\n" + auto_notes + "\n", 1)
        else:
            body = body.rstrip() + f"\n\n{note_block}{auto_notes}\n"

    header = (f"# {title} — {course.name}\n"
              f"**Date:** {date} · **Professor:** {course.professor} · "
              f"**Source:** transcripts/{date}.txt\n\n")
    full = header + body

    out_path = paths.lecture_note(course.slug, date, topic_slug)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(full, encoding="utf-8")

    clean, verify_out = scripts_bridge.verify_note(out_path, transcript_path)
    return NoteResult(path=out_path, verified=clean, verify_output=verify_out,
                       warnings=warnings, topic_slug=topic_slug, title=title)


def density_check(paths, course, date: str, lang: str) -> density.DensityResult:
    live_dir = paths.raw_live_dir(course.slug, date)
    return density.check(live_dir, lang)


def append_admin_and_questions(paths, course, date: str, note_result: NoteResult):
    """Append this lecture's Open questions / Admin bullets to the term-spanning
    QUESTIONS.md / ASSIGNMENTS.md files. Append-only, per SKILL.md -- and guarded
    against a double-append if `note` is re-run for a date already recorded."""
    note_text = note_result.path.read_text(encoding="utf-8")
    heading_marker = f"## {date}"

    def section(name):
        m = re.search(rf"## {re.escape(name)}\n(.*?)(\n## |\Z)", note_text, re.S)
        return m.group(1).strip() if m else ""

    open_qs = section("Open questions")
    if open_qs:
        qpath = paths.questions(course.slug)
        existing = qpath.read_text(encoding="utf-8") if qpath.exists() else \
            f"# Open questions — {course.code} {course.name}\n"
        if heading_marker not in existing:
            rel = f"lectures/{note_result.path.name}"
            block = f"\n{heading_marker} · [{note_result.title}]({rel})\n\n{open_qs}\n"
            qpath.parent.mkdir(parents=True, exist_ok=True)
            qpath.write_text(existing.rstrip("\n") + "\n" + block, encoding="utf-8")

    admin = section("Admin")
    if admin:
        apath = paths.assignments(course.slug)
        existing = apath.read_text(encoding="utf-8") if apath.exists() else \
            f"# Assignments — {course.code} {course.name}\n"
        if heading_marker not in existing:
            block = f"\n{heading_marker} admin note\n\n{admin}\n"
            apath.parent.mkdir(parents=True, exist_ok=True)
            apath.write_text(existing.rstrip("\n") + "\n" + block, encoding="utf-8")
