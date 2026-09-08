"""Assemble the '## ⚡ Exam signals' section deterministically.

SKILL.md / the build brief are explicit: this section must be built from
extract-signals.py's output plus the per-course signal vocabulary in
LESSONS.md -- NEVER from the Groq digest alone, because a summariser has no
notion that one sentence outweighs a paragraph (measured: it dropped the two
highest-value lines of a lecture).

The critical property that rule protects is that a real signal line cannot
be silently dropped. An instruction telling an LLM not to drop things is not
a guarantee -- the failure it exists to prevent is exactly an LLM deciding a
line is redundant. So the list of candidate lines is assembled here, in
Python, and if Groq is used at all it is only to add a short gloss; every
input line is asserted present (verbatim, normalised) in Groq's output
afterwards, and anything missing is force-appended rather than lost.
"""
from __future__ import annotations

import re

from . import groq_client, scripts_bridge

LESSONS_SIGNAL_SECTION = re.compile(
    r"## How this professor signals an exam question(.*?)(\n## |\Z)", re.S)


def _norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9ऀ-ॿ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _lessons_phrases(lessons_text: str) -> list[str]:
    """Pull quoted phrases out of LESSONS.md's signal-vocabulary section."""
    m = LESSONS_SIGNAL_SECTION.search(lessons_text or "")
    if not m:
        return []
    return re.findall(r'"([^"]{4,80})"', m.group(1))


def gather_lines(transcript_text: str, extract_signals_output: str, lessons_text: str) -> list[str]:
    lines: list[str] = []
    seen = set()

    def add(l: str):
        l = l.strip().lstrip("-").strip()
        if not l:
            return
        n = _norm(l)
        if n and n not in seen:
            seen.add(n)
            lines.append(l)

    # extract-signals.py output: "## Exam signals" bullets, then "## Repeated lines" bullets
    for raw in extract_signals_output.splitlines():
        raw = raw.strip()
        if raw.startswith("- ") and "none matched" not in raw:
            # repeated-lines entries look like "- (3x) some line" -- keep the count marker
            add(raw[2:])

    # LESSONS.md's known phrases for this professor: grep the transcript itself,
    # since extract-signals.py's generic patterns can underperform on a given
    # professor's phrasing (measured: near-zero hits on a pure walkthrough session).
    phrases = _lessons_phrases(lessons_text)
    if phrases:
        for line in transcript_text.splitlines():
            line = line.strip()
            if not line:
                continue
            low = line.lower()
            if any(p.lower() in low for p in phrases):
                add(line)

    return lines


def build_section(transcript_text: str, lessons_text: str, transcript_path,
                   use_groq: bool = True) -> tuple[str, list[str]]:
    """Returns (markdown for '## ⚡ Exam signals', warnings)."""
    warnings: list[str] = []
    raw_signals = scripts_bridge.extract_signals(transcript_path)
    lines = gather_lines(transcript_text, raw_signals, lessons_text)

    if not lines:
        warnings.append(
            "extract-signals.py and LESSONS.md phrase-grep both found nothing. "
            "LESSONS.md records this as a known failure mode on walkthrough-style "
            "sessions for some professors -- do not treat an empty section as 'no "
            "signal in this lecture' without checking by eye.")
        return "## ⚡ Exam signals\n- none extracted mechanically -- see Transcription notes.\n", warnings

    if not use_groq:
        return "## ⚡ Exam signals\n" + "\n".join(f"- {l}" for l in lines) + "\n", warnings

    # The input list is numbered only so Groq can address "line 7" etc. internally;
    # that numbering must never survive into the note. verify-notes.py (correctly)
    # flags any digit in the note body that isn't grounded in the transcript, and a
    # stray "19." list marker reads exactly like a fabricated figure to it. Told
    # once and it still echoed the input numbering back verbatim on one real run,
    # so strip it defensively rather than trust the instruction alone.
    numbered = "\n".join(f"{i}. {l}" for i, l in enumerate(lines, 1))
    system = (
        "You format exam-signal lines extracted verbatim from a lecture transcript into "
        "a markdown bullet list for student exam-prep notes. The input lines are numbered "
        "only so you can refer to them; your OUTPUT must never contain that numbering or "
        "any other digit-dot list marker -- start every output line with '- ' and nothing "
        "before it. Every input line MUST appear in your output, verbatim or near-verbatim "
        "(you may trim leading filler words, but never paraphrase away the substance). You "
        "may add a short clause after a line explaining why it's a signal (e.g. 'said twice "
        "in a row'), but never remove a line, never merge two lines into one bullet, never "
        "add a line that was not given to you, and never renumber or number your output.")
    try:
        out = groq_client.chat(system, numbered, max_tokens=1500)
    except groq_client.GroqError as e:
        warnings.append(f"Groq gloss of exam signals failed ({e}); using raw extracted lines.")
        return "## ⚡ Exam signals\n" + "\n".join(f"- {l}" for l in lines) + "\n", warnings

    cleaned_lines = []
    for raw_line in out.strip().splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        raw_line = re.sub(r"^[-*]?\s*\d+[.)]\s*", "", raw_line)  # strip echoed "19. " markers
        cleaned_lines.append(f"- {raw_line.lstrip('-* ').strip()}")
    body = "\n".join(cleaned_lines)

    out_norm = _norm(body)
    missing = [l for l in lines if _norm(l) not in out_norm]
    if missing:
        warnings.append(f"{len(missing)} signal line(s) dropped by Groq's gloss pass -- force-appended verbatim.")
        body += "\n" + "\n".join(f"- {l}" for l in missing)
    return "## ⚡ Exam signals\n" + body + "\n", warnings
