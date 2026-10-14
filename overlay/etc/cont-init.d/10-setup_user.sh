#!/usr/bin/env bash
set -euo pipefail
# Replaces GoW's delete-existing-user hook; no usermod recursive ownership.
getent group 1000 >/dev/null || groupadd -g 1000 retro
if ! id retro >/dev/null 2>&1; then
    if getent passwd 1000 >/dev/null; then printf 'UID1000 occupied by another user\n' >&2; exit 64; fi
    useradd -M -d /home/retro -u 1000 -g 1000 -s /bin/bash retro
fi
[[ $(id -u retro) = 1000 && $(id -g retro) = 1000 ]] || exit 64
mkdir -p /home/retro
[[ ! -L /home/retro ]] || exit 64
chown 1000:1000 /home/retro
umask 077
