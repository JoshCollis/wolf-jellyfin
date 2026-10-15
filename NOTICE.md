# Third-party notices

Project-specific launcher/tests/docs are MIT. Jellyfin Desktop is GPL-2.0-or-later
(see the upstream source archive's LICENSE and bundled third-party notices).
Each build archives the upstream source it fetched and includes it at
`/usr/share/doc/wolf-jellyfin/jellyfin-desktop-source.tar.gz`, alongside the exact
container-aspect and Wolf kiosk patches. The resolved upstream commit is recorded
in `jellyfin-desktop-commit.txt` in the same directory.

This project modifies `PlayerComponent::updateVideoAspectSettings()` to use mpv's
`-1` default aspect override instead of `no` (2026-10-14). The GPL-2.0-or-later
modification is provided as `vendor/patches/jellyfin-container-aspect.patch` and
copied alongside the source. The Dockerfile records the complete build procedure.

The additional GPL-2.0-or-later `vendor/patches/jellyfin-wolf-kiosk.patch` modifies
`WindowManager::setFullScreen()` and `onVisibilityChanged()` for an opt-in
borderless, explicitly output-sized Wolf kiosk. The strict application helper
`vendor/patches/apply-kiosk.py` and exact patch are copied alongside the source.
The image launcher enables this policy without replacing persistent user data.

The GPL-2.0-or-later `jellyfin-wolf-context-menu.patch` suppresses Qt's native
context menu in Wolf kiosk mode without blocking the web client's context-menu
events. `jellyfin-wolf-audio.patch` selects libmpv's PulseAudio output in that mode
through MpvQt's initial property queue (2026-10-15). Both patches and their strict
application helpers are included alongside the source.

Official GoW base/entrypoint/device/NVIDIA infrastructure is MIT:
https://github.com/games-on-whales/gow/blob/bc4bb677e3376e17265317f23d887ecf42de8972/LICENSE
No endorsement or affiliation is claimed. Fedora, Qt, Chromium, libmpv, MpvQt, FFmpeg,
Mesa, SDL, PulseAudio and the other RPMs retain their individual licenses and installed
notices under `/usr/share/licenses` and `/usr/share/doc`. The image includes the package
inventory at `/usr/share/packages-wolf-jellyfin.txt`; these components are not relicensed
MIT. Before distributing an image, review the applicable corresponding-source duties
for every GPL component; the Jellyfin source archive alone is not the full operating
system dependency source bundle. Package SRPM URLs/source provenance must remain
available or an appropriate source distribution/source offer be prepared. Test media
is generated locally from FFmpeg lavfi testsrc/sine, not downloaded copyrighted media.
