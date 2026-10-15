#!/usr/bin/env python3
"""Apply the pinned Wolf kiosk patch without adding an unpinned patch dependency.

--diff prints the exact corresponding-source patch instead of modifying source.
Fail closed if either upstream anchor changes.
"""
import difflib
from pathlib import Path
import sys

path = Path(sys.argv[1]) / 'src/ui/WindowManager.cpp'
source = path.read_text()
changes = [
    ('''void WindowManager::setFullScreen(bool enable)
{
  if (!m_window)
    return;

  if (enable)
''', '''void WindowManager::setFullScreen(bool enable)
{
  if (!m_window)
    return;

  // Wolf's minimal shell need not honour fullscreen/maximize configure requests.
  // Size the client explicitly and remove client-side decorations as well.
  // Use Qt's logical screen geometry (not physical pixels) for HiDPI correctness.
  if (qEnvironmentVariableIntValue("WOLF_JELLYFIN_KIOSK") == 1)
  {
    enable = true;
    m_window->setFlag(Qt::FramelessWindowHint, true);
    if (QScreen* screen = m_window->screen())
      m_window->setGeometry(screen->geometry());
  }

  if (enable)
'''),
    ('''    if (forceAlwaysFS)
''', '''    if (forceAlwaysFS || qEnvironmentVariableIntValue("WOLF_JELLYFIN_KIOSK") == 1)
'''),
]
patched = source
for old, new in changes:
    if patched.count(old) != 1:
        raise SystemExit('Pinned WindowManager kiosk anchor changed; re-review patch')
    patched = patched.replace(old, new)
if '--diff' in sys.argv[2:]:
    print(''.join(difflib.unified_diff(source.splitlines(True), patched.splitlines(True),
                                     'a/src/ui/WindowManager.cpp', 'b/src/ui/WindowManager.cpp')), end='')
else:
    path.write_text(patched)
