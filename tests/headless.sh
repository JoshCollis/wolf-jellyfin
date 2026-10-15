#!/usr/bin/env bash
set -euo pipefail
# Test-only headless software compositor. Production never sets these variables.
[[ $(id -u) = 1000 ]]
export XDG_RUNTIME_DIR=/run/wolf-jellyfin
export WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1
export LIBGL_ALWAYS_SOFTWARE=1 QT_QPA_PLATFORM=wayland QSG_RENDER_LOOP=basic
unset WAYLAND_DISPLAY PULSE_SERVER
mkdir -p "$HOME/evidence"
width=${TEST_WIDTH:-1280}
height=${TEST_HEIGHT:-720}
[[ $width =~ ^[0-9]+$ && $height =~ ^[0-9]+$ ]]
platform=${TEST_QT_PLATFORM:-xcb}
printf 'xwayland disable\noutput HEADLESS-1 mode %sx%s@60Hz\nseat * hide_cursor 3000\n' "$width" "$height" > "$XDG_RUNTIME_DIR/sway.conf"
sway -c "$XDG_RUNTIME_DIR/sway.conf" > "$HOME/evidence/sway.log" 2>&1 &
sway_pid=$!
python3 -m http.server --bind 127.0.0.1 --directory /opt/wolf-jellyfin/tests/fixture 8765 > "$HOME/evidence/http.log" 2>&1 &
http_pid=$!
cleanup() { [[ -z ${app_pid:-} ]] || kill "$app_pid" 2>/dev/null || true; kill "$sway_pid" "$http_pid" 2>/dev/null || true; [[ -z ${xvfb_pid:-} ]] || kill "$xvfb_pid" 2>/dev/null || true; }
trap cleanup EXIT
for ((i=0; i<100; i++)); do
    sock=$(python3 -c 'import glob,os; print(" ".join(p for p in glob.glob(os.environ["XDG_RUNTIME_DIR"]+"/wayland-*") if __import__("stat").S_ISSOCK(os.stat(p).st_mode)))')
    [[ -n $sock ]] && break
    sleep .1
done
export WAYLAND_DISPLAY=${sock%% *}
# With xcb there is deliberately NO window manager to honour fullscreen sizing.
if [[ $platform = xcb ]]; then
export QT_QPA_PLATFORM=xcb DISPLAY=:99 XAUTHORITY=$XDG_RUNTIME_DIR/Xauthority
: > "$XAUTHORITY"
xauth -f "$XAUTHORITY" add :99 . "$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
Xvfb :99 -screen 0 "${width}x${height}x24" -auth "$XAUTHORITY" -nolisten tcp -noreset > "$HOME/evidence/xvfb.log" 2>&1 &
xvfb_pid=$!
for ((i=0; i<100; i++)); do
    kill -0 "$xvfb_pid"
    [[ -S /tmp/.X11-unix/X99 ]] && break
    sleep .1
done
[[ -S /tmp/.X11-unix/X99 ]]
elif [[ $platform != wayland ]]; then
    echo 'Unsupported TEST_QT_PLATFORM' >&2; exit 1
fi
export GAMESCOPE_WIDTH=$width GAMESCOPE_HEIGHT=$height GAMESCOPE_REFRESH=60
[[ -S $WAYLAND_DISPLAY ]]
# Test-only Pulse daemon; production uses Wolf's mounted server socket instead.
pulseaudio --daemonize=yes --exit-idle-time=-1 --load='module-null-sink sink_name=test-sink'
export PULSE_SERVER=unix:$XDG_RUNTIME_DIR/pulse/native
pactl list short sinks > "$HOME/evidence/audio-sinks.txt"
/usr/local/bin/jellyfin-desktop --list-profiles
# Fixture media is original synthetic testsrc + sine, not copyrighted content.
ffmpeg -hide_banner -loglevel error -y -f lavfi -i testsrc2=size=640x360:rate=30 -f lavfi -i sine=frequency=440:sample_rate=48000 -t 20 -c:v libvpx-vp9 -deadline realtime -cpu-used 8 -b:v 1M -c:a pcm_s16le "$HOME/evidence/synthetic.mkv"
python3 /opt/wolf-jellyfin/session.py --disable-gpu --remote-debugging-port 9222 --log-level debug > "$HOME/evidence/client.log" 2>&1 &
app_pid=$!
printf '%s\n' "$app_pid" > "$XDG_RUNTIME_DIR/app.pid"
for ((i=0; i<300; i++)); do
    kill -0 "$app_pid"
    if curl --max-time 2 -fsS http://127.0.0.1:9222/json/list > "$HOME/evidence/targets.json"; then break; fi
    sleep .1
done
# Host test controller talks only to this isolated container's CDP, via docker exec.
[[ -s $HOME/evidence/targets.json ]]
touch "$XDG_RUNTIME_DIR/test-ready"
while [[ ! -e $XDG_RUNTIME_DIR/test-done ]]; do kill -0 "$app_pid"; sleep .2; done
kill -TERM "$app_pid"
wait "$app_pid"
echo 'headless client graceful exit PASS'
