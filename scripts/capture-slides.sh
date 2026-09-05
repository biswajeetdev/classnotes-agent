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
# REQUIRES: Screen Recording permission for your terminal
#   System Settings > Privacy & Security > Screen Recording > enable Terminal/iTerm
#
# PRIVACY / SCOPE. Screen Recording is a broad permission, so this script constrains
# itself to the one job it exists for:
#   * frames may only be written under ~/class-notes -- it refuses any other path
#   * a hard stop (SLIDE_MAX_MINUTES, default 210) is enforced by ffmpeg itself, so a
#     crashed caller cannot leave the screen recording indefinitely
#   * every start/stop is appended to ~/class-notes/screen-capture-audit.log
#   * nothing is sent anywhere -- no script in this pipeline makes a network call;
#     transcription is local whisper.cpp, not an API
# It still records the WHOLE screen while running: keep the lecture full-screen and
# nothing private visible. Frames stay on disk until you delete them.

set -uo pipefail

case "${1:-}" in
  start)
    DIR="${2:?usage: capture-slides.sh start <frames-dir> [interval]}"
    IVL="${3:-10}"

    # --- guardrails ------------------------------------------------------------
    # Screen Recording is a broad permission. These make it hard for this script to
    # be used, or to misfire, as anything other than lecture-slide capture.

    # 1. Frames may only ever be written inside ~/class-notes. Anything else is not
    #    note-taking, so refuse rather than record.
    ABS=$(python3 -c "import os,sys;print(os.path.realpath(os.path.expanduser(sys.argv[1])))" "$DIR")
    ROOT=$(python3 -c "import os;print(os.path.realpath(os.path.expanduser('~/class-notes')))")
    case "$ABS/" in
      "$ROOT"/*) ;;
      *) echo "error: refusing to capture outside ~/class-notes (asked for $ABS)" >&2; exit 1 ;;
    esac

    # 2. Hard stop. Nothing here needs more than one lecture's worth, so a runaway
    #    or forgotten session cannot sit recording the screen all day.
    MAXMIN="${SLIDE_MAX_MINUTES:-210}"

    mkdir -p "$DIR"
    AUDIT="$ROOT/screen-capture-audit.log"

    IDX=$(ffmpeg -nostdin -f avfoundation -list_devices true -i "" 2>&1 \
          | sed -n '/AVFoundation video devices/,/audio devices/p' \
          | grep -i 'capture screen' \
          | sed -n 's/.*\[\([0-9][0-9]*\)\] *Capture screen.*/\1/p' | head -1)
    [ -n "$IDX" ] || { echo "error: no screen capture device found" >&2; exit 1; }

    # -r 1/N gives one frame every N seconds. 1024px wide is plenty for slide text.
    # -t enforces the hard stop inside ffmpeg itself, so it holds even if the
    # caller crashes and never calls stop.
    # avfoundation screen input hands over a pixel format the mjpeg encoder refuses
    # ("Non full-range YUV is non-standard" -> ff_frame_thread_encoder_init failed,
    # zero frames written). Pin the input format and convert to yuvj420p for JPEG.
    # Fully detach. Left attached, this ffmpeg keeps the CALLER's shell alive until
    # its own -t expires -- run-queue.sh does start/sleep/stop in one shell, so an
    # attached child hangs the whole queue rather than the capture.
    nohup ffmpeg -nostdin -loglevel error -y -f avfoundation -pixel_format uyvy422 \
      -framerate 30 -i "$IDX:none" \
      -t "$(( MAXMIN * 60 ))" \
      -vf "fps=1/$IVL,scale=1024:-2,format=yuvj420p" -q:v 4 "$DIR/%05d.jpg" \
      >"$DIR/.ffmpeg.log" 2>&1 </dev/null &
    echo $! > "$DIR/.pid"
    disown 2>/dev/null || true
    # 3. Every session is logged, so screen capture is never silent or deniable.
    echo "$(date '+%Y-%m-%d %H:%M:%S')  START  dir=$DIR interval=${IVL}s max=${MAXMIN}min pid=$!" >> "$AUDIT"
    echo ">> slide capture started (1 frame / ${IVL}s, hard stop ${MAXMIN} min) -> $DIR"
    echo ">> logged to $AUDIT"
    ;;

  stop)
    DIR="${2:?usage: capture-slides.sh stop <frames-dir>}"
    [ -f "$DIR/.pid" ] || { echo "error: no slide capture running in $DIR" >&2; exit 1; }
    PID=$(cat "$DIR/.pid")
    kill -INT "$PID" 2>/dev/null || true
    # Wait for it to actually exit before deduping -- deduping while frames are still
    # being written desyncs the thumbnail list from the files and deletes the wrong ones.
    for _ in $(seq 1 20); do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
    if kill -0 "$PID" 2>/dev/null; then
      echo "!! ffmpeg ignored SIGINT — forcing" >&2; kill -9 "$PID" 2>/dev/null; sleep 1
    fi
    rm -f "$DIR/.pid"
    BEFORE=$(ls "$DIR"/*.jpg 2>/dev/null | wc -l | tr -d ' ')
    if [ "$BEFORE" -eq 0 ]; then
      echo "!! no frames captured. Check, in order:" >&2
      echo "!!   1. Screen Recording permission for this terminal" >&2
      echo "!!   2. the ffmpeg error in the queue log (encoder/pixel-format issues" >&2
      echo "!!      also produce zero frames and look identical to a permission denial)" >&2
      exit 1
    fi
    python3 "$(dirname "$0")/dedup-frames.py" "$DIR"
    AFTER=$(ls "$DIR"/*.jpg 2>/dev/null | wc -l | tr -d ' ')
    ROOT=$(python3 -c "import os;print(os.path.realpath(os.path.expanduser('~/class-notes')))")
    echo "$(date '+%Y-%m-%d %H:%M:%S')  STOP   dir=$DIR kept=$AFTER of $BEFORE" >> "$ROOT/screen-capture-audit.log"
    echo ">> slides: $AFTER kept of $BEFORE captured"
    ;;

  *) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
