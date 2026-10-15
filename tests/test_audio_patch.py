"""Compile/execute the patched constructor's emitted-option behavior.

A small C++ signal sink replaces Qt plumbing, not the constructor under test.
The separate image-level libmpv probe checks actual AO semantics. Does not claim
that ao=pulse limits audio-device-list: libmpv enumerates other drivers anyway.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
APPLY = ROOT / 'vendor/patches/apply-audio.py'
SOURCE = '''MpvVideoItem::MpvVideoItem(QQuickItem *parent)
    : MpvAbstractItem(parent)
{
    qDebug() << "MpvVideoItem constructed";
    // Critical: Set vo=libmpv for Qt integration
    Q_EMIT setProperty("vo", "libmpv");

#ifdef Q_OS_WIN32
    // Force desktop OpenGL and disable advanced features for compatibility with older GPUs
    Q_EMIT setProperty("gpu-api", "opengl");
    Q_EMIT setProperty("opengl-es", "no");
#endif
}
'''
PREAMBLE = '''#include <cstdlib>
#include <iostream>
#define Q_EMIT
struct QQuickItem {};
struct Log { template<class T> Log& operator<<(T const&) { return *this; } };
Log qDebug() { return {}; }
int qEnvironmentVariableIntValue(const char* k) { auto p=std::getenv(k); return p?std::atoi(p):0; }
struct MpvAbstractItem {
  MpvAbstractItem(QQuickItem*) {}
  void setProperty(const char* k,const char* v) { std::cout << k << '=' << v << '\\n'; }
};
struct MpvVideoItem: MpvAbstractItem { MpvVideoItem(QQuickItem*); };
'''


class AudioPatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'src/player/MpvVideoItem.cpp'
        self.source.parent.mkdir(parents=True)
        self.source.write_text(SOURCE)

    def apply(self, *args):
        return subprocess.run([sys.executable, str(APPLY), str(self.root), *args],
                              capture_output=True, text=True)

    def compile(self):
        self.assertTrue(APPLY.exists(), 'audio applicator is required')
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        cpp = self.root / 'probe.cpp'
        cpp.write_text(PREAMBLE + self.source.read_text() + '\nint main(){MpvVideoItem item(nullptr);}\n')
        self.exe = self.root / 'probe'
        result = subprocess.run(['c++', '-std=c++17', str(cpp), '-o', str(self.exe)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wolf_selects_pulse_in_initial_properties_without_null_fallback(self):
        self.compile()
        env = dict(os.environ, WOLF_JELLYFIN_KIOSK='1')
        result = subprocess.run([str(self.exe)], env=env, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines(), ['vo=libmpv', 'ao=pulse'])

    def test_non_wolf_preserves_upstream_auto_selection(self):
        self.compile()
        for flag in (None, '0', '2'):
            env = dict(os.environ)
            env.pop('WOLF_JELLYFIN_KIOSK', None)
            if flag is not None:
                env['WOLF_JELLYFIN_KIOSK'] = flag
            result = subprocess.run([str(self.exe)], env=env, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.splitlines(), ['vo=libmpv'])

    def test_diff_matches_corresponding_source_without_mutation(self):
        self.assertTrue(APPLY.exists())
        result = self.apply('--diff')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.source.read_text(), SOURCE)
        def edits(text):
            return [line for line in text.splitlines() if line.startswith(('+', '-'))
                    and len(line) > 1 and not line.startswith(('+++', '---'))]
        self.assertEqual(edits(result.stdout), edits(
            (ROOT / 'vendor/patches/jellyfin-wolf-audio.patch').read_text()))

    def test_drift_and_reapplication_fail_closed(self):
        self.assertTrue(APPLY.exists(), 'audio applicator not implemented')
        self.source.write_text(SOURCE.replace('Q_EMIT setProperty("vo", "libmpv");', ''))
        before = self.source.read_text()
        self.assertNotEqual(self.apply().returncode, 0)
        self.assertEqual(self.source.read_text(), before)
        self.source.write_text(SOURCE)
        self.assertEqual(self.apply().returncode, 0)
        before = self.source.read_text()
        self.assertNotEqual(self.apply().returncode, 0)
        self.assertEqual(self.source.read_text(), before)


if __name__ == '__main__':
    unittest.main()
