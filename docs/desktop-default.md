# Desktop default

The Wolf session launches Jellyfin Desktop with `--fullscreen --desktop`, unless
the caller explicitly supplies `--tv` or `--desktop`. `startup.sh` forwards its
arguments to the session supervisor. There is no new environment-variable setting
or saved-home migration. Do not pass both layout flags. Native fullscreen/kiosk,
Wayland, GPU rendering, Pulse routing, audio-enumeration guard, and the default
`basic` Qt render loop are unchanged.

## Verified contract

The installed development source inspected on Gill was
`2cb4a4456fd29b5b62d825ef0e5df93ed6913328` (2.0.0-dev, Qt 6.11.2).
`main.cpp` advertises `--desktop` and `--tv`;
`SettingsComponent::setCommandLineValues` applies them after settings load.
`SystemComponent::getNativeShellScript` passes `main.layout` into `jmpInfo.mode`,
and `NativeShell.AppHost.getDefaultLayout()` returns that value.
`main.webMode` is separate web feedback, not the launch default.

The installed server's 12.3 web Layout enum distinguishes `desktop` (modern) from
`desktop-legacy`. Its LayoutManager uses a saved web `layout` preference first,
then the native default. We deliberately preserve that explicit web preference:
a saved web TV or legacy choice is **not** erased by this change. To return such
a client to the new UI, choose **Desktop**, not Desktop (Legacy), in its Display
settings during an approved idle session. A saved **native** `main.layout=tv`
requires no manual migration: `--desktop` overrides it on next launch.

## Tests

```sh
AUDIO_TEST_BUILDER=wolf-jellyfin:audio-enumeration-builder python3 -m unittest discover -s tests -v
docker run --rm --network none --user 1000:1000 \
  --tmpfs /tmp:uid=1000,gid=1000,mode=1777 \
  --env HOME=/tmp --env QT_QPA_PLATFORM=offscreen \
  --mount type=bind,src="$PWD",dst=/work,readonly \
  --entrypoint python3 wolf-jellyfin:audio-enumeration-builder /work/tests/layout_startup.py
node tests/web_layout.cjs /path/to/installed/main.jellyfin.bundle.js
```

The native startup test uses the production `client_args`, the real matching
builder executable, disposable empty homes and synthetic version-7 settings. It
waits for the native web shell to initialize, shuts down that disposable process,
and checks effective persisted desktop/TV mode, fullscreen, enabled MPV, and an
untouched second profile. No household auth or home is copied. The builder's
source commit must match the client being investigated; this local builder was
verified against the commit above. The executable path is builder-specific.

The Node probe executes the actual installed web enum and LayoutManager modules
with inert dependencies; it fails closed on an unsupported bundle format. It
checks new versus legacy desktop and explicit saved web preference precedence.
It is not a browser or playback test. Native startup offscreen is also **not**
proof of rendered video, GPU health, or playback progress. No native/player code
was changed; target-host playback acceptance remains a separate activation check.

## Optional player preferences

No independent supported TV-player/desktop-browser layout switch was found in
the inspected client or server layout code. The video OSD consults global
LayoutManager TV state for focus, keyboard navigation and control visibility.
Changing that state on play/stop is not a safe small isolated setting change.
This change therefore retains desktop browsing **and desktop player controls**.

The inspected video OSD hides its fullscreen control when `ToggleFullscreen` is
unavailable, or when the local player is already fullscreen **and** TV layout is
active. In desktop mode it remains visible. Native MPV's fullscreen action routes
to `host:fullscreen`; Wolf's existing kiosk policy already blocks exiting native
fullscreen. No separate supported button-only switch was found. Altering player
capabilities could also affect shortcuts; runtime-scoped CSS/native-shell changes
would need compilation and isolated playback/control/video-only lifecycle tests.
Neither is implemented here. No global CSS, server assets, DOM observer or
playback-time layout toggles are introduced.

## Activation boundary

Source readiness is not deployment. The existing Gill image still embeds the old
launcher; its runner has no supported layout environment override, and its old
startup script does not forward arguments. Changing an environment variable or
the running container would not be an authoritative fix.

After review and separate release authorization, build/test/publish an image
containing these launcher changes. After interruption approval, update only the
intended Wolf profile's runner image to the approved immutable image, and create
a fresh session/container when playback has ended. Do not restart Jellyfin Server
or change family profiles. Verify launch argv, native saved layout and actual
modern web UI separately, then confirm normal playback progress and controls.
Do not edit the active application's settings file or delete its web storage.
