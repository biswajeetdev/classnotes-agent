#!/usr/bin/env bash
# Set (and VERIFY) the playback rate of a lecture playing in Chrome.
#
#   set-playback-rate.sh <rate> [url-substring]
#
# Prints the rate ACTUALLY in effect. The caller must size its wait from that, never
# from what it asked for -- a guessed rate truncates the lecture.
#
# Targets the tab whose URL contains <url-substring> (default "sharepoint.com") across
# ALL windows, rather than the frontmost window. Frontmost is wrong here: lectures play
# in the profile signed into SharePoint (Default), while the front window is often a
# different profile entirely -- and "Allow JavaScript from Apple Events" is PER-PROFILE,
# so aiming at the wrong window fails with -1723 even when the setting is on.
#
# Whisper handles sped-up audio well (1.5x kept every segment in testing) but does NOT
# survive being slowed back down. Play fast, transcribe the fast audio as-is.

set -uo pipefail
RATE="${1:?usage: set-playback-rate.sh <rate> [url-substring]}"
MATCH="${2:-sharepoint.com}"

OUT=$(osascript <<APPLESCRIPT 2>&1
tell application "Google Chrome"
  repeat with w in windows
    repeat with t in tabs of w
      if (URL of t as string) contains "$MATCH" then
        return (execute javascript "(function(){var v=document.querySelector('video');if(!v)return 'novideo';try{v.playbackRate=$RATE;}catch(e){return 'error';}return String(v.playbackRate);})()" in t)
      end if
    end repeat
  end repeat
  return "notab"
end tell
APPLESCRIPT
)

case "$OUT" in
  *-1723*|*"Access not allowed"*)
      echo "1.0"
      echo "!! Chrome blocks JS from Apple Events for that tab's profile. Focus the" >&2
      echo "!! window signed into SharePoint, then: View > Developer >" >&2
      echo "!! Allow JavaScript from Apple Events. Falling back to 1x." >&2
      exit 1 ;;
  notab)
      echo "1.0"; echo "!! no Chrome tab matching '$MATCH' — assuming 1x" >&2; exit 1 ;;
  novideo)
      echo "1.0"; echo "!! tab found but no <video> element yet — assuming 1x" >&2; exit 1 ;;
  ''|*[!0-9.]*)
      echo "1.0"; echo "!! could not set playback rate ($OUT) — assuming 1x" >&2; exit 1 ;;
  *)  echo "$OUT" ;;
esac
