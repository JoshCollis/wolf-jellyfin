#!/usr/bin/env python3
"""Use Wolf's Pulse transport without libmpv backend device enumeration.

Device observation and synchronous reads both enumerate all compiled backends,
regardless of ao=pulse. Preserve native discovery outside Wolf, and validate
all anchors before writing any file so upstream drift fails closed.
"""
import difflib
from pathlib import Path
import sys

root = Path(sys.argv[1])
video = 'src/player/MpvVideoItem.cpp'
player = 'src/player/PlayerComponent.cpp'
old = '''    // Critical: Set vo=libmpv for Qt integration
    Q_EMIT setProperty("vo", "libmpv");
'''
new = old + '''
    // Wolf transports audio over its mounted Pulse socket, not native PipeWire.
    // Queue before MpvQt initialization and PlayerComponent's device observer.
    if (qEnvironmentVariableIntValue("WOLF_JELLYFIN_KIOSK") == 1)
        Q_EMIT setProperty("ao", "pulse");
'''
observe = '  mpv_observe_property(m_mpv->mpv(), 0, "audio-device-list", MPV_FORMAT_NODE);\n'
guarded = '''  // ao=pulse does not limit device discovery: libmpv probes every backend.
  // Wolf has one mounted Pulse transport; avoid native PipeWire hotplug entirely.
  if (qEnvironmentVariableIntValue("WOLF_JELLYFIN_KIOSK") != 1)
  ''' + observe
getter = '''QVariant PlayerComponent::getAudioDeviceList()
{
'''
safe_getter = getter + '''  // Keep the upstream QVariantList<QVariantMap> schema used by settings/WebChannel.
  // "auto" resolves through ao=pulse, retaining Pulse's configured default sink.
  if (qEnvironmentVariableIntValue("WOLF_JELLYFIN_KIOSK") == 1)
    return QVariantList{QVariantMap{{"name", "auto"},
                                   {"description", "Wolf PulseAudio (default)"}}};

'''
changes = {video: [(old, new)], player: [(observe, guarded), (getter, safe_getter)]}
results = []
for name, edits in changes.items():
    source = (root / name).read_text()
    patched = source
    for before, after in edits:
        if patched.count(before) != 1 or after in patched:
            raise SystemExit(f'Upstream {name} audio anchor changed; re-review patch')
        patched = patched.replace(before, after)
    results.append((name, source, patched))
for name, source, patched in results:
    if '--diff' in sys.argv[2:]:
        print(''.join(difflib.unified_diff(source.splitlines(True), patched.splitlines(True),
                                         'a/' + name, 'b/' + name, n=1)), end='')
    else:
        (root / name).write_text(patched)
