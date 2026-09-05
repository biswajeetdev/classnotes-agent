#!/usr/bin/env python3
"""Generate the MBA class calendar from courses.yaml.

courses.yaml is the single source of truth for the timetable. The .ics used to be
maintained by hand, so when the official timetable was revised on 31 Aug 2026
(506 moved off Friday, 502 off Wednesday, two new slots added) courses.yaml was
updated and the calendar silently was not -- it still rang for classes that no
longer existed and stayed silent for two that did. Regenerate, never hand-edit.

    gen-calendar.py [out.ics]        # default: ~/Documents/mba-schedule-2026.ics
"""
import re, sys, os, datetime

ROOT = os.environ.get("CLASSNOTES_ROOT", os.path.expanduser("~/class-notes"))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/Documents/mba-schedule-2026.ics")

# The revised timetable took effect Mon 31 Aug 2026. Recurrences start that week so
# the calendar never claims a class happened under the old schedule.
MOODLE_BASE = os.environ.get("MOODLE_BASE", "https://moodle.example.edu/moodle")
WEEK0 = datetime.date(2026, 8, 31)
UNTIL = "20261130T235959Z"
DAYNUM = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
BYDAY = {"Mon": "MO", "Tue": "TU", "Wed": "WE", "Thu": "TH",
         "Fri": "FR", "Sat": "SA", "Sun": "SU"}


def esc(s):
    return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")


def fold(line):
    """iCalendar: max 75 octets per line, continuations start with a space."""
    b = line.encode();  out = [];  lim = 73
    while len(b) > lim:
        cut = lim
        while cut > 0 and (b[cut] & 0xC0) == 0x80:   # never split a UTF-8 char
            cut -= 1
        out.append(b[:cut]);  b = b" " + b[cut:];  lim = 74
    out.append(b)
    return b"\r\n".join(out).decode()


def courses():
    txt = open(f"{ROOT}/courses.yaml").read()
    for blk in txt.split("- slug:")[1:]:
        # Strip inline "# ..." comments -- YAML allows them and they were leaking into
        # values (a moodle_id came out with half a sentence attached to it).
        def g(k):
            m = re.search(rf"^\s*{k}:\s*(.+)$", blk, re.M)
            return re.split(r"\s+#", m.group(1))[0].strip() if m else ""
        yield {"slug": blk.split("\n")[0].strip(), "code": g("code"),
               "moodle": g("moodle_id"), "name": g("name"),
               "prof": g("professor"), "sessions": g("sessions")}


ev = []
for c in courses():
    for part in c["sessions"].split("·"):
        m = re.search(r"(\w{3})\s+(\d\d):(\d\d)-(\d\d):(\d\d)", part.strip())
        if not m:
            continue
        day, h1, m1, h2, m2 = m.group(1), *map(int, m.groups()[1:])
        d = WEEK0 + datetime.timedelta(days=DAYNUM[day])
        slot = "Morning" if h1 < 12 else "Afternoon" if h1 < 17 else "Evening"
        uid = f"{c['code'].lower().replace('-','')}-{BYDAY[day].lower()}-{h1:02d}{m1:02d}"
        t12 = lambda h, mi: f"{(h-1)%12+1}:{mi:02d} {'AM' if h<12 else 'PM'}"
        ev.append("\r\n".join(fold(x) for x in [
            "BEGIN:VEVENT",
            f"UID:{uid}@classnotes.local",
            "DTSTAMP:20260905T050000Z",
            f"DTSTART;TZID=Asia/Kolkata:{d:%Y%m%d}T{h1:02d}{m1:02d}00",
            f"DTEND;TZID=Asia/Kolkata:{d:%Y%m%d}T{h2:02d}{m2:02d}00",
            f"RRULE:FREQ=WEEKLY;BYDAY={BYDAY[day]};UNTIL={UNTIL}",
            f"SUMMARY:{esc(c['code'])} {esc(c['name'])} ({slot})",
            "LOCATION:Microsoft Teams (online)",
            f"URL:{MOODLE_BASE}/course/view.php?id={c['moodle']}",
            f"DESCRIPTION:{esc(c['name'])}\\n{esc(c['prof'])}\\n{slot} session\\, "
            f"{day} {t12(h1,m1)} - {t12(h2,m2)} IST\\nLog in with your institute "
            "Microsoft account before joining.",
            "BEGIN:VALARM", "TRIGGER:-PT15M", "ACTION:DISPLAY",
            f"DESCRIPTION:{esc(c['code'])} starts in 15 minutes",
            "END:VALARM", "END:VEVENT"]))

cal = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0",
                   "PRODID:-//classnotes-agent//Class Schedule//EN",
                   "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
                   "X-WR-CALNAME:" + os.environ.get("CALENDAR_NAME", "Classes"),
                   "X-WR-TIMEZONE:Asia/Kolkata", "BEGIN:VTIMEZONE",
                   "TZID:Asia/Kolkata", "BEGIN:STANDARD",
                   "DTSTART:19700101T000000", "TZOFFSETFROM:+0530",
                   "TZOFFSETTO:+0530", "TZNAME:IST", "END:STANDARD",
                   "END:VTIMEZONE"] + ev + ["END:VCALENDAR", ""])
open(OUT, "w", newline="").write(cal)
print(f"wrote {len(ev)} events -> {OUT}")
