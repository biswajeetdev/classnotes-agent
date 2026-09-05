#!/usr/bin/env bash
# Is BlackHole actually hearing the class RIGHT NOW? Run any time mid-lecture,
# and always after connecting AirPods or headphones. Takes ~4 seconds.
#
#   ~/class-notes/scripts/check-audio.sh
#
# Why this exists: class-start.sh proves the audio chain ONCE, at startup. If the
# output device is switched afterwards, BlackHole goes deaf and the recorder keeps
# writing silence with no error at all.
export PATH="/opt/homebrew/bin:$PATH"

echo "system output : $(SwitchAudioSource -c 2>/dev/null)"

IDX=$(ffmpeg -nostdin -f avfoundation -list_devices true -i "" 2>&1 \
      | sed -n '/AVFoundation audio devices/,$p' \
      | grep -i 'blackhole' \
      | sed -E 's/.*\[([0-9]+)\] .*/\1/' | head -1)
if [ -z "$IDX" ]; then
  echo "RESULT: ✗ BlackHole device not found — driver not loaded."
  echo "        Run ~/class-notes/scripts/reload-audio.command"
  exit 1
fi

LVL=$(ffmpeg -nostdin -f avfoundation -i ":$IDX" -t 3 -af volumedetect -f null - 2>&1 \
      | sed -n 's/.*mean_volume: \(-*[0-9.]*\) dB.*/\1/p')
echo "BlackHole [$IDX]: ${LVL:-unreadable} dB"

if [ -z "$LVL" ]; then
  echo "RESULT: ✗ could not read BlackHole"
elif awk -v m="$LVL" 'BEGIN{exit !(m < -45)}'; then
  echo "RESULT: ✗ SILENT — the recorder is capturing nothing."
  echo "        Set system output back to a Multi-Output device containing BlackHole 2ch."
else
  echo "RESULT: ✓ audio IS reaching the recorder"
fi
