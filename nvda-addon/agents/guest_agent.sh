#!/bin/sh
# Say what this guest shows, from a guest with no Python in it.
#
# The Python agent beside this one reads a guest properly - AT-SPI on Linux,
# the Accessibility API on macOS - and needs Python and one library. This
# needs neither: it is VMware Tools and `xdotool`, which is on nearly every
# desktop Linux, and it reports the one thing X will answer without a
# toolkit - the window the keyboard is in, and what the pointer is over as
# far as the window manager knows.
#
#   sh guest_agent.sh
#
# There is no address and no key because there is no network: the value goes
# into a VMware guest variable and the reader on the host takes it out with
# `vmrun readVariable`. If `vmware-rpctool` is not here, VMware Tools is not
# installed and there is nothing to borrow - read the guest as a picture
# from the host instead, which needs nothing in here at all.
#
# What this CANNOT tell you is which control inside the window the pointer
# is on; that is what AT-SPI is for and why the Python agent exists. A
# window's name is still a great deal more than a picture of an icon.

VAR="${TITAN_VAR:-guestinfo.titan.say}"
EVERY="${TITAN_EVERY:-0.3}"

RPC=""
for candidate in vmware-rpctool /usr/bin/vmware-rpctool /usr/sbin/vmware-rpctool \
                 "/Library/Application Support/VMware Tools/vmware-rpctool"; do
    if command -v "$candidate" >/dev/null 2>&1; then RPC="$candidate"; break; fi
    if [ -x "$candidate" ]; then RPC="$candidate"; break; fi
done
if [ -z "$RPC" ]; then
    echo "agent: vmware-rpctool is not here - VMware Tools is not installed" >&2
    echo "agent: read this guest as a picture from the host instead" >&2
    exit 2
fi
if ! command -v xdotool >/dev/null 2>&1; then
    echo "agent: xdotool is not here - install it, or use guest_agent.py" >&2
    exit 2
fi

count=0
last=""
echo "agent: reporting through $RPC into $VAR"
while :; do
    name="$(xdotool getwindowname "$(xdotool getwindowfocus)" 2>/dev/null)"
    if [ -n "$name" ] && [ "$name" != "$last" ]; then
        last="$name"
        count=$((count + 1))
        # A counter in front makes a repeat a new value: a variable holds
        # what it was last set to for ever, and the reader says a value once.
        "$RPC" "info-set $VAR $count|focus|$name" >/dev/null 2>&1
    fi
    sleep "$EVERY"
done
