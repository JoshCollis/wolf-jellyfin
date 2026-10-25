#!/usr/bin/env bash
set -euo pipefail
export HOME=/home/retro
umask 077
exec python3 /opt/wolf-jellyfin/session.py "$@"
