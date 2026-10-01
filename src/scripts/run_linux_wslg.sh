#!/bin/bash
# Start Titan on Linux (a desktop session, or WSLg) with everything a screen
# reader needs up first: a session bus, the AT-SPI registry, GTK's ATK bridge.
#
#   bash src/scripts/run_linux_wslg.sh          # foreground, log on the console
#   bash src/scripts/run_linux_wslg.sh --check  # start, wait, read the window through AT-SPI, stop
#
# Needs (Debian/Ubuntu): python3 python3-gi gir1.2-atspi-2.0 at-spi2-core
# speech-dispatcher python3-speechd espeak-ng libgtk-3-0 libsdl2-2.0-0
# libportaudio2 pulseaudio-utils, plus `pip install -f
# https://extras.wxpython.org/wxPython4/extras/linux/gtk3/<distro> wxPython`
# and the rest of requirements.txt. Under WSLg the audio goes through the
# WSLg PulseAudio server and the window through Weston; wmctrl/xdotool do
# not work there, AT-SPI does.
cd "$(dirname "$0")/../.."
export DISPLAY="${DISPLAY:-:0}" SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-pulseaudio}" PYTHONUTF8=1
export GTK_MODULES="${GTK_MODULES:-gail:atk-bridge}" NO_AT_BRIDGE=0
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ] || [ ! -S "${DBUS_SESSION_BUS_ADDRESS#unix:path=}" ]; then
  eval "$(dbus-launch --sh-syntax)" 2>/dev/null
  export DBUS_SESSION_BUS_ADDRESS
fi
pgrep -f at-spi-bus-launcher >/dev/null || (/usr/libexec/at-spi-bus-launcher --launch-immediately >/dev/null 2>&1 &)
gsettings set org.gnome.desktop.interface toolkit-accessibility true 2>/dev/null
if [ "$1" = "--check" ]; then
  python3 main.py > /tmp/titan_linux.log 2>&1 &
  pid=$!
  sleep 45
  if kill -0 $pid 2>/dev/null; then echo "Titan is running (pid $pid)"; else echo "Titan exited; see /tmp/titan_linux.log"; fi
  python3 src/scripts/check_atspi_window.py
  kill $pid 2>/dev/null
else
  exec python3 main.py
fi
