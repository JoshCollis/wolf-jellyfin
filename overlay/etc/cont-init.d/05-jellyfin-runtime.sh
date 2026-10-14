#!/usr/bin/env bash
set -euo pipefail
# Fixed non-root identity is an explicit image contract. Pre-own mounted data.
[[ ${PUID:-1000} = 1000 && ${PGID:-1000} = 1000 && ${UNAME:-retro} = retro && ${HOME:-/home/retro} = /home/retro ]] || { printf 'Expected retro UID/GID1000 HOME=/home/retro\n' >&2; exit 64; }
if [[ -n ${WAYLAND_DISPLAY:-} ]]; then
    if [[ $WAYLAND_DISPLAY != /* ]]; then
        export WAYLAND_DISPLAY="${XDG_RUNTIME_DIR:?Parent runtime required}/$WAYLAND_DISPLAY"
    fi
    [[ -S $WAYLAND_DISPLAY ]] || { printf 'Parent Wayland socket missing\n' >&2; exit 1; }
    # Only this lobby socket: never traverse Wolf's shared runtime tree.
    chown 1000:1000 -- "$WAYLAND_DISPLAY"
fi
export XDG_RUNTIME_DIR=/run/wolf-jellyfin
install -d -m 0700 -o 1000 -g 1000 "$XDG_RUNTIME_DIR"
install -d -m 1777 /tmp/.X11-unix
