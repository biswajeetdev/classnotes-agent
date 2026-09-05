#!/usr/bin/env bash
# Record whatever the Mac is playing, via BlackHole.
#
#   capture.sh start <output-basename>   # switch output to BlackHole, start recording
#   capture.sh stop                      # stop, restore your normal output device
#
# Use when a lecture recording cannot be downloaded (some SharePoint/LMS setups block it)
# but can be played in the browser. Play the lecture between start and stop; the
# .wav that lands is a normal file that transcribe.sh can consume.
#
# NOTE: while recording, output goes to BlackHole, so YOU WILL NOT HEAR the audio.
# That is fine for unattended capture. Nothing else should be playing sound.

set -euo pipefail

STATE="$HOME/class-notes/.capture"
DEV_NAME="BlackHole 2ch"

usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; }

blackhole_index() {
  # macOS awk has no 3-arg match(); keep this to sed/grep so it works out of the box.
  ffmpeg -nostdin -f avfoundation -list_devices true -i "" 2>&1 \
    | sed -n '/AVFoundation audio devices/,$p' \
    | grep -i 'blackhole' \
    | sed -n 's/^\[AVFoundation[^]]*\] *\[\([0-9][0-9]*\)\].*/\1/p' \
    | head -1
}

case "${1:-}" in
  start)
    [ $# -ge 2 ] || { usage; exit 1; }
    OUTBASE="$2"
    command -v ffmpeg >/dev/null || { echo "error: ffmpeg missing" >&2; exit 1; }
    command -v SwitchAudioSource >/dev/null || { echo "error: SwitchAudioSource missing" >&2; exit 1; }

    IDX="$(blackhole_index || true)"
    if [ -z "$IDX" ]; then
      echo "error: BlackHole not found in ffmpeg's audio devices." >&2
      echo "       Install it and REBOOT:  brew install --cask blackhole-2ch" >&2
      exit 1
    fi

    mkdir -p "$STATE" "$(dirname "$OUTBASE")"
    SwitchAudioSource -c -t output > "$STATE/prev-output"
    SwitchAudioSource -s "$DEV_NAME" -t output >/dev/null
    echo ">> output switched to $DEV_NAME (you will not hear audio while recording)"

    ffmpeg -nostdin -loglevel error -y -f avfoundation -i ":$IDX" \
      -ac 1 -ar 16000 -c:a pcm_s16le "${OUTBASE}.wav" &
    echo $! > "$STATE/pid"
    echo "$OUTBASE" > "$STATE/outbase"
    echo ">> recording to ${OUTBASE}.wav  — start playback now"
    echo ">> stop with:  $0 stop"
    ;;

  stop)
    [ -f "$STATE/pid" ] || { echo "error: nothing is recording" >&2; exit 1; }
    kill -INT "$(cat "$STATE/pid")" 2>/dev/null || true
    sleep 2
    if [ -f "$STATE/prev-output" ]; then
      SwitchAudioSource -s "$(cat "$STATE/prev-output")" -t output >/dev/null || true
      echo ">> output restored to $(cat "$STATE/prev-output")"
    fi
    OUTBASE="$(cat "$STATE/outbase" 2>/dev/null || echo)"
    rm -f "$STATE/pid" "$STATE/prev-output" "$STATE/outbase"
    if [ -n "$OUTBASE" ] && [ -f "${OUTBASE}.wav" ]; then
      DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "${OUTBASE}.wav" 2>/dev/null || echo 0)
      awk -v d="$DUR" 'BEGIN{printf ">> captured %.1f min\n", d/60}'
      # a silent capture means the routing was wrong, not that the lecture was quiet
      MEAN=$(ffmpeg -nostdin -i "${OUTBASE}.wav" -af volumedetect -f null - 2>&1 \
             | sed -n 's/.*mean_volume: \(-*[0-9.]*\) dB.*/\1/p')
      echo ">> mean level: ${MEAN:-?} dB"
      case "${MEAN:-0}" in -9[0-9]*|-inf) echo "!! SILENT capture — output was not routed to BlackHole, or nothing played." >&2;; esac
      echo ">> next:  ~/class-notes/scripts/transcribe.sh ${OUTBASE}.wav <out-basename>"
    fi
    ;;

  *) usage; exit 1 ;;
esac
