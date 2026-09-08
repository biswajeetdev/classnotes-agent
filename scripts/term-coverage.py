#!/usr/bin/env python3
"""Which scheduled classes have no transcript.

check-coverage.py answers "did whisper drop speech inside this one file".
This answers the other question: across the term, which sessions were never
captured at all. That is the one that decides how much of November's revision
is reconstructible.

    term-coverage.py                 # term start .. today
    term-coverage.py --from 2026-09-01
    term-coverage.py --all           # include cancelled sessions in the listing

Cancelled sessions are read from ~/class-notes/cancellations.yaml and are NOT
counted as gaps -- see the note in that file about not crying wolf.

Exit status: 0 when nothing is missing, 2 when something is.
"""
import argparse, datetime, glob, os, re, sys
from zoneinfo import ZoneInfo

ROOT = os.path.expanduser("~/class-notes")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="2026-08-22")
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--all", action="store_true", help="list cancelled sessions too")
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
    sys.exit(2 if missing else 0)


if __name__ == "__main__":
    main()
