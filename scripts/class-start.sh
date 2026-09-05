#!/usr/bin/env bash
# One command to capture a whole live class: professor's AUDIO (BlackHole) and the
# shared SCREEN (slides), together, and tear both down cleanly when the class ends.
#
#   class-start.sh <course-slug> [YYYY-MM-DD]     # start audio + slides
#   class-start.sh stop <course-slug>             # stop early (or just let it auto-stop)
#
# Run it and leave it -- it blocks while the class runs and prints progress. It stops
# ITSELF ~15 min after the room goes silent (live-notes.sh's auto-stop), so you don't
# have to remember to come back. Stop early from another terminal with the `stop` form
# or Ctrl-C here.
#
# WHY A WRAPPER: audio and slides are two tools (live-notes.sh, capture-slides.sh).
# Audio is the MASTER -- it has silence detection, slides do not. When audio ends for
# ANY reason, this stops slides and restores your normal speakers. Slides can never be
# left recording your screen for 3.5 hours because the class ran short.
#
# ONE-TIME SETUP you must do once (persists across reboots):
#   Create a Multi-Output Device so audio reaches BlackHole *and* your speakers:
#     1. Open "Audio MIDI Setup"  (Cmd-Space -> Audio MIDI Setup)
#     2. "+" bottom-left -> Create Multi-Output Device
#     3. Tick BOTH "MacBook Air Speakers" and "BlackHole 2ch"
#     4. Set "MacBook Air Speakers" as Primary; tick Drift Correction on BlackHole
#   Do NOT rename it to contain the word "BlackHole" (live-notes.sh would refuse it).
# This script sets output to that device on start and restores your speakers on stop,
# so you never touch Audio MIDI Setup again.
#
# Also required once: Screen Recording permission for your terminal
#   System Settings > Privacy & Security > Screen Recording > enable Terminal/iTerm.

set -uo pipefail
ROOT="$HOME/class-notes"
SCRIPTS="$ROOT/scripts"
STATEDIR="$ROOT/.live"; mkdir -p "$STATEDIR"

# --- stop subcommand: self-contained, does not rely on the waiting wrapper ---------
if [ "${1:-}" = "stop" ]; then
  SLUG="${2:?usage: class-start.sh stop <course-slug>}"
  # slides first -- quick; then audio, which blocks while it transcribes its tail.
  if [ -f "$STATEDIR/$SLUG.slides" ]; then
    SD=$(cat "$STATEDIR/$SLUG.slides")
    [ -f "$SD/.pid" ] && "$SCRIPTS/capture-slides.sh" stop "$SD" || true
    rm -f "$STATEDIR/$SLUG.slides"
  fi
  "$SCRIPTS/live-notes.sh" stop "$SLUG" || true
  if [ -f "$STATEDIR/$SLUG.out" ]; then
    OUT=$(cat "$STATEDIR/$SLUG.out")
    SwitchAudioSource -s "$OUT" >/dev/null 2>&1 && echo ">> output restored to '$OUT'"
    rm -f "$STATEDIR/$SLUG.out"
  fi
  echo ">> stopped $SLUG"
  exit 0
fi

SLUG="${1:?usage: class-start.sh <course-slug> [date]  |  class-start.sh stop <slug>}"
DATE="${2:-$(date +%Y-%m-%d)}"

[ -d "$ROOT/$SLUG" ] || { echo "error: no course '$SLUG' under ~/class-notes" >&2; exit 1; }
[ -f "$STATEDIR/$SLUG.pid" ] && { echo "error: $SLUG is already recording (.live/$SLUG.pid)" >&2; exit 1; }
command -v SwitchAudioSource >/dev/null || { echo "error: SwitchAudioSource missing (brew install switchaudio-osx)" >&2; exit 1; }

# --- BlackHole present? ------------------------------------------------------------
BH=$(ffmpeg -nostdin -f avfoundation -list_devices true -i "" 2>&1 \
      | sed -n '/AVFoundation audio devices/,$p' | grep -i blackhole \
      | sed -n 's/^\[AVFoundation[^]]*\] *\[\([0-9][0-9]*\)\].*/\1/p' | head -1)
[ -n "$BH" ] || { echo "error: BlackHole not loaded. Run $SCRIPTS/reload-audio.command or reboot." >&2; exit 1; }

# --- find the Multi-Output Device (override with MULTIOUT="exact name") -------------
MO="${MULTIOUT:-}"
if [ -z "$MO" ]; then
  MO=$(SwitchAudioSource -a -t output 2>/dev/null \
       | grep -iE 'multi[- ]?output|aggregate' | head -1)
fi
if [ -z "$MO" ]; then
  echo "error: no Multi-Output Device found. Create it once (see the header of this" >&2
  echo "       script), then re-run. Tick BOTH your speakers AND BlackHole 2ch." >&2
  echo "       Output devices currently seen:" >&2
  SwitchAudioSource -a -t output 2>/dev/null | sed 's/^/         - /' >&2
  exit 1
fi

# --- switch output to it, remembering what to restore ------------------------------
PREV=$(SwitchAudioSource -c -t output 2>/dev/null)
echo "$PREV" > "$STATEDIR/$SLUG.out"
SwitchAudioSource -s "$MO" >/dev/null 2>&1 || { echo "error: could not select '$MO'" >&2; exit 1; }
echo ">> output: '$PREV' -> '$MO' (you still hear the class)"

# --- PROVE audio actually reaches BlackHole before committing 90 min to it ----------
# The whole prior failure was -91 dB silence. Creating the device in the GUI does not
# prove it routes; a real sound must show up on BlackHole's input.
( for _ in 1 2 3; do afplay /System/Library/Sounds/Glass.aiff 2>/dev/null; done ) &
APID=$!
MEAN=$(ffmpeg -nostdin -f avfoundation -i ":$BH" -t 3 -af volumedetect -f null - 2>&1 \
       | sed -n 's/.*mean_volume: \(-*[0-9.]*\) dB.*/\1/p')
kill "$APID" 2>/dev/null
if [ -z "$MEAN" ] || awk -v m="$MEAN" 'BEGIN{exit !(m < -70)}'; then
  echo "error: BlackHole heard nothing (${MEAN:-no reading} dB) through '$MO'." >&2
  echo "       Likely: the Multi-Output does not have BlackHole 2ch ticked, or the" >&2
  echo "       system volume is muted. Restoring your output and stopping." >&2
  SwitchAudioSource -s "$PREV" >/dev/null 2>&1
  rm -f "$STATEDIR/$SLUG.out"
  exit 1
fi
echo ">> audio chain verified: BlackHole hears output (${MEAN} dB)"

# --- start slides (screen), then audio (master) ------------------------------------
SLIDES="$ROOT/$SLUG/slides/$DATE"
echo "$SLIDES" > "$STATEDIR/$SLUG.slides"
"$SCRIPTS/capture-slides.sh" start "$SLIDES" "${SLIDE_INTERVAL:-10}" || echo "!! slide capture failed to start — continuing with audio only" >&2

"$SCRIPTS/live-notes.sh" "$SLUG" "$DATE" &
LNPID=$!
echo ">> class capture running: $SLUG $DATE"
echo ">> stop early with:  $0 stop $SLUG   (or Ctrl-C)"

teardown() {
  # idempotent: the `stop` subcommand may have already done some of this.
  if [ -f "$STATEDIR/$SLUG.slides" ]; then
    SD=$(cat "$STATEDIR/$SLUG.slides")
    [ -f "$SD/.pid" ] && "$SCRIPTS/capture-slides.sh" stop "$SD" || true
    rm -f "$STATEDIR/$SLUG.slides"
  fi
  if [ -f "$STATEDIR/$SLUG.out" ]; then
    OUT=$(cat "$STATEDIR/$SLUG.out")
    SwitchAudioSource -s "$OUT" >/dev/null 2>&1 && echo ">> output restored to '$OUT'"
    rm -f "$STATEDIR/$SLUG.out"
  fi
}
trap 'kill -INT $LNPID 2>/dev/null' INT TERM

wait "$LNPID"          # AUDIO IS MASTER: block until it ends (silence auto-stop or stop)
teardown
echo ">> done. Now run /classnotes in Claude Code to write the note + rebuild SYNTHESIS.md"
