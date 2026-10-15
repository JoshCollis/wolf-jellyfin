#!/usr/bin/env python3
"""Suppress Qt WebEngine's native menu in Wolf kiosk only.

--diff emits the corresponding-source patch without writing files.
Validate every anchor before writing so upstream drift fails closed.
"""
import difflib
from pathlib import Path
import sys

root = Path(sys.argv[1])
changes = [
    ('src/main.cpp',
     '    Globals::SetContextProperty("components", &ComponentManager::Get().getQmlPropertyMap());\n',
     '''    Globals::SetContextProperty("components", &ComponentManager::Get().getQmlPropertyMap());
    Globals::SetContextProperty("wolfJellyfinKiosk",
                                QVariant(qEnvironmentVariableIntValue("WOLF_JELLYFIN_KIOSK") == 1));
'''),
    ('src/ui/webview.qml',
     '''  WebEngineView
  {
    id: web
    objectName: "web"
''',
     '''  WebEngineView
  {
    id: web
    objectName: "web"

    // Accept the native request in Wolf kiosk; leave web-app handlers untouched.
    onContextMenuRequested: function(request)
    {
      if (wolfJellyfinKiosk)
        request.accepted = true
    }
'''),
]
prepared = []
for name, old, new in changes:
    source = (root / name).read_text()
    if source.count(old) != 1 or new in source:
        raise SystemExit(f'Upstream {name} context-menu anchor changed; re-review patch')
    prepared.append((name, source, source.replace(old, new)))
for name, source, patched in prepared:
    if '--diff' in sys.argv[2:]:
        print(''.join(difflib.unified_diff(source.splitlines(True), patched.splitlines(True),
                                         'a/' + name, 'b/' + name)), end='')
    else:
        (root / name).write_text(patched)
