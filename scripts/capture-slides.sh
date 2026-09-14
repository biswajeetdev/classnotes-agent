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
# appears -- minimise other windows, then click the Microsoft Teams MEETING window.
#
# SECURITY. No Screen Recording permission is needed or wanted (macOS grants it per app,
# never per window, so it cannot be scoped):
#   * access comes from the system picker, per session, for ONE window you choose
#   * refused and quits: any non-Teams window, and Teams windows that are not a meeting
#     (main window, chats -- titles ending "| Microsoft Teams")
#   * only that window's pixels are captured -- overlapping windows never appear
#   * App Sandbox: no network, and the app can write ONLY to ~/class-notes/.frames. This
#     script -- outside the sandbox -- moves finished frames into <frames-dir>, so the app
#     can never modify scripts, notes or .env that later run or are read outside it
#   * hard stop (SLIDE_MAX_MINUTES, default and max 210) enforced inside the app; it also
#     quits when the Teams window closes, or if nothing is picked within 5 minutes
#   * audit trail: ~/class-notes/.frames/screen-capture-audit.log (linked from
#     ~/class-notes/screen-capture-audit.log)
# The old full-screen ffmpeg path was removed on purpose. Do not re-add it. If macOS asks
# to let "ffmpeg" bypass the private window picker, click Don't Allow.

set -uo pipefail

APP="$(cd "$(dirname "$0")" && pwd)/classslides/ClassSlides.app"
ROOT=$(python3 -c "import os;print(os.path.realpath(os.path.expanduser('~/class-notes')))")
FRAMES="$ROOT/.frames"
AUDIT="$FRAMES/screen-capture-audit.log"
AUDIT_LINK="$ROOT/screen-capture-audit.log"

# The sandboxed app can only write inside .frames, so the audit log lives there; the old
# path stays usable as a symlink. Idempotent.
prepare_frames() {
  mkdir -p "$FRAMES" && chmod 700 "$FRAMES"
  if [ ! -L "$AUDIT_LINK" ]; then
    if [ -f "$AUDIT_LINK" ]; then cat "$AUDIT_LINK" >> "$AUDIT" && rm -f "$AUDIT_LINK"; fi
    ln -s "$AUDIT" "$AUDIT_LINK"
  fi
  touch "$AUDIT"
}

# True only for a numeric pid whose executable is exactly ClassSlides -- a stale .pid may
# now belong to an unrelated process.
is_classslides() {
  case "${1:-}" in ''|*[!0-9]*) return 1 ;; esac
  [ "$(basename "$(ps -p "$1" -o comm= 2>/dev/null)")" = "ClassSlides" ]
}

case "${1:-}" in
  start)
    DIR="${2:?usage: capture-slides.sh start <frames-dir> [interval]}"
    IVL="${3:-10}"
    MAXMIN="${SLIDE_MAX_MINUTES:-210}"
    case "$IVL" in ''|*[!0-9]*) echo "error: interval must be whole seconds" >&2; exit 1 ;; esac
    case "$MAXMIN" in ''|*[!0-9]*) echo "error: SLIDE_MAX_MINUTES must be whole minutes" >&2; exit 1 ;; esac

    ABS=$(python3 -c "import os,sys;print(os.path.realpath(os.path.expanduser(sys.argv[1])))" "$DIR")
    case "$ABS/" in
      "$FRAMES"/*) echo "error: <frames-dir> must be a course folder, not inside .frames" >&2; exit 1 ;;
      "$ROOT"/*) ;;
      *) echo "error: refusing to capture outside ~/class-notes (asked for $ABS)" >&2; exit 1 ;;
    esac

    [ -d "$APP" ] || { echo "error: $APP missing — run scripts/classslides/build.sh" >&2; exit 1; }

    # One capture at a time. A second instance would mean something was left running.
    if OTHER=$(pgrep -x ClassSlides); then
      echo "error: ClassSlides already running (pid $OTHER) — stop it before starting another" >&2
      exit 1
    fi

    prepare_frames
    STAGE="$FRAMES/$(printf '%s' "${ABS#"$ROOT"/}" | tr '/' '_')"
    mkdir -p "$ABS" "$STAGE"
    rm -f "$STAGE/.pid" "$ABS/.pid" "$ABS/.stage"
    open -n "$APP" --args "$STAGE" "$IVL" "$MAXMIN"
    for _ in $(seq 1 20); do [ -f "$STAGE/.pid" ] && break; sleep 0.5; done
    PID=$(cat "$STAGE/.pid" 2>/dev/null || true)
    is_classslides "$PID" || { echo "!! ClassSlides did not start — see $AUDIT" >&2; exit 1; }
    echo "$PID" > "$ABS/.pid"
    echo "$STAGE" > "$ABS/.stage"
    echo ">> slide capture: pick the Microsoft Teams MEETING window in the system picker"
    echo ">>   (minimise this terminal first — the picker takes the window under your click)"
    echo ">> 1 frame / ${IVL}s, hard stop ${MAXMIN} min -> $ABS · audit: $AUDIT"
    ;;

  stop)
    DIR="${2:?usage: capture-slides.sh stop <frames-dir>}"
    # Same confinement as start: dedup-frames.py DELETES jpgs in whatever dir it is given.
    DIR=$(python3 -c "import os,sys;print(os.path.realpath(os.path.expanduser(sys.argv[1])))" "$DIR")
    case "$DIR/" in
      "$FRAMES"/*) echo "error: <frames-dir> must be a course folder, not inside .frames" >&2; exit 1 ;;
      "$ROOT"/?*) ;;
      *) echo "error: refusing to stop/dedup outside ~/class-notes (asked for $DIR)" >&2; exit 1 ;;
    esac
    prepare_frames
    if [ -f "$DIR/.pid" ]; then
      PID=$(cat "$DIR/.pid")
      if is_classslides "$PID"; then
        kill -INT "$PID" 2>/dev/null || true
        # Wait for it to exit before moving/deduping -- frames still being written would
        # desync the thumbnail list from the files and delete the wrong ones.
        for _ in $(seq 1 20); do is_classslides "$PID" || break; sleep 0.5; done
        if is_classslides "$PID"; then
          echo "!! ClassSlides ignored SIGINT — forcing" >&2; kill -9 "$PID" 2>/dev/null; sleep 1
        fi
      fi
    fi

    # Move staged frames into the course folder. Only trust a .stage inside .frames.
    STAGE=$(cat "$DIR/.stage" 2>/dev/null || true)
    case "$STAGE" in *..*) STAGE="" ;; "$FRAMES"/?*) ;; *) STAGE="" ;; esac
    if [ -n "$STAGE" ] && [ -d "$STAGE" ]; then
      RUN=$(date +%Y%m%d%H%M%S)
      for f in "$STAGE"/*.jpg; do
        [ -f "$f" ] && mv -n "$f" "$DIR/r$RUN-$(basename "$f")"
      done
      rm -f "$STAGE/.pid"
      rmdir "$STAGE" 2>/dev/null || true
    fi
    rm -f "$DIR/.pid" "$DIR/.stage"

    BEFORE=$(ls "$DIR"/*.jpg 2>/dev/null | wc -l | tr -d ' ')
    if [ "$BEFORE" -eq 0 ]; then
      echo "!! no frames in $DIR. Check the last lines of $AUDIT:" >&2
      echo "!!   REFUSED   -> a non-Teams or non-meeting window was picked (minimise the terminal)" >&2
      echo "!!   no window picked / picker cancelled -> nobody clicked the meeting window in time" >&2
      echo "!!   capture failed -> the error text follows on that line" >&2
      exit 1
    fi
    python3 "$(dirname "$0")/dedup-frames.py" "$DIR"
    AFTER=$(ls "$DIR"/*.jpg 2>/dev/null | wc -l | tr -d ' ')
    echo "$(date '+%Y-%m-%d %H:%M:%S')  DEDUP  dir=$DIR kept=$AFTER of $BEFORE" >> "$AUDIT"
    echo ">> slides: $AFTER kept of $BEFORE captured"
    ;;

  *) sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
