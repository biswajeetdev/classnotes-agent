#!/bin/bash
# Double-clickable installer. Runs in a real Terminal window so sudo can prompt
# for your password -- which is why neither Claude nor the `!` prefix can do it.
clear
echo "=============================================="
echo " BlackHole 2ch — virtual audio driver"
echo "=============================================="
echo
echo "This lets your Mac record the audio it is playing, so lectures can be"
echo "transcribed. It installs to /Library/Audio/Plug-Ins/HAL/ and therefore"
echo "needs an admin password."
echo
echo "You will be asked for your Mac password. Nothing is sent anywhere."
echo
/opt/homebrew/bin/brew install --cask blackhole-2ch
RC=$?
echo
if [ $RC -eq 0 ] && ls /Library/Audio/Plug-Ins/HAL/ 2>/dev/null | grep -qi blackhole; then
  echo "=============================================="
  echo " INSTALLED. Now REBOOT — the driver does not"
  echo " appear until you do."
  echo "=============================================="
else
  echo "=============================================="
  echo " Install did not complete (exit $RC)."
  echo " Copy the error above back to Claude."
  echo "=============================================="
fi
echo
echo "Press Return to close this window."
read _
