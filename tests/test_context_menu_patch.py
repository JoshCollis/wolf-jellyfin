"""Focused source-patch contract; no Qt, network or Docker required."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
APPLY = ROOT / 'vendor/patches/apply-context-menu.py'
MAIN = '    Globals::SetContextProperty("components", &ComponentManager::Get().getQmlPropertyMap());\n'
QML = '''  WebEngineView
  {
    id: web
    objectName: "web"
'''


class ContextMenuPatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, text in [('src/main.cpp', MAIN), ('src/ui/webview.qml', QML)]:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)

    def apply(self, *args):
        return subprocess.run([sys.executable, str(APPLY), str(self.root), *args],
                              capture_output=True, text=True)

    def test_native_menu_is_accepted_only_in_wolf_kiosk(self):
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        main = (self.root / 'src/main.cpp').read_text()
        qml = (self.root / 'src/ui/webview.qml').read_text()
        self.assertIn('Globals::SetContextProperty("wolfJellyfinKiosk",', main)
        self.assertIn('qEnvironmentVariableIntValue("WOLF_JELLYFIN_KIOSK") == 1', main)
        self.assertIn('onContextMenuRequested: function(request)', qml)
        self.assertIn('if (wolfJellyfinKiosk)\n        request.accepted = true', qml)
        self.assertNotIn('request.accepted = false', qml)
        self.assertNotIn('preventDefault', qml)  # Do not block web-app handlers.

    def test_diff_matches_shipped_corresponding_source_without_mutating(self):
        result = self.apply('--diff')
        self.assertEqual(result.returncode, 0, result.stderr)
        def changes(diff):
            return [line for line in diff.splitlines() if line.startswith(('+', '-'))
                    and not line.startswith(('+++', '---'))]
        self.assertEqual(changes(result.stdout), changes(
            (ROOT / 'vendor/patches/jellyfin-wolf-context-menu.patch').read_text()))
        self.assertEqual((self.root / 'src/main.cpp').read_text(), MAIN)
        self.assertEqual((self.root / 'src/ui/webview.qml').read_text(), QML)

    def test_changed_or_ambiguous_anchor_refused_before_any_write(self):
        for replacement in ['', QML + QML]:
            with self.subTest(replacement=replacement):
                (self.root / 'src/ui/webview.qml').write_text(replacement)
                result = self.apply()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('context-menu anchor changed', result.stderr)
                self.assertEqual((self.root / 'src/main.cpp').read_text(), MAIN)
                self.assertEqual((self.root / 'src/ui/webview.qml').read_text(), replacement)

    def test_second_application_refused(self):
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        before = (self.root / 'src/ui/webview.qml').read_text()
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / 'src/ui/webview.qml').read_text(), before)


if __name__ == '__main__':
    unittest.main()
