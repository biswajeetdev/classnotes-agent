#!/usr/bin/env bash
# Start a capture automatically when a class is due, and let it end itself.
#
#   class-watch.sh check     # run every 5 min from cron/launchd; starts anything due
#   class-watch.sh install   # install the launchd job
#   class-watch.sh status    # what is scheduled today, and what is recording
#   class-watch.sh coverage  # which scheduled sessions have no transcript
#
# It ASKS before recording (a dialog with Record/Skip). The mic records the room,
# so it never switches on unattended; no answer means no recording. Set
# CLASSWATCH_ASK=0 to go back to starting silently.
#
# Design note: it only automates the START. Ending is already handled by live-notes.sh
# auto-stopping after AUTO_STOP_CHUNKS silent chunks, which is deliberate --
# courses.yaml end times are demonstrably unreliable (506 ran Sat 20:00 while listed
# Sat 08:00), and a wrong end time truncates a lecture you cannot re-record. Silence is
# ground truth; the timetable is a hint.
#
# Same reason it starts EARLY (LEAD_MIN, default 6): starting early costs a few silent
# minutes that get skipped anyway. Starting late loses content permanently.
#
# If nothing is actually happening, the silence auto-stop shuts it down within ~15 min.

set -uo pipefail
# launchd runs this with a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin) that does NOT
# include Homebrew. Every tool the capture chain needs -- whisper-cli, ffmpeg,
# SwitchAudioSource -- lives in /opt/homebrew/bin, so without this the 5-min check
# logs "start", live-notes.sh dies instantly on "whisper-cli missing", and the
# session is lost silently. That is exactly how the 5 Sep 2026 10:00 506 class was
# lost. Hardcoded, not $(brew --prefix): brew is itself unreachable on that PATH.
export PATH="/opt/homebrew/bin:$PATH"
ROOT="$HOME/class-notes"
# Must exceed the launchd check interval (5 min) or the check before the bell falls
# outside the window and capture starts AT the start time -- which is how the first
# 10 minutes of the 22 Aug 501 lecture were lost. 6 guarantees one check lands early.
LEAD="${LEAD_MIN:-6}"
LOG="$ROOT/class-watch.log"

due_now() {
  python3 - "$LEAD" <<'PY'
import datetime, os, re, sys
lead=int(sys.argv[1]); now=datetime.datetime.now(); day=now.strftime('%a')
txt=open(os.path.expanduser('~/class-notes/courses.yaml')).read()
for blk in txt.split('- slug:')[1:]:
    slug=blk.split('\n')[0].strip()
    m=re.search(r'sessions:\s*(.+)', blk)
    if not m: continue
    for part in m.group(1).split('·'):
        if day not in part: continue
        t=re.search(r'(\d\d):(\d\d)\s*-\s*(\d\d):(\d\d)', part)
        if not t: continue
        start=now.replace(hour=int(t.group(1)),minute=int(t.group(2)),second=0,microsecond=0)
        delta=(start-now).total_seconds()/60
        # fire in the window [lead minutes before start, 10 min after start].
        # Emit the slot time too: a course can hold two sessions on one date, and
        # the caller needs to tell them apart to avoid skipping the second.
        if -10 <= delta <= lead:
            print(f"{slug}|{t.group(1)}{t.group(2)}"); break
PY
}

# Ask before switching the microphone on. This records the room, so starting
# unattended is not something to do silently -- there may be nobody in class and
# whatever is said near the laptop would be captured. Default is to ask.
#
#   CLASSWATCH_ASK=0   start without asking (old behaviour)
#   ASK_TIMEOUT=240    seconds to wait for an answer (default 240)
#
# No answer means DO NOT record. A missed class is recoverable from the Teams
# recording; a recording you did not consent to is not undoable.
ask_permission() {
  local slug="$1" slot="$2"
  [ "${CLASSWATCH_ASK:-1}" = "0" ] && return 0
  local pretty="${slot:0:2}:${slot:2:2}"
  local answer
  answer=$(osascript <<EOF 2>/dev/null
try
  set r to display dialog "Class due: $slug at $pretty

Start recording the room microphone?" buttons {"Skip", "Record"} default button "Record" with title "Class Notes" giving up after ${ASK_TIMEOUT:-240}
  if gave up of r then
    return "timeout"
  else
    return button returned of r
  end if
on error
  return "error"
end try
EOF
)
  case "$answer" in
    Record) return 0 ;;
    Skip)   return 1 ;;
    *)      return 2 ;;   # timeout, no GUI session, or osascript unavailable
  esac
}

# Reads cancellations.yaml. Matches a whole day ("- 2026-09-03"), one course that
# day ("- 2026-09-03 genai-comm-strategy") or one slot ("- ... 2000").
is_cancelled() {
  local date="$1" slug="$2" slot="$3" f="$ROOT/cancellations.yaml"
  [ -f "$f" ] || return 1
  sed 's/#.*//' "$f" | grep -qE "^[[:space:]]*-[[:space:]]+$date([[:space:]]+$slug([[:space:]]+$slot)?)?[[:space:]]*$"
}

case "${1:-check}" in
  check)
    TODAY=$(date +%F)
    mkdir -p "$ROOT/.live/done"
    for entry in $(due_now); do
      slug="${entry%%|*}"; slot="${entry##*|}"
      [ -d "$ROOT/$slug" ] || continue
      [ -f "$ROOT/.live/$slug.pid" ] && continue                       # already recording
      # Guard per SESSION, not per day. The old check was
      # "transcripts/<today>.txt exists -> skip", which silently dropped the
      # second of two same-day sessions (506 Sat 10:00 + Sat 20:00,
      # 505 Sat 11:00 + 17:30) because the morning class had already written
      # that file.
      done_marker="$ROOT/.live/done/$slug-$TODAY-$slot"
      [ -f "$done_marker" ] && continue
      # A cancelled class must not be recorded: 15 minutes of silence still
      # writes a transcript, which then reads as "captured" in term-coverage
      # and hides the fact that nothing was taught.
      if is_cancelled "$TODAY" "$slug" "$slot"; then
        echo "[$(date '+%F %H:%M')] skip $slug (cancelled in cancellations.yaml)" >> "$LOG"
        touch "$done_marker"
        continue
      fi
      # First session of the day keeps the plain <date>.txt name; a later one
      # gets a suffix so it cannot collide with, or be refused by, the first.
      suffix=""
      if [ -f "$ROOT/$slug/transcripts/$TODAY.txt" ]; then
        n=2
        while [ -f "$ROOT/$slug/transcripts/$TODAY.$n.txt" ]; do n=$((n+1)); done
        suffix=".$n"
      fi
      ask_permission "$slug" "$slot"; consent=$?
      case $consent in
        1) echo "[$(date '+%F %H:%M')] declined $slug (slot $slot)" >> "$LOG"
           touch "$done_marker"          # explicit no: do not ask again today
           continue ;;
        2) echo "[$(date '+%F %H:%M')] no answer for $slug (slot $slot) — not starting" >> "$LOG"
           continue ;;                   # no marker: re-ask on the next check
      esac
      echo "[$(date '+%F %H:%M')] start $slug (slot $slot${suffix:+, suffix $suffix})" >> "$LOG"
      cd "$HOME" && MIC_MODE="${MIC_MODE:-1}" SESSION_SUFFIX="$suffix" \
        nohup "$ROOT/scripts/live-notes.sh" "$slug" \
        >> "$ROOT/live-$slug.log" 2>&1 &
      child=$!
      # Mark the slot done only once the capture is actually up. Marking first meant a
      # child that died on a missing dependency looked identical to a completed class,
      # so every later check skipped it and the lecture was lost in silence.
      sleep 3
      if kill -0 "$child" 2>/dev/null; then
        touch "$done_marker"
      else
        echo "[$(date '+%F %H:%M')] FAILED to start $slug (slot $slot) — see live-$slug.log; will retry while in window" >> "$LOG"
      fi
    done
    ;;
  status)
    echo "now: $(date '+%a %H:%M')"
    echo "-- recording --"
    ls "$ROOT/.live"/*.pid 2>/dev/null | while read -r f; do
      s=$(basename "$f" .pid); p=$(cat "$f")
      echo "  $s (pid $p, $(kill -0 "$p" 2>/dev/null && echo alive || echo DEAD))"
    done || true
    ls "$ROOT/.live"/*.pid >/dev/null 2>&1 || echo "  nothing"
    echo "-- due within the next hour --"
    python3 - <<'PY'
import datetime,os,re
now=datetime.datetime.now(); day=now.strftime('%a')
txt=open(os.path.expanduser('~/class-notes/courses.yaml')).read()
found=False
for blk in txt.split('- slug:')[1:]:
    slug=blk.split('\n')[0].strip()
    m=re.search(r'sessions:\s*(.+)',blk)
    if not m: continue
    for part in m.group(1).split('·'):
        if day not in part: continue
        t=re.search(r'(\d\d):(\d\d)\s*-\s*(\d\d):(\d\d)',part)
        if not t: continue
        st=now.replace(hour=int(t.group(1)),minute=int(t.group(2)),second=0)
        d=(st-now).total_seconds()/60
        if 0 <= d <= 60:
            print(f"  {slug} in {d:.0f} min"); found=True
if not found: print("  nothing")
PY
    ;;
  coverage)
    shift
    exec "$ROOT/scripts/term-coverage.py" "$@"
    ;;
  install)
    P="$HOME/Library/LaunchAgents/com.classnotes.watch.plist"
    cat > "$P" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.classnotes.watch</string>
  <key>ProgramArguments</key>
  <array><string>$ROOT/scripts/class-watch.sh</string><string>check</string></array>
  <key>StartInterval</key><integer>300</integer>
  <key>StandardErrorPath</key><string>$ROOT/class-watch.err</string>
</dict></plist>
PLIST
    launchctl unload "$P" 2>/dev/null
    launchctl load "$P" && echo "installed — checks every 5 min"
    ;;
  *) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
