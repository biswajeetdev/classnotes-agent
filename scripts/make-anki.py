#!/usr/bin/env python3
"""Turn a course SYNTHESIS.md into an Anki deck.

    make-anki.py <course-dir-or-SYNTHESIS.md> [out.tsv]

Writes tab-separated cards that Anki imports natively (File > Import, "Fields
separated by: Tab", and tick "Allow HTML in fields"). No dependencies, and no
.apkg builder: a TSV is inspectable in a text editor, diffable in git, and
re-importable over the same deck without duplicating cards, which an .apkg is not.

Two card types come out of a synthesis, because it already contains both:

  concept  - from the "Concept index" table. Front is the term, back is the
             one-line gloss plus which lecture it came from.
  exam     - from "Likely exam questions". Front is the question, back is the
             guidance underneath it.

Cards carry the course as a tag and the type as a second tag, so one deck can
hold every course and still be filtered down at revision time.
"""
import os
import re
import sys
from pathlib import Path

LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")     # [26 Aug](lectures/...) -> 26 Aug
BOLD = re.compile(r"\*\*(.+?)\*\*")
ITAL = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
# Notes number exam questions two ways, and both are in use across the courses:
#   **1. Question text**   (number inside the bold)
#   1. **Question text**   (number outside it)
# Matching only the first silently yields zero exam cards for the other courses,
# which looks exactly like a synthesis that has no questions in it.
QNUM = (re.compile(r"^\*\*(\d+)\.\s*(.+?)\*\*\s*(.*)$"),
        re.compile(r"^(\d+)\.\s*\*\*(.+?)\*\*\s*(.*)$"))


def match_question(line: str):
    for pat in QNUM:
        m = pat.match(line)
        if m:
            return m
    return None


def to_html(md: str) -> str:
    """Markdown fragment -> the small subset of HTML Anki renders."""
    s = LINK.sub(r"\1", md)
    s = BOLD.sub(r"<b>\1</b>", s)
    s = ITAL.sub(r"<i>\1</i>", s)
    s = s.replace("\t", " ").strip()
    return re.sub(r"\n+", "<br>", s)


def sections(text: str) -> "dict[str, str]":
    """Split on level-2 headings, keeping each body intact."""
    out, name, buf = {}, None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if name:
                out[name] = "\n".join(buf)
            name, buf = line[3:].strip().lower(), []
        elif name:
            buf.append(line)
    if name:
        out[name] = "\n".join(buf)
    return out


def concept_cards(body: str) -> "list[tuple[str, str]]":
    """Rows of the concept-index table. Skips the header and the |---| rule."""
    cards = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|- :"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        term = to_html(cells[0])
        if not term or term.lower() in ("concept", "term"):
            continue
        back = to_html(cells[1])
        if len(cells) > 2 and cells[2].strip():
            back += f"<br><br><i>{to_html(cells[2])}</i>"
        if back:
            cards.append((term, back))
    return cards


def exam_cards(body: str) -> "list[tuple[str, str]]":
    """Numbered **N. Question** headings, each followed by its guidance."""
    cards, q, buf = [], None, []
    for line in body.splitlines():
        m = match_question(line.strip())
        if m:
            if q:
                cards.append((q, "\n".join(buf).strip()))
            q, buf = m.group(2).strip(), ([m.group(3)] if m.group(3) else [])
        elif q is not None:
            buf.append(line)
    if q:
        cards.append((q, "\n".join(buf).strip()))
    return [(to_html(a), to_html(b)) for a, b in cards if to_html(b)]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    if src.is_dir():
        src = src / "SYNTHESIS.md"
    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr)
        return 1

    course = src.parent.name
    text = src.read_text(encoding="utf-8")
    secs = sections(text)

    rows = []
    for title, body in secs.items():
        if "concept index" in title:
            rows += [(f, b, f"{course} concept") for f, b in concept_cards(body)]
        elif "exam question" in title:
            rows += [(f, b, f"{course} exam") for f, b in exam_cards(body)]

    if not rows:
        print(f"error: no cards found in {src} — expected a 'Concept index' table "
              "or a 'Likely exam questions' section", file=sys.stderr)
        return 1

    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.parent / f"{course}-anki.tsv"
    with dst.open("w", encoding="utf-8") as fh:
        # Anki reads these directives, so the import dialog needs no fiddling.
        fh.write("#separator:tab\n#html:true\n#tags column:3\n")
        for front, back, tags in rows:
            fh.write(f"{front}\t{back}\t{tags}\n")

    concepts = sum(1 for r in rows if r[2].endswith("concept"))
    print(f"  wrote {dst} — {len(rows)} cards "
          f"({concepts} concept, {len(rows) - concepts} exam), tagged '{course}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
