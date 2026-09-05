#!/usr/bin/env bash
# Sit in a live class and build the transcript as it happens.
#
#   live-notes.sh <course-slug> [YYYY-MM-DD]
#   (Ctrl-C when the class ends)
#
# Why this beats capturing recordings: no wait for the recording to be published, no
# SharePoint download block, no replay backlog. It costs no extra time -- it runs
# during a class you are already attending.
#
# CRITICAL DIFFERENCE from capture.sh: that one routes output to BlackHole and you
# hear NOTHING, which is fine for replaying a recording and useless in a live class.
# This requires a MULTI-OUTPUT DEVICE so audio reaches BlackHole *and* your speakers.
#
# One-time setup (Audio MIDI Setup):
#   1. Open "Audio MIDI Setup"  (Cmd-Space -> Audio MIDI Setup)
#   2. "+" bottom-left -> Create Multi-Output Device
#   3. Tick BOTH "BlackHole 2ch" and your speakers/headphones
#   4. Right-click it -> "Use This Device For Sound Output"
#   5. Set your speakers as the Primary/master device (drift correction on BlackHole)
# Then just run this. It never changes your output device -- that is yours to set,
# precisely so it cannot silence you mid-class.
#
# Transcribes in chunks while the class runs, so the transcript is finished within
# about a chunk of the class ending rather than an hour later.

set -uo pipefail

# `pgrep -f live-notes.sh` also matches any shell command containing that string --
# including the caller's own. On 22 Aug that made a stop signal hit the wrong process
# and the real capture ran for 2.5 extra hours into an empty room. Use a PID file.
STATEDIR="$HOME/class-notes/.live"; mkdir -p "$STATEDIR"

if [ "${1:-}" = "stop" ]; then
  slug="${2:?usage: live-notes.sh stop <course-slug>}"
  pf="$STATEDIR/$slug.pid"
  [ -f "$pf" ] || { echo "error: nothing recording for $slug" >&2; exit 1; }
  pid=$(cat "$pf")
  kill -INT "$pid" 2>/dev/null
  # The script finishes transcribing its last chunks before exiting, which can take
  # several minutes. Wait generously -- killing early loses that work.
  for _ in $(seq 1 "${STOP_WAIT_TRIES:-150}"); do kill -0 "$pid" 2>/dev/null || break; sleep 2; done
  if kill -0 "$pid" 2>/dev/null; then
    echo "!! still running after $(( ${STOP_WAIT_TRIES:-150} * 2 / 60 )) min — forcing" >&2
    kill -9 "$pid" 2>/dev/null
  fi
  # these must happen whether it exited cleanly or was forced
  if [ -f "$STATEDIR/$slug.ffpid" ]; then
    kill -9 "$(cat "$STATEDIR/$slug.ffpid")" 2>/dev/null && echo ">> stopped the recorder"
  fi
  if [ -f "$STATEDIR/$slug.gain" ]; then
    osascript -e "set volume input volume $(cat "$STATEDIR/$slug.gain")" 2>/dev/null \
      && echo ">> mic gain restored to $(cat "$STATEDIR/$slug.gain")"
  fi
  rm -f "$pf" "$STATEDIR/$slug.ffpid" "$STATEDIR/$slug.gain"
  echo ">> stopped $slug"
  exit 0
fi

SLUG="${1:?usage: live-notes.sh <course-slug> [date]  |  live-notes.sh stop <course-slug>}"
DATE="${2:-$(date +%Y-%m-%d)}"
ROOT="$HOME/class-notes"
CHUNK_MIN="${CHUNK_MINUTES:-5}"

[ -d "$ROOT/$SLUG" ] || { echo "error: no course '$SLUG' under ~/class-notes" >&2; exit 1; }
command -v whisper-cli >/dev/null || { echo "error: whisper-cli missing" >&2; exit 1; }

# MIC mode is the zero-setup fallback: no BlackHole, no Multi-Output Device, no
# change to your audio output. It records the room, so the class must be playing
# through SPEAKERS, not headphones. Quality is worse than a clean digital capture
# but it is available instantly -- and a rough transcript of a class beats none.
if [ "${MIC_MODE:-0}" = "1" ]; then
  IDX=$(ffmpeg -nostdin -f avfoundation -list_devices true -i "" 2>&1 \
        | sed -n '/AVFoundation audio devices/,$p' | grep -iE 'microphone' \
        | grep -vi iphone \
        | sed -n 's/^\[AVFoundation[^]]*\] *\[\([0-9][0-9]*\)\].*/\1/p' | head -1)
  [ -n "$IDX" ] || { echo "error: no built-in microphone found" >&2; exit 1; }
  # macOS defaults input gain to 100, which CLIPPED the whole 22 Aug lecture
  # (max_volume 0.0 dB). Clipped speech garbles words and whisper guesses.
  OLDGAIN=$(osascript -e 'input volume of (get volume settings)' 2>/dev/null || echo "")
  [ -n "$OLDGAIN" ] && echo "$OLDGAIN" > "$STATEDIR/$SLUG.gain"
  osascript -e "set volume input volume ${MIC_GAIN:-38}" 2>/dev/null
  echo ">> MIC MODE — recording the room from the built-in mic (device $IDX)"
  echo ">> mic input gain ${OLDGAIN:-?} -> ${MIC_GAIN:-38} (avoids clipping)"
  echo ">> The class MUST be on speakers, not headphones, or this records silence."
  echo ">> Your audio output is untouched: $(SwitchAudioSource -c -t output 2>/dev/null)"
else
  IDX=$(ffmpeg -nostdin -f avfoundation -list_devices true -i "" 2>&1 \
        | sed -n '/AVFoundation audio devices/,$p' | grep -i blackhole \
        | sed -n 's/^\[AVFoundation[^]]*\] *\[\([0-9][0-9]*\)\].*/\1/p' | head -1)
  [ -n "$IDX" ] || { echo "error: BlackHole not found (installed but not loaded?)." >&2
                     echo "       Run ~/class-notes/scripts/reload-audio.command, or reboot." >&2
                     echo "       Or capture now with:  MIC_MODE=1 $0 $SLUG" >&2; exit 1; }

  # Refuse to run if output is BlackHole alone -- that means no multi-output device
  # and the user would sit through a silent class.
  #
  # REPLAY=1 lifts that guard: when re-playing an ARCHIVED recording nobody is
  # listening, so routing everything to BlackHole is correct rather than a mistake.
  CUR=$(SwitchAudioSource -c -t output 2>/dev/null)
  if [ "${REPLAY:-0}" != "1" ]; then
    case "$CUR" in
      *BlackHole*) echo "error: output is '$CUR' — you would hear NOTHING in a live class." >&2
                   echo "       Create a Multi-Output Device (see header), or set REPLAY=1" >&2
                   echo "       if you are re-playing an archived recording." >&2
                   exit 1 ;;
    esac
  fi
  echo ">> output device: $CUR"
  echo ">> if you cannot hear the class in the first few seconds, STOP and fix the"
  echo ">> Multi-Output Device — do not sit through a silent lecture."
fi

# Some courses genuinely run two sessions on the same date (506 sits at Sat 10:00
# AND Sat 20:00; 505 at Sat 11:00 and 17:30). Keying purely on the date meant the
# evening class hit "exists" and was refused, losing it. SESSION_SUFFIX lets the
# caller name the second one; unset it and behaviour is exactly as before.
SUFFIX="${SESSION_SUFFIX:-}"
WORK="$ROOT/$SLUG/raw/$DATE$SUFFIX-live"; mkdir -p "$WORK"
OUT="$ROOT/$SLUG/transcripts/$DATE$SUFFIX.txt"
mkdir -p "$(dirname "$OUT")"
[ -f "$OUT" ] && { echo "error: $OUT exists — move it, pick another date, or set SESSION_SUFFIX for a second session that day" >&2; exit 1; }
: > "$OUT"

echo $$ > "$STATEDIR/$SLUG.pid"
echo ">> live capture: $SLUG $DATE, ${CHUNK_MIN}-min chunks -> $OUT"
echo ">> stop with:  $0 stop $SLUG   (or Ctrl-C)"

# Segment straight to disk: ffmpeg closes each chunk cleanly on its own, so a crash
# costs at most one chunk instead of the whole class.
ffmpeg -nostdin -loglevel error -y -f avfoundation -i ":$IDX" \
  -ac 1 -ar 16000 -c:a pcm_s16le \
  -f segment -segment_time $(( CHUNK_MIN * 60 )) "$WORK/chunk-%04d.wav" &
FFPID=$!
echo "$FFPID" > "$STATEDIR/$SLUG.ffpid"
trap 'kill -INT $FFPID 2>/dev/null' INT TERM

DONE=""
QUIET=0
VAD_MODEL="$ROOT/models/ggml-silero-v5.1.2.bin"
# Silero VAD: whisper invents speech in silence -- 36 fabricated "Any doubt in this
# notebook?" lines in one 5-min chunk on 5 Sep. Measured on that chunk: 36 hallucinations
# -> 0, real words 466 -> 515 (it also RECOVERED speech), "bulk constructor" -> the correct
# "bool constructor", and 35s -> 27s because silence is skipped. Guarded so a missing
# model degrades to the old behaviour instead of failing the capture.
VAD_ARGS=""
[ -f "$VAD_MODEL" ] && VAD_ARGS="--vad --vad-model $VAD_MODEL --suppress-nst"

EXPECTED_OUT="$(SwitchAudioSource -c 2>/dev/null)"
AUTO_STOP="${AUTO_STOP_CHUNKS:-3}"   # consecutive silent chunks before giving up

transcribe_chunk() {
  local w="$1" base="${1%.wav}"
  # Whisper HALLUCINATES on silence -- the 22 Aug transcript ended with "*click*",
  # "*sad music*" and "We'll be right back" invented from an empty room. Skip any
  # chunk with no speech in it rather than letting it invent content.
  local mean
  mean=$(ffmpeg -nostdin -i "$w" -af volumedetect -f null - 2>&1 \
         | sed -n 's/.*mean_volume: \(-*[0-9.]*\) dB.*/\1/p')
  if [ -n "$mean" ] && awk -v m="$mean" 'BEGIN{exit !(m < -45)}'; then
    QUIET=$((QUIET+1))
    echo ">> skipped $(basename "$w") — silent (${mean} dB) [${QUIET}/${AUTO_STOP}]"
    rm -f "$w"                       # an empty room is not worth 8 MB
    # Silence has TWO causes and they need opposite responses. A quiet room means the
    # class ended. But if the system output was switched away from the Multi-Output
    # mid-class -- AirPods connecting, headphones, a Teams device grab -- BlackHole goes
    # deaf while the lecture continues, and "silence" would stop a live capture. Check
    # which one this is before concluding anything.
    if [ -n "${EXPECTED_OUT:-}" ]; then
      NOW_OUT=$(SwitchAudioSource -c 2>/dev/null)
      if [ -n "$NOW_OUT" ] && [ "$NOW_OUT" != "$EXPECTED_OUT" ]; then
        echo "!! OUTPUT DEVICE CHANGED: '$EXPECTED_OUT' -> '$NOW_OUT'" >&2
        echo "!! BlackHole is deaf — this silence is a ROUTING failure, not the end of class." >&2
        echo "!! Switch output back to '$EXPECTED_OUT' NOW; recording continues meanwhile." >&2
        QUIET=0                      # do NOT let a reroute trip the auto-stop
        return 0
      fi
    fi
    if [ "$QUIET" -ge "$AUTO_STOP" ]; then
      echo ">> $((QUIET * CHUNK_MIN)) min of silence — class is over, stopping."
      kill -INT $FFPID 2>/dev/null
    fi
    return 0
  fi
  QUIET=0
  whisper-cli -m "$ROOT/models/ggml-large-v3-turbo.bin" -f "$w" -l auto \
    -t "${WHISPER_THREADS:-4}" $VAD_ARGS -otxt -of "$base" >/dev/null 2>&1
  # With VAD on, a chunk containing no speech produces NO .txt at all -- that is correct,
  # not a failure. Guard the read: the old unconditional `cat` printed a confusing
  # "No such file or directory" for every silent chunk, which is the same signature a
  # genuinely dead recorder produces and would mask it.
  if [ -s "$base.txt" ]; then
    cat "$base.txt" >> "$OUT"
    echo ">> +$(wc -w <"$base.txt" | tr -d ' ') words  [$(basename "$w")]"
  else
    echo ">> (no speech in $(basename "$w") — skipped)"
  fi
}

while kill -0 $FFPID 2>/dev/null; do
  sleep 20
  for w in "$WORK"/chunk-*.wav; do
    [ -e "$w" ] || continue
    case " $DONE " in *" $w "*) continue ;; esac
    # only touch a chunk ffmpeg has moved past, so we never read a half-written file
    NEWER=$(ls "$WORK"/chunk-*.wav 2>/dev/null | awk -v f="$w" '$0>f' | head -1)
    [ -n "$NEWER" ] || continue
    DONE="$DONE $w"; transcribe_chunk "$w"
  done
done

sleep 3
for w in "$WORK"/chunk-*.wav; do
  [ -e "$w" ] || continue
  case " $DONE " in *" $w "*) continue ;; esac
  DONE="$DONE $w"; transcribe_chunk "$w"      # the final partial chunk
done

rm -f "$STATEDIR/$SLUG.pid" "$STATEDIR/$SLUG.ffpid" "$STATEDIR/$SLUG.gain"
[ -n "${OLDGAIN:-}" ] && osascript -e "set volume input volume $OLDGAIN" 2>/dev/null \
  && echo ">> mic input gain restored to $OLDGAIN"
echo ">> class captured: $(wc -w <"$OUT" | tr -d ' ') words -> $OUT"
echo ">> now run /classnotes in Claude Code to write the note + rebuild SYNTHESIS.md"
