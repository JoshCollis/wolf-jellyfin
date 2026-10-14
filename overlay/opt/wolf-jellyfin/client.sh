#!/usr/bin/env bash
set -euo pipefail
# Private runtime belongs to UID1000. PID lets the supervisor signal Qt first,
# leaving Chromium renderers alive long enough to flush persistent web storage.
printf '%s\n' "$$" > "$XDG_RUNTIME_DIR/client-main.pid"
exec "$@"
