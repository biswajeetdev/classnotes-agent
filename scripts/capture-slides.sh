#!/usr/bin/env bash
# Capture the slides shown during a lecture, as deduplicated JPEG frames.
#
#   capture-slides.sh start <frames-dir> [seconds-between-frames]   # default 10
#   capture-slides.sh stop  <frames-dir>
#
# The audio pipeline hears the professor but never sees the board. MBA lectures are
# slide-driven -- formulas, frameworks, diagrams -- so those frames carry content the
# transcript simply does not contain.
#
# HOW: launches scripts/classslides/ClassSlides.app. On start, Apple's system window picker
# appears -- minimise other windows, then click the Microsoft Teams meeting window.
#
# SECURITY. No Screen Recording permission is needed or wanted (Terminal's was revoked
# 2026-09-14; macOS grants it per app, never per window, so it cannot be scoped):
#   * access comes from the system picker, per session, for ONE window you choose
#   * any window not owned by Microsoft Teams is refused and the app quits
#   * only that window's pixels are captured -- overlapping windows never appear
#   * App Sandbox: no network entitlement, file writes only under ~/class-notes
#   * hard stop (SLIDE_MAX_MINUTES, default and max 210) enforced inside the app; it also
#     quits when the Teams window closes, or if nothing is picked within 5 minutes
#   * every PICKER / START / STOP / REFUSED line goes to ~/class-notes/screen-capture-audit.log
# The old full-screen ffmpeg path was removed on purpose. Do not re-add it. If macOS asks
# to let "ffmpeg" bypass the private window picker, click Don't Allow.

set -uo pipefail

APP="$(cd "$(dirname "$0")" && pwd)/classslides/ClassSlides.app"
ROOT=$(python3 -c "import os;print(os.path.realpath(os.path.expanduser('~/class-notes')))")
AUDIT="$ROOT/screen-capture-audit.log"

case "${1:-}" in
  start)
    DIR="${2:?usage: capture-slides.sh start <frames-dir> [interval]}"
    IVL="${3:-10}"
    MAXMIN="${SLIDE_MAX_MINUTES:-210}"

    # Frames may only ever be written inside ~/class-notes (the app's sandbox enforces the
    # same boundary; this refuses before anything launches).
    ABS=$(python3 -c "import os,sys;print(os.path.realpath(os.path.expanduser(sys.argv[1])))" "$DIR")
    case "$ABS/" in
      "$ROOT"/*) ;;
      *) echo "error: refusing to capture outside ~/class-notes (asked for $ABS)" >&2; exit 1 ;;
    esac

    [ -d "$APP" ] || { echo "error: $APP missing — run scripts/classslides/build.sh" >&2; exit 1; }

    # One capture at a time. A second instance would mean something was left running.
    if OTHER=$(pgrep -x ClassSlides); then
      echo "error: ClassSlides already running (pid $OTHER) — stop it before starting another" >&2
      exit 1
    fi

    mkdir -p "$ABS"
    rm -f "$ABS/.pid"
    open -n "$APP" --args "$ABS" "$IVL" "$MAXMIN"
    for _ in $(seq 1 20); do [ -f "$ABS/.pid" ] && break; sleep 0.5; done
    [ -f "$ABS/.pid" ] || { echo "!! ClassSlides did not start — see $AUDIT" >&2; exit 1; }
    echo ">> slide capture: pick the Microsoft Teams meeting window in the system picker"
    echo ">>   (minimise this terminal first — the picker takes the window under your click)"
    echo ">> 1 frame / ${IVL}s, hard stop ${MAXMIN} min -> $ABS · audit: $AUDIT"
    ;;

  stop)
    DIR="${2:?usage: capture-slides.sh stop <frames-dir>}"
    if [ -f "$DIR/.pid" ]; then
      PID=$(cat "$DIR/.pid")
      # Only signal the pid if it is still ClassSlides -- the app may have quit on its own
      # (Teams window closed) and the pid been reused by something unrelated.
      if ps -p "$PID" -o comm= 2>/dev/null | grep -q ClassSlides; then
        kill -INT "$PID" 2>/dev/null || true
        # Wait for it to exit before deduping -- deduping while frames are still being
        # written desyncs the thumbnail list from the files and deletes the wrong ones.
        for _ in $(seq 1 20); do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
        if kill -0 "$PID" 2>/dev/null; then
          echo "!! ClassSlides ignored SIGINT — forcing" >&2; kill -9 "$PID" 2>/dev/null; sleep 1
        fi
      fi
      rm -f "$DIR/.pid"
    elif ! ls "$DIR"/*.jpg >/dev/null 2>&1; then
      echo "error: no slide capture in $DIR" >&2; exit 1
    fi
    BEFORE=$(ls "$DIR"/*.jpg 2>/dev/null | wc -l | tr -d ' ')
    if [ "$BEFORE" -eq 0 ]; then
      echo "!! no frames captured. Check the last lines of $AUDIT:" >&2
      echo "!!   REFUSED   -> a non-Teams window was picked (minimise the terminal, pick Teams)" >&2
      echo "!!   no window picked / picker cancelled -> nobody clicked Teams in time" >&2
      echo "!!   capture failed -> the error text follows on that line" >&2
      exit 1
    fi
    python3 "$(dirname "$0")/dedup-frames.py" "$DIR"
    AFTER=$(ls "$DIR"/*.jpg 2>/dev/null | wc -l | tr -d ' ')
    echo "$(date '+%Y-%m-%d %H:%M:%S')  DEDUP  dir=$DIR kept=$AFTER of $BEFORE" >> "$AUDIT"
    echo ">> slides: $AFTER kept of $BEFORE captured"
    ;;

  *) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
