#!/usr/bin/env python3
"""Select Wolf's Pulse transport in MpvQt's initial property queue only.

This prevents automatic playback selection of native PipeWire. It intentionally
makes no claim about audio-device-list: libmpv still enumerates other drivers.
Keep outside-Wolf behavior unchanged; fail closed on upstream source drift.
"""
import difflib
from pathlib import Path
import sys

root = Path(sys.argv[1])
name = 'src/player/MpvVideoItem.cpp'
old = '''    // Critical: Set vo=libmpv for Qt integration
    Q_EMIT setProperty("vo", "libmpv");
'''
new = old + '''
    // Wolf transports audio over its mounted Pulse socket, not native PipeWire.
    // Queue before MpvQt initialization and PlayerComponent's device observer.
    if (qEnvironmentVariableIntValue("WOLF_JELLYFIN_KIOSK") == 1)
        Q_EMIT setProperty("ao", "pulse");
'''
source = (root / name).read_text()
if source.count(old) != 1 or new in source:
    raise SystemExit(f'Upstream {name} audio anchor changed; re-review patch')
patched = source.replace(old, new)
if '--diff' in sys.argv[2:]:
    print(''.join(difflib.unified_diff(source.splitlines(True), patched.splitlines(True),
                                     'a/' + name, 'b/' + name)), end='')
else:
    (root / name).write_text(patched)
