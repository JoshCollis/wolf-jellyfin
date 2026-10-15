#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tests -v
if [[ ${SKIP_BUILD:-0} != 1 ]]; then
    docker build --pull --no-cache --target runtime -t wolf-jellyfin:local-review .
    docker build --target test -t wolf-jellyfin:test .
fi
bash tests/image-home.sh wolf-jellyfin:local-review
name="wolf-jellyfin-test-$$"
home_a="$name-home-a"
home_b="$name-home-b"
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; docker volume rm "$home_a" "$home_b" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker volume create "$home_a" >/dev/null
docker volume create "$home_b" >/dev/null
run_case() {
    local volume=$1 expectation=$2 label=$3
    docker run -d --name "$name" --network none --security-opt seccomp=unconfined --security-opt apparmor=unconfined --shm-size=1g -v "$volume:/home/retro" wolf-jellyfin:test 'exec gosu retro bash /opt/wolf-jellyfin/tests/headless.sh' >/dev/null
    for ((i=0; i<200; i++)); do
        [[ $(docker inspect -f '{{.State.Running}}' "$name") = true ]] || { docker logs "$name"; return 1; }
        if docker exec "$name" test -f /run/wolf-jellyfin/test-ready; then break; fi
        sleep .2
    done
    docker exec "$name" test -f /run/wolf-jellyfin/test-ready
    # Second writer refused before upstream touches profile/config/SQLite state.
    if docker exec -e XDG_RUNTIME_DIR=/run/wolf-jellyfin -e WAYLAND_DISPLAY=/run/wolf-jellyfin/wayland-1 -e GAMESCOPE_WIDTH=1280 -e GAMESCOPE_HEIGHT=720 -e GAMESCOPE_REFRESH=60 "$name" gosu retro python3 /opt/wolf-jellyfin/session.py; then
        printf 'Concurrent same-HOME session unexpectedly succeeded\n' >&2;return 1
    fi
    docker exec -e XDG_RUNTIME_DIR=/run/wolf-jellyfin -e PULSE_SERVER=unix:/run/wolf-jellyfin/pulse/native -e "$expectation=1" "$name" gosu retro python3 /opt/wolf-jellyfin/tests/playback.py
    mkdir -p "evidence/$label"
    docker cp "$name:/home/retro/evidence/." "evidence/$label/"
    docker exec "$name" touch /run/wolf-jellyfin/test-done
    code=$(docker wait "$name");[[ $code = 0 ]]
    docker logs "$name" > "evidence/$label/container.log"
    docker rm "$name" >/dev/null
}
run_case "$home_a" EXPECT_FRESH fresh-home-a
run_case "$home_a" EXPECT_PERSISTENCE recreated-home-a
run_case "$home_b" EXPECT_FRESH isolated-home-b
docker image inspect wolf-jellyfin:local-review --format '{{.Id}}' > evidence/image-id.txt
printf 'PASS: native client software playback/audio/subtitles/input mapping, graceful exit, same-home exclusion, recreation persistence and separate-home isolation\n'
