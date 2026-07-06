#!/usr/bin/env bash

# Default socket path (can be overridden by NFSM_SOCKET env var)
# The daemon defaults to /run/user/1000/nfsm.sock
SOCKET="${NFSM_SOCKET:-/run/user/$(id -u)/nfsm.sock}"
CMD="${1:-FullWidthRequest}"
# Sends the 'CMD' signal to the daemon with FullWidthRequest as default
if echo "$CMD" | socat - UNIX-CONNECT:"$SOCKET"; then
  exit 0
else
  echo "Error: Could not connect to nfsm daemon at $SOCKET" >&2
  #  Optional: notify-send "NFSM Error" "Could not connect to daemon"
  exit 1
fi
