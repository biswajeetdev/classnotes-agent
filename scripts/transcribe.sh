#!/usr/bin/env bash
# Teams recording (or any audio/video) -> transcript.
# Writes <output-basename>.txt and <output-basename>.srt

set -euo pipefail

# Resolve models from the configured root, not a hardcoded $HOME path, so a
# non-default CLASSNOTES_ROOT (and any test using one) finds them.
ROOT="${CLASSNOTES_ROOT:-$HOME/class-notes}"
MODEL="${WHISPER_MODEL:-$ROOT/models/ggml-large-v3-turbo.bin}"

usage() {
  cat <<'USAGE'
  transcribe.sh <input-media> <output-basename> [language]

  language:
    auto  (default) - whisper detects the dominant language. Use this.
    hi              - force Hindi (Devanagari out; English terms stay Latin).
    en              - force English.

  WARNING: whisper locks onto ONE language per file and SILENTLY DROPS sustained
  speech in the other -- no error, no gap in the output. Verified on turbo,
  22 Aug 2026: a pure-English sentence vanished from a Hindi-dominant recording
  under both auto and hi. Forcing the other direction translates instead of
  dropping, which is equally lossy. There is no flag that is safe on its own,
  which is why this script always runs check-coverage.py afterwards.
  DO NOT IGNORE THE '!!' LINES.

  Roughly 5x realtime on turbo at full threads: a 90-min lecture takes ~18 min.
  Set WHISPER_THREADS to cap CPU (run-queue.sh does this while capturing).
  NEVER pass -bs 1: whisper-cli exits rc=0 in <1s and writes NO transcript.

  Never passes -tr/--translate: translating at the ASR layer destroys technical
  terms and the professor's emphasis in code-switched audio.
USAGE
}

if [ $# -lt 2 ]; then usage; exit 1; fi

INPUT="$1"
OUTBASE="$2"
LANG_CODE="${3:-auto}"

[ -f "$INPUT" ] || { echo "error: no such file: $INPUT" >&2; exit 1; }
[ -f "$MODEL" ] || { echo "error: model missing: $MODEL" >&2; exit 1; }

command -v ffmpeg      >/dev/null || { echo "error: ffmpeg not installed"      >&2; exit 1; }
command -v whisper-cli >/dev/null || { echo "error: whisper-cli not installed" >&2; exit 1; }

if [ "$LANG_CODE" = "en" ]; then
  echo "!! note: lang=en is only safe on the turbo model; it drops Hindi on smaller ones." >&2
fi

# A transcript can cost a second whisper pass plus a hand-merged gap recovery.
# Never silently clobber one.
if [ -f "${OUTBASE}.txt" ] && [ "${FORCE:-0}" != "1" ]; then
  echo "error: ${OUTBASE}.txt already exists." >&2
  echo "       Reuse it, or re-run with FORCE=1 to overwrite." >&2
  echo "       (If it contains a [recovered: ...] line, overwriting loses that work.)" >&2
  exit 1
fi

# Performance cores on Apple silicon, else all cores, else nproc on Linux, else 4.
# sysctl exists on Linux but has no hw.logicalcpu, so an unguarded fallback chain
# yields an empty -t and whisper-cli gets no thread count at all.
default_threads() {
  sysctl -n hw.perflevel0.logicalcpu 2>/dev/null \
    || sysctl -n hw.logicalcpu 2>/dev/null \
    || nproc 2>/dev/null \
    || echo 4
}

mkdir -p "$(dirname "$OUTBASE")"
# GNU mktemp requires at least three X's in a -t template and rejects a bare
# prefix; BSD mktemp accepts the template and appends its own suffix. This form
# is the only one both agree on -- without it the script dies on Linux with
# "mktemp: too few x's in template", which is what broke CI.
WAV="$(mktemp -t classnotes.XXXXXX).wav"
trap 'rm -f "$WAV"' EXIT

echo ">> extracting audio: $(basename "$INPUT")"
ffmpeg -nostdin -loglevel error -y -i "$INPUT" \
  -vn -ac 1 -ar 16000 -c:a pcm_s16le "$WAV"

DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$WAV" 2>/dev/null || echo 0)
awk -v d="$DUR" 'BEGIN{printf ">> audio ready: %.1f min\n", d/60}'

VAD_MODEL="${WHISPER_VAD_MODEL:-$ROOT/models/ggml-silero-v5.1.2.bin}"
# Silero VAD: whisper invents speech in silence -- 36 fabricated "Any doubt in this
# notebook?" lines in one 5-min chunk on 5 Sep. Measured on that chunk: 36 hallucinations
# -> 0, real words 466 -> 515 (it also RECOVERED speech), "bulk constructor" -> the correct
# "bool constructor", and 35s -> 27s because silence is skipped. Guarded so a missing
# model degrades to the old behaviour instead of failing the capture.
VAD_ARGS=""
[ -f "$VAD_MODEL" ] && VAD_ARGS="--vad --vad-model $VAD_MODEL --suppress-nst"

echo ">> transcribing (lang=$LANG_CODE, this takes a while)"
whisper-cli $VAD_ARGS \
  -m "$MODEL" \
  -f "$WAV" \
  -l "$LANG_CODE" \
  -t "${WHISPER_THREADS:-$(default_threads)}" \
  -otxt -osrt \
  -of "$OUTBASE" \
  -pp

echo ">> done: ${OUTBASE}.txt"
wc -w "${OUTBASE}.txt" | awk '{print ">> " $1 " words"}'

# whisper locks onto ONE language per file and silently drops sustained speech in
# the other. Check the transcript actually covers the audio before trusting it.
python3 "$(dirname "$0")/check-coverage.py" "$WAV" "${OUTBASE}.srt" || true
