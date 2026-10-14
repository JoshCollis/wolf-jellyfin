# wolf-jellyfin

Fullscreen Jellyfin Desktop for [Games on Whales Wolf](https://github.com/games-on-whales/wolf), using Qt6, native Wayland and libmpv. The app loads your Jellyfin server's web interface.

Linux/amd64 only. Builds use Jellyfin Desktop development snapshot [`2cb4a44`](https://github.com/jellyfin/jellyfin-desktop/tree/2cb4a4456fd29b5b62d825ef0e5df93ed6913328), a pinned Fedora 43 base and exact RPM versions. This is not a stable Jellyfin Desktop release. Builds fail if pinned packages are unavailable or the base reaches its declared end of support (2026-12-02).

A bundled one-line compatibility patch makes mpv prefer the container aspect ratio. Original source, patch and build instructions are included.

## Build

```sh
docker build -t wolf-jellyfin:local .
```

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

Requires Docker and Python 3 on the host:

```sh
python3 -m unittest discover -s tests -v
docker build --target runtime -t wolf-jellyfin:local .
bash tests/image-home.sh wolf-jellyfin:local
docker build --target test -t wolf-jellyfin:test .
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

Project code is MIT. Dependencies retain their own licenses; see [`NOTICE.md`](NOTICE.md). Jellyfin Desktop's corresponding source is included in `vendor/` and the image. Review dependency source-distribution obligations before distributing container images.
