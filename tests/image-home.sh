#!/usr/bin/env bash
set -euo pipefail
image=${1:-wolf-jellyfin:local-review}
# Image-inherited HOME directories must be writable by UID1000 on volume copy-up.
docker run --rm --entrypoint /bin/bash "$image" -c '
  if [[ -d /home/retro/.local ]]; then
    [[ $(stat -c %u /home/retro/.local) = 1000 ]]
  fi
'
