#!/usr/bin/env bash
# Capture + transcribe a whole queue of lectures unattended.
#
#   run-queue.sh ~/class-notes/queue.tsv
#
# SharePoint blocks downloading the recordings, so the only way to get audio is to
# play them and capture it. This drives that end to end: for each row it opens the
# Stream URL in Chrome, records system audio via BlackHole, trims trailing silence,
# transcribes, and checks coverage.
#
# REQUIREMENTS: blackhole-2ch installed AND rebooted. Nothing else may play sound.
# Slide capture also needs Screen Recording permission for your terminal, and records
# the WHOLE screen — keep the lecture full-screen. Set SLIDES_CAPTURE=0 to skip it.
# While this runs the Mac's output is BlackHole, so you will hear NOTHING. Runs in
# real time -- a 2h lecture takes 2h to capture plus ~45 min to transcribe.
#
# queue.tsv is tab-separated, one lecture per row, '#' comments allowed:
#   <course-slug><TAB><YYYY-MM-DD><TAB><minutes><TAB><stream-url>
# Set <minutes> generously; trailing silence is trimmed before transcription.

set -uo pipefail

QUEUE="${1:-$HOME/class-notes/queue.tsv}"
ROOT="$HOME/class-notes"
LOG="$ROOT/queue.log"

[ -f "$QUEUE" ] || { echo "error: no queue file at $QUEUE" >&2; exit 1; }
command -v SwitchAudioSource >/dev/null || { echo "error: switchaudio-osx missing" >&2; exit 1; }
if ! SwitchAudioSource -a -t output | grep -qi blackhole; then
  echo "error: BlackHole not present. Install it and REBOOT:" >&2
  echo "       brew install --cask blackhole-2ch" >&2
  exit 1
fi

say_log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

# The turbo model is ~1.5 GB resident. On a small-RAM Mac, transcribing while the
# next lecture captures pushes the machine into memory compression -- which is the
# lag, and worse, a starved capture can drop audio it can never get back. So the
# overlap optimisation is only safe when there is headroom for it.
RAM_GB=$(sysctl -n hw.memsize | awk '{printf "%.0f", $1/1073741824}')
if [ "${OVERLAP:-auto}" = "auto" ]; then
  if [ "$RAM_GB" -le 8 ]; then OVERLAP=0; else OVERLAP=1; fi
fi
if [ "$OVERLAP" = "0" ]; then
  say_log "NOTE  ${RAM_GB}GB RAM — transcribing serially, not overlapped (safer on this machine)"
  say_log "NOTE  slide capture also disabled by default here; set SLIDES_CAPTURE=1 to force"
  : "${SLIDES_CAPTURE:=0}"
  : "${TRANSCRIBE_THREADS:=0}"     # 0 = let transcribe.sh use its full-thread default
fi
# A 10-hour unattended run dies silently if the Mac sleeps: playback stops, capture
# records nothing, and every remaining lecture is written as a silent failure.
caffeinate -dimsu -w $$ &
say_log "NOTE  sleep inhibited for the duration of this run"
say_log "=== queue start: $(grep -vc '^#' "$QUEUE" 2>/dev/null) lecture(s) ==="

FAILED=0
JOBS=""
CONSEC_SILENT=0
while IFS=$'\t' read -r SLUG DATE MINS URL; do
  case "${SLUG:-}" in ''|\#*) continue ;; esac
  [ -n "${URL:-}" ] || { say_log "SKIP  malformed row: $SLUG"; continue; }

  TXT="$ROOT/$SLUG/transcripts/$DATE.txt"
  if [ -f "$TXT" ]; then say_log "SKIP  $SLUG $DATE — transcript already exists"; continue; fi

  mkdir -p "$ROOT/$SLUG"/{raw,transcripts,lectures,slides}
  RAW="$ROOT/$SLUG/raw/$DATE-capture"
  SLIDES="$ROOT/$SLUG/slides/$DATE"
  say_log "PLAY  $SLUG $DATE — capturing ${MINS} min"

  open -a "Google Chrome" "$URL" >/dev/null 2>&1
  sleep 12                                   # let the player load and start

  # Playback speed is the only lever on capture time -- capture is real time by nature.
  # Size the wait from the rate actually IN EFFECT, never the requested one: if setting
  # it silently failed we would wait 2/3 of the lecture and truncate it.
  RATE=$("$ROOT/scripts/set-playback-rate.sh" "${PLAYBACK_RATE:-1.5}" 2>/dev/null | tail -1)
  case "$RATE" in ''|*[!0-9.]*) RATE=1.0 ;; esac
  WAIT=$(python3 -c "import math;print(int(math.ceil($MINS*60/$RATE))+60)")
  say_log "RATE  $SLUG $DATE — playing at ${RATE}x, waiting $((WAIT/60)) min"
  "$ROOT/scripts/capture.sh" start "$RAW" >>"$LOG" 2>&1 || { say_log "FAIL  capture start"; FAILED=1; continue; }
  # Slides carry formulas and frameworks the transcript never states. Optional:
  # set SLIDES_CAPTURE=0 to skip, e.g. if Screen Recording permission is not granted.
  if [ "${SLIDES_CAPTURE:-1}" = "1" ]; then
    "$ROOT/scripts/capture-slides.sh" start "$SLIDES" "${SLIDE_INTERVAL:-10}" >>"$LOG" 2>&1 \
      || say_log "WARN  slide capture failed to start — continuing audio-only"
  fi
  sleep "$WAIT"
  "$ROOT/scripts/capture.sh" stop >>"$LOG" 2>&1
  if [ "${SLIDES_CAPTURE:-1}" = "1" ] && [ -f "$SLIDES/.pid" ]; then
    "$ROOT/scripts/capture-slides.sh" stop "$SLIDES" >>"$LOG" 2>&1 || true
    NSLIDES=$(ls "$SLIDES"/slide-*.jpg 2>/dev/null | wc -l | tr -d ' ')
    say_log "SLIDE $SLUG $DATE — $NSLIDES distinct slides kept"
  fi

  if [ ! -f "$RAW.wav" ]; then say_log "FAIL  $SLUG $DATE — no audio captured"; FAILED=1; continue; fi

  MEAN=$(ffmpeg -nostdin -i "$RAW.wav" -af volumedetect -f null - 2>&1 \
         | sed -n 's/.*mean_volume: \(-*[0-9.]*\) dB.*/\1/p')
  case "${MEAN:-0}" in
    -9[0-9]*|-inf|"")
      say_log "FAIL  $SLUG $DATE — SILENT (playback never started / wrong output)"
      FAILED=1
      CONSEC_SILENT=$((CONSEC_SILENT+1))
      # Unattended, the expensive mistake is grinding through 10 hours of silence
      # because a SharePoint session expired or audio routing broke. Two in a row
      # means it is systemic, not one bad lecture -- stop and leave the rest to retry.
      if [ "$CONSEC_SILENT" -ge 2 ]; then
        say_log "ABORT two silent captures in a row — something is systemically wrong"
        say_log "ABORT check: Chrome still signed into SharePoint? mic permission on?"
        say_log "ABORT remaining lectures untouched; just re-run when fixed."
        exit 1
      fi
      continue ;;
  esac
  CONSEC_SILENT=0

  # drop trailing silence so we don't transcribe an hour of nothing
  ffmpeg -nostdin -loglevel error -y -i "$RAW.wav" \
    -af "areverse,silenceremove=start_periods=1:start_silence=2:start_threshold=-45dB,areverse" \
    "$RAW-trim.wav" && mv "$RAW-trim.wav" "$RAW.wav"

  # Transcribe in the background so it overlaps the NEXT lecture's capture, which is
  # pure waiting. Threads are held back from the full core count so the concurrent
  # audio capture is not starved -- a glitched capture is far more expensive than a
  # slower transcription, because it cannot be redone without replaying the lecture.
  if [ "$OVERLAP" = "1" ]; then
    say_log "TXT   $SLUG $DATE — transcribing in background (mean ${MEAN} dB)"
    (
      if WHISPER_THREADS="${TRANSCRIBE_THREADS:-4}" \
         "$ROOT/scripts/transcribe.sh" "$RAW.wav" "$ROOT/$SLUG/transcripts/$DATE" >>"$LOG" 2>&1
      then say_log "OK    $SLUG $DATE — $(wc -w <"$TXT" | tr -d ' ') words"
      else say_log "FAIL  $SLUG $DATE — transcription failed"; fi
    ) &
    JOBS="$JOBS $!"
  else
    say_log "TXT   $SLUG $DATE — transcribing (mean ${MEAN} dB)"
    if "$ROOT/scripts/transcribe.sh" "$RAW.wav" "$ROOT/$SLUG/transcripts/$DATE" >>"$LOG" 2>&1
    then say_log "OK    $SLUG $DATE — $(wc -w <"$TXT" | tr -d ' ') words"
    else say_log "FAIL  $SLUG $DATE — transcription failed"; FAILED=1; fi
    # free the captured audio's page cache pressure before the next capture starts
    sleep 5
  fi
done < "$QUEUE"

say_log "all captures done — waiting on background transcriptions"
for j in $JOBS; do wait "$j" || FAILED=1; done

say_log "=== queue done ==="
say_log "Now run /classnotes in Claude Code to turn the transcripts into notes + SYNTHESIS.md"
exit $FAILED
