# wolf-jellyfin

Fullscreen Jellyfin Desktop for [Games on Whales Wolf](https://github.com/games-on-whales/wolf), using Qt6, native Wayland and libmpv. The app loads your Jellyfin server's web interface.

Linux/amd64 only. Builds use the current GoW Fedora base, current Fedora/RPM Fusion
packages and Jellyfin Desktop's upstream default branch, without version pins.
This is a development build, not a stable Jellyfin Desktop release. Compatibility
patches and tests must pass before CI publishes an image.

A bundled one-line compatibility patch makes mpv prefer the container aspect ratio.
A separate Wolf kiosk patch explicitly sizes the client to Qt's logical output
geometry and removes window decorations instead of relying on a desktop window
manager to honour fullscreen/maximize requests. The launcher enables this policy
with `WOLF_JELLYFIN_KIOSK=1`; exiting fullscreen/minimizing is intentionally blocked
in this single-app image. Closing/quitting still works. Existing accounts, web
storage and unrelated settings are preserved. Original source, exact patches and
build instructions are included.
Wolf kiosk mode also selects PulseAudio output and suppresses Qt's native context
menu while preserving the web client's context-menu events. It avoids cross-backend
audio-device discovery and uses the automatic Pulse output routed by `PULSE_SERVER`
and `PULSE_SINK`. The launcher defaults to Qt's `basic` render loop while retaining
Wayland and GPU rendering; `QSG_RENDER_LOOP` can explicitly override it.

## Build

```sh
docker build --pull --no-cache -t wolf-jellyfin:local .
```

Pushes to `main` build and test the image, then publish the runtime to
`ghcr.io/joshcollis/wolf-jellyfin:latest` and `:sha-<commit>`. Manual workflow runs
on `main` also publish; pull requests run unit tests without registry access.
GHCR package visibility is managed separately from repository visibility.
CI refreshes dependencies and source on every build. Each image includes its
Jellyfin source archive, source commit ID and installed package inventory.

## Wolf setup

Add the app from [`examples/wolf.config.toml`](examples/wolf.config.toml) to your Wolf configuration. Replace the HOME mount with a unique local directory for each Wolf profile/app:

```sh
sudo install -d -m 0700 -o 1000 -g 1000 /absolute/path/to/jellyfin-home
```

Existing files in that directory must be writable by UID/GID 1000. Startup changes ownership of the mount root only, not its contents. Do not reuse another app's home.

Wolf must provide its Wayland and PulseAudio sockets, input devices, GPU access and negotiated `GAMESCOPE_WIDTH`, `GAMESCOPE_HEIGHT` and `GAMESCOPE_REFRESH`. Exactly one current Wayland output must match that mode. A mode change ends the session with exit code 75; recreate it with fresh negotiation.

The example relaxes seccomp and AppArmor to allow Chromium's namespace sandbox. Review this policy for your host before use; the container is not privileged and Chromium's sandbox is not disabled.

## Accounts and playback

Select your server and log in interactively. The HOME mount persists settings, profiles and web storage. `JELLYFIN_PROFILE` defaults to `Default` and accepts 1–64 letters, digits, underscores or hyphens. A home-wide advisory lock prevents cooperating sessions from writing the same HOME concurrently; it is not a distributed lock.

Fullscreen TV layout and upstream keyboard/controller mappings are enabled. Native mpv uses upstream hardware-decoding preferences with software fallback. Leave automatic refresh switching disabled: Wolf owns the output mode. Use Wolf's PulseAudio stream rather than HDMI passthrough.

A shared Wolf lobby shares the same UI, playback and logged-in account with all participants. Use separate homes for independent accounts.

## Tests

Requires Docker, Python 3 and a C++ compiler on the host. The compiled audio-device
regression also needs Qt6 Core development headers and `pkg-config` (Ubuntu:
`sudo apt-get install g++ pkg-config qt6-base-dev`). Alternatively set
`AUDIO_TEST_BUILDER` to an existing Docker builder image containing those tools.

```sh
python3 -m unittest discover -s tests -v
docker build --pull --no-cache --target runtime -t wolf-jellyfin:local .
bash tests/image-home.sh wolf-jellyfin:local
docker build --target test -t wolf-jellyfin:test .
python3 tests/fullscreen.py
python3 tests/context_menu.py
python3 tests/acceptance.py
```

Acceptance tests use isolated containers with no external network, synthetic media,
a test-only authenticated Xvfb software display (with a headless Wayland output for
the parent-mode contract), and a PulseAudio null sink. The software renderer uses
mpv `gpu-dumb-mode=yes`, disabled hardware decode and WebEngine `--disable-gpu`;
none of these are production defaults. Results are written to unique ignored
`artifacts/` directories. Tests check actual presented color video, external
subtitles, native keyboard/controller action mappings, pause/seek, audio, storage
persistence and HOME isolation. Native Wayland GPU decoding, real-server
authentication/plugins, physical controllers and Wolf/Moonlight streaming still
require target-host testing. The CPU-only full-shader Wayland path showed intermittent
black video; this software test path does not establish its cause or prove native
GPU rendering.

## License

Project code is MIT. Dependencies retain their own licenses; see [`NOTICE.md`](NOTICE.md). Jellyfin Desktop's corresponding source is included in the image, alongside the local patches. Review dependency source-distribution obligations before distributing container images.
