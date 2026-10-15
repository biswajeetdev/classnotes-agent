#!/usr/bin/env python3
"""Check a lecture note against its transcript. Flags anything not grounded in it.

    verify-notes.py <lecture.md> <transcript.txt> [more transcripts...]

Transcripts named on the note's own **Source:** line are added automatically.

The LLM pass reconstructs garbled terms and infers structure, which is necessary -- but
it is also exactly where fabrication would enter. A wrong figure discovered in November
is worse than a gap. This checks the claims that are cheap to check mechanically:

  * numbers   -- every figure in the note must appear in the transcript
  * quotes    -- anything in "quotes" must be traceable to the audio
  * names     -- capitalised terms must resemble something that was said

It cannot judge reasoning, and it is not meant to. It catches invented specifics.
Reconstructions the note declares under "Transcription notes" are exempt.
"""
import difflib, os, re, sys, unicodedata

def norm(t):
    """Normalise both sides so notation differences are not mistaken for fabrication.

    Spoken lectures say "99 percent" and "y is equal to mx"; notes write "99%" and
    "y = mx". Without this the checker flags correct quotes, and a checker that cries
    wolf is one nobody reads -- the same failure mode as an over-eager coverage check.
    """
    t = unicodedata.normalize("NFKC", t.lower())
    t = t.replace("%", " percent ").replace("=", " is equal to ")
    t = t.replace("\u2019", "'").replace("\u2018", "'")
    t = re.sub(r"(\d)\.(\d)", r"\1 point \2", t)   # 1.3 -> "1 point 3"
    t = re.sub(r"[^a-z0-9ऀ-ॿ ]+", " ", t)
    return re.sub(r"\s+", " ", t)

def num_variants(n):
    d = n.replace(",", "")
    out = {d, n, d.replace(".", " point "), d.replace(".", " ")}
    if d.endswith(".0"): out.add(d[:-2])
    if "." in d: out.add(d.split(".")[0])
    return {re.sub(r"\s+", " ", v).strip() for v in out}

def sources(note_path, note, extra):
    """Transcripts to check against: the ones on the command line, plus every file the
    note's own **Source:** line names. A note built from a cleaned or re-run transcript
    (`2026-09-12.mc0.txt`) or from a recovered tail chunk was being checked against the
    wrong text, and every quote in it flagged -- 25 false alarms on one note."""
    paths = list(extra)
    m = re.search(r"\*\*Source:?\*\*:?\s*([^\n]+)", note)
    if m:
        course = os.path.dirname(os.path.dirname(os.path.abspath(note_path)))
        for rel in re.findall(r"transcripts/[\w.\-]+\.txt", m.group(1)):
            p = os.path.join(course, rel)
            if os.path.isfile(p) and p not in paths:
                paths.append(p)
    return paths

def section(note, title):
    m = re.search(rf"\n## {title}[^\n]*\n(.*?)(?=\n## |\Z)", note, re.S)
    return m.group(1) if m else ""

# Pipeline vocabulary, not claims about the lecture.
META = {"Groq", "LESSONS", "SYNTHESIS", "QUESTIONS", "ASSIGNMENTS", "Whisper"}

def main():
    note = open(sys.argv[1], encoding="utf-8").read()
    tr   = "\n".join(open(p, encoding="utf-8").read()
                     for p in sources(sys.argv[1], note, sys.argv[2:]))
    tnorm, tflat = norm(tr), norm(tr).replace(" ", "")
    twords = set(tnorm.split())

    # things the note itself declares as reconstructed are not fabrications
    exempt = ""
    m = re.search(r"## Transcription notes(.*?)(\n## |\Z)", note, re.S)
    if m: exempt = norm(m.group(1))

    body = re.sub(r"## Transcription notes.*?(?=\n## |\Z)", "", note, flags=re.S)
    # the header block is metadata (dates, durations, file paths) -- not claims
    body = re.sub(r"\A.*?(?=\n## )", "", body, flags=re.S)
    issues = []

    # --- numbers -------------------------------------------------------------
    # Exempt TOKENS, never whole lines: a fabricated figure must not be able to hide
    # behind a slide tag. What is removed is only the bookkeeping number itself --
    # the N in "[from slide N]", frame ids, review dates, self-test scenarios -- and
    # figures inside a 🤖 callout, which the note already declares as not-from-class.
    nbody = re.sub(r"\[[^\]\n]*\bslides?[- ][\d,–\- ]+[^\]\n]*\]", " ", body, flags=re.I)
    nbody = re.sub(r"\bslides?[- ]\d+(?:\s*[,–-]\s*\d+)*", " ", nbody, flags=re.I)
    nbody = re.sub(r"\bD\+\d+\b", " ", nbody)
    nbody = "\n".join(l for l in nbody.split("\n") if "🤖" not in l)
    for title in ("Frame coverage", "Review schedule", "Self-test"):
        sec = section(nbody, title)
        if sec: nbody = nbody.replace(sec, "")
    for raw in set(re.findall(r"(?<![\w/-])(\d[\d,]*\.?\d*)(?![\w/-])", nbody)):
        if len(raw.replace(",", "").replace(".", "")) < 2:   # skip 1-digit noise
            continue
        if any(v in tnorm or v.replace(",", "") in tflat for v in num_variants(raw)):
            continue
        if raw in exempt: continue
        ctx = next((l.strip()[:90] for l in body.split("\n") if raw in l), "")
        issues.append(("NUMBER", raw, ctx))

    # --- direct quotes -------------------------------------------------------
    # markdown emphasis markers otherwise get swallowed into "quotes"
    qbody = re.sub(r"[*_`]", "", body)
    for q in re.findall(r'[""]([^""\n]{12,160})[""]', qbody):
        qn = norm(q)
        words = qn.split()
        # allow paraphrase-level drift; require a solid run of it to be present
        if len(words) < 4: continue          # too short to verify meaningfully
        for start in range(0, max(1, len(words) - 4)):
            probe = " ".join(words[start:start + 5])
            if probe in tnorm: break
        else:
            if difflib.SequenceMatcher(None, qn, tnorm).find_longest_match(
                    0, len(qn), 0, len(tnorm)).size >= max(20, len(qn) * 0.55):
                continue
            issues.append(("QUOTE", q[:70] + ("..." if len(q) > 70 else ""), ""))
        continue

    # --- capitalised names ---------------------------------------------------
    # Ordinary English words get capitalised at the start of headings and bullets, and
    # are not claims about the world. Only genuine proper nouns are worth checking.
    english = set()
    for dic in ("/usr/share/dict/words",):
        try:
            english = {w.strip().lower() for w in open(dic, encoding="utf-8", errors="ignore")}
        except OSError:
            pass
    stop = {"Date","Source","Course","Professor","Given","Due","Weight","Status"} | META
    # A capitalised word at the start of a line, heading, bullet or table cell is
    # just sentence case, not a claim. Only mid-sentence capitals are proper nouns.
    #
    # \s spans newlines, so this used to read the first word of a line as
    # mid-sentence whenever the line above happened to end in a lowercase letter
    # or a ")" -- which is every heading. That flagged the ordinary verbs opening
    # "Maps ordered categories..." and "Centers each feature..." as unverified
    # names. Skip a capital that opens a block (first line, or the line after a
    # heading or a blank line); a capital opening a wrapped continuation line is
    # still genuinely mid-sentence and is still checked.
    line_start = {0}
    for m in re.finditer(r"\n", body):
        line_start.add(m.end())

    def opens_a_block(pos):
        if pos not in line_start:
            return False
        prev_end = body.rfind("\n", 0, pos - 1)
        prev = body[prev_end + 1:pos - 1] if pos else ""
        return not prev.strip() or prev.lstrip().startswith("#")

    midsentence = {
        m.group(1)
        for m in re.finditer(r"[a-z,;)]\s+([A-Z][a-zA-Z]{3,})\b", body)
        if not opens_a_block(m.start(1))
    }
    for name in midsentence:
        if name in stop: continue
        n = norm(name).strip()
        if n in english and not name.isupper(): continue
        if n in twords or n in tflat: continue
        if n in exempt: continue
        best = max((difflib.SequenceMatcher(None, n, w).ratio() for w in twords), default=0)
        if best < 0.72:
            issues.append(("NAME", name, f"closest transcript match {best:.0%}"))

    if not issues:
        print("  ✓ every figure, quote and name in the note is grounded in the transcript")
        return 0
    order = {"QUOTE": 0, "NUMBER": 1, "NAME": 2}
    issues.sort(key=lambda x: order[x[0]])
    print(f"  {len(issues)} item(s) not found in the transcript — verify or remove:")
    for kind, item, ctx in issues:
        print(f"    [{kind:6}] {item}" + (f"   ({ctx})" if ctx else ""))
    return 1

if __name__ == "__main__":
    sys.exit(main())
