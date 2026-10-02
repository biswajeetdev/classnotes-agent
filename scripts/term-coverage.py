#!/usr/bin/env python3
"""Which scheduled classes have no transcript.

check-coverage.py answers "did whisper drop speech inside this one file".
This answers the other question: across the term, which sessions were never
captured at all. That is the one that decides how much of November's revision
is reconstructible.

    term-coverage.py                 # term start .. today
    term-coverage.py --from 2026-09-01
    term-coverage.py --all           # include cancelled sessions in the listing
    term-coverage.py --no-health     # skip the pipeline-health section

Cancelled sessions are read from ~/class-notes/cancellations.yaml and are NOT
counted as gaps -- see the note in that file about not crying wolf.

Exit status: 0 when nothing is missing, 2 when something is.
"""
import argparse, datetime, glob, os, re, subprocess, sys, time
from zoneinfo import ZoneInfo

ROOT = os.environ.get("CLASSNOTES_ROOT", os.path.expanduser("~/class-notes"))
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# courses.yaml's header states all times are IST. Compare against IST explicitly
# rather than trusting the machine's local tz to happen to be set right -- see
# the 2026-09-08 bug where a class starting in ~1h was reported as already missed
# because "today" was compared as a bare date, not against the session's own end
# time in any timezone at all.
TZ = ZoneInfo("Asia/Kolkata")


def load_courses():
    """Parse slug + weekly sessions out of courses.yaml.

    Deliberately the same tolerant regex approach class-watch.sh uses, so the
    watcher and this report can never disagree about what is scheduled.
    """
    txt = open(f"{ROOT}/courses.yaml").read()
    out = []
    for blk in txt.split("- slug:")[1:]:
        slug = blk.split("\n")[0].strip()
        m = re.search(r"sessions:\s*(.+)", blk)
        if not m:
            continue
        sessions = []
        for part in m.group(1).split("·"):
            day = next((d for d in DAYS if d in part), None)
            t = re.search(r"(\d\d):(\d\d)\s*-\s*(\d\d):(\d\d)", part)
            if day and t:
                start = t.group(1) + t.group(2)
                end = t.group(3) + t.group(4)
                sessions.append((day, start, end))
        out.append((slug, sessions))
    return out


def load_cancellations():
    """-> (whole_days, {(date, slug)}, {(date, slug, slot)})"""
    days, per_course, per_slot = set(), set(), set()
    path = f"{ROOT}/cancellations.yaml"
    if not os.path.exists(path):
        return days, per_course, per_slot
    for line in open(path):
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


def captured(slug):
    """Dates that have at least one transcript, including .2/.3 same-day extras."""
    seen = set()
    for f in glob.glob(f"{ROOT}/{slug}/transcripts/*.txt"):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", os.path.basename(f))
        if m:
            seen.add(m.group(1))
    return seen


# A transcript the pipeline produced, as opposed to a derived copy (.mc0, .clean,
# .original, .combined, -digest ...). Same-day extras are .2/.3, split captures -partN.
PRIMARY = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:\.\d+|-part\d+)?\.txt$")
LOOP_RUN = 10       # >10 identical consecutive lines = whisper looped (≤7 is normal speech)
LOUD_DB = -45.0     # live-notes.sh skips chunks below this as silent; use the same line


def mean_db(wav):
    try:
        out = subprocess.run(["ffmpeg", "-nostdin", "-i", wav, "-af", "volumedetect",
                              "-f", "null", "-"], capture_output=True, text=True,
                             timeout=60).stderr
        m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", out)
        return float(m.group(1)) if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def max_run(path):
    best = run = 0
    prev = None
    for line in open(path, errors="ignore"):
        line = line.strip()
        if not line:
            continue
        run = run + 1 if line == prev else 1
        prev, best = line, max(best, run)
    return best


def pipeline_health(slug):
    """Failures that happen AFTER capture and never raise an error: a transcript no
    note was written from, audio that was recorded but never transcribed, a synthesis
    older than its newest note, and a looped transcript the note doesn't declare."""
    base = f"{ROOT}/{slug}"
    notes = {os.path.basename(n)[:10]: n for n in glob.glob(f"{base}/lectures/2026-*.md")}
    rows = []
    for t in sorted(glob.glob(f"{base}/transcripts/*.txt")):
        m = PRIMARY.match(os.path.basename(t))
        if not m:
            continue
        date = m.group(1)
        if date not in notes:
            rows.append(f"     {date}  transcript has NO NOTE  ({os.path.basename(t)})")
            continue
        run = max_run(t)
        if run > LOOP_RUN:
            note = open(notes[date], errors="ignore").read()
            tn = re.search(r"## Transcription notes(.*?)(?=\n## |\Z)", note, re.S)
            if not (tn and re.search(r"loop|repeat|artefact|artifact|hallucinat|\d+ times", tn.group(1), re.I)):
                rows.append(f"     {date}  transcript LOOPED ({run} identical lines) "
                            f"— note does not declare it")
    for d in sorted(glob.glob(f"{base}/raw/*-live")):
        if time.time() - os.path.getmtime(d) < 900:     # still being recorded
            continue
        # A <date>.mc0.txt is a full re-transcription of every kept chunk (the 12 Sep
        # loop recovery), so it covers chunks the live run never wrote a .txt for.
        if glob.glob(f"{base}/transcripts/{os.path.basename(d)[:-5]}.mc0.txt"):
            continue
        for wav in sorted(glob.glob(f"{d}/chunk-*.wav")):
            tail = f"{base}/transcripts/{os.path.basename(d)[:-5]}.tail-chunk-{wav[-8:-4]}.txt"
            if os.path.exists(wav[:-4] + ".txt") or os.path.exists(tail):
                continue
            db = mean_db(wav)
            if db is not None and db > LOUD_DB:
                rows.append(f"     {os.path.basename(d)[:10]}  UNTRANSCRIBED audio "
                            f"{os.path.basename(wav)} ({db:.0f} dB)")
    # Compare content, not mtimes: a cosmetic edit to an old note must not read as a
    # stale synthesis. Every header so far reads "*Rebuilt <date> · <n> lectures|sessions".
    syn = f"{base}/SYNTHESIS.md"
    if notes and os.path.exists(syn):
        m = re.search(r"(\d+)\s+(?:lectures?|sessions?)", open(syn).read(600))
        if m and int(m.group(1)) < len(notes):
            rows.append(f"     SYNTHESIS.md covers {m.group(1)} lectures, "
                        f"{len(notes)} notes exist — rebuild it")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="2026-08-22")
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--all", action="store_true", help="list cancelled sessions too")
    ap.add_argument("--no-health", dest="health", action="store_false",
                    help="skip the pipeline-health checks (notes, chunks, synthesis, loops)")
    a = ap.parse_args()

    start = datetime.date.fromisoformat(a.start)
    end = datetime.date.fromisoformat(a.end) if a.end else datetime.date.today()
    off_days, off_course, off_slot = load_cancellations()
    now = datetime.datetime.now(TZ)

    held = missing = cancelled = 0
    report = []
    for slug, sessions in load_courses():
        have = captured(slug)
        rows = []
        d = start
        while d <= end:
            iso, dn = d.isoformat(), DAYS[d.weekday()]
            for sday, slot, slot_end in sessions:
                if sday != dn:
                    continue
                # A slot only becomes assessable once it has actually finished --
                # otherwise a class later today (or still in progress) gets
                # reported as missed before anyone could have captured it.
                eh, em = int(slot_end[:2]), int(slot_end[2:])
                ends_at = datetime.datetime(d.year, d.month, d.day, eh, em, tzinfo=TZ)
                if ends_at > now:
                    continue
                if iso in off_days or (iso, slug) in off_course or (iso, slug, slot) in off_slot:
                    cancelled += 1
                    if a.all:
                        rows.append(f"     {iso} {dn} {slot[:2]}:{slot[2:]}  cancelled")
                    continue
                held += 1
                if iso not in have:
                    missing += 1
                    rows.append(f"     {iso} {dn} {slot[:2]}:{slot[2:]}  NO TRANSCRIPT")
            d += datetime.timedelta(days=1)
        report.append((slug, rows))

    print(f"TERM COVERAGE  {start} .. {end}\n")
    for slug, rows in report:
        gaps = [r for r in rows if "NO TRANSCRIPT" in r]
        mark = "ok" if not gaps else f"{len(gaps)} missing"
        print(f"  {slug:24s} {mark}")
        for r in rows:
            print(r)

    pct = 100 * (held - missing) // held if held else 100
    print(f"\n  captured {held - missing}/{held} sessions held ({pct}%)"
          f"{f', {cancelled} cancelled' if cancelled else ''}")
    if missing:
        print("\n  A gap is only recoverable while the Teams recording is still up.")
        print("  Either pull it and run transcribe.sh, or mark it in cancellations.yaml.")

    unhealthy = 0
    if a.health:
        print("\nPIPELINE HEALTH  (captured, but not carried through)\n")
        for slug, _ in load_courses():
            rows = pipeline_health(slug)
            unhealthy += len(rows)
            print(f"  {slug:24s} {'ok' if not rows else f'{len(rows)} issue(s)'}")
            for r in rows:
                print(r)
    sys.exit(2 if missing or unhealthy else 0)


if __name__ == "__main__":
    main()
