#!/bin/bash
clear
echo "================================================="
echo " Load the BlackHole driver without a full reboot"
echo "================================================="
echo
echo "The driver is installed but CoreAudio has not picked it up."
echo "Restarting CoreAudio loads it. ALL AUDIO CUTS OUT FOR ~2 SECONDS."
echo "If you are mid-class, that is a brief blip — nothing disconnects."
echo
read -p "Press Return to continue (Ctrl-C to cancel)..." _
sudo killall coreaudiod
sleep 4
echo
if /opt/homebrew/bin/SwitchAudioSource -a -t output | grep -qi blackhole; then
  echo "================================================="
  echo " BlackHole is LIVE. Go back to Claude."
  echo "================================================="
else
  echo "================================================="
  echo " Still not showing. A full reboot will fix it."
  echo "================================================="
fi
echo
read -p "Press Return to close..." _
