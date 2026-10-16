"""Execute patched upstream observer/getter with real Qt variants and poison mpv.

A poisoned enumeration fails immediately rather than reproducing an unbounded
PipeWire deadlock. Set AUDIO_UPSTREAM_SOURCE to test actual upstream source;
otherwise use the minimal verbatim upstream excerpts below.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
VIDEO = '''MpvVideoItem::MpvVideoItem(QQuickItem *parent)
{
    // Critical: Set vo=libmpv for Qt integration
    Q_EMIT setProperty("vo", "libmpv");
}
'''
PLAYER = '''void PlayerComponent::initializeMpv()
{
  mpv_observe_property(m_mpv->mpv(), 0, "pause", MPV_FORMAT_FLAG);
  mpv_observe_property(m_mpv->mpv(), 0, "audio-device-list", MPV_FORMAT_NODE);
  // Setup a hook
}
QVariant PlayerComponent::getAudioDeviceList()
{
  if (!m_mpv) {
    qWarning() << "PlayerComponent::getAudioDeviceList: mpv not initialized yet";
    return QVariant();
  }
  return m_mpv->getProperty( "audio-device-list");
}
'''


def method(source, signature):
    start = source.index(signature)
    body = source.index('{', start)
    depth = 1
    end = body + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


class AudioEnumeration(unittest.TestCase):
    def test_poisoned_enumeration_is_bypassed_only_in_wolf(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root = Path(tmp)
            player = root / 'src/player/PlayerComponent.cpp'
            player.parent.mkdir(parents=True)
            upstream = os.environ.get('AUDIO_UPSTREAM_SOURCE')
            source = (Path(upstream) / 'src/player/PlayerComponent.cpp').read_text() if upstream else PLAYER
            video = (Path(upstream) / 'src/player/MpvVideoItem.cpp').read_text() if upstream else VIDEO
            player.write_text(source)
            (player.parent / 'MpvVideoItem.cpp').write_text(video)
            subprocess.run(['python3', str(ROOT / 'vendor/patches/apply-audio.py'), tmp], check=True)
            patched = player.read_text()
            # Compile the actual observation region, without unrelated player initialization.
            init = method(patched, 'void PlayerComponent::initializeMpv(')
            observers = init[init.index('  mpv_observe_property'):init.index('  // Setup a hook')]
            getter = method(patched, 'QVariant PlayerComponent::getAudioDeviceList()')
            cpp = r'''#include <QVariant>
#include <QDebug>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
static int observations=0, reads=0;
static bool poison=false;
enum {MPV_FORMAT_FLAG, MPV_FORMAT_NODE, MPV_FORMAT_INT64, MPV_FORMAT_DOUBLE};
int mpv_observe_property(void*, int, const char* name, int) {
  if (!strcmp(name,"audio-device-list")) {
    ++observations;
    if (poison) throw std::runtime_error("forbidden audio-device-list observer");
  }
  return 0;
}
struct Mpv {
  void* mpv() { return this; }
  QVariant getProperty(const char* name) {
    if (strcmp(name,"audio-device-list")) std::abort();
    ++reads;
    if (poison) throw std::runtime_error("forbidden synchronous enumeration");
    return QVariantList{QVariantMap{{"name", "native"}, {"description", "Native device"}}};
  }
};
struct PlayerComponent {
  Mpv* m_mpv;
  void initializeMpv();
  QVariant getAudioDeviceList();
};
''' + 'void PlayerComponent::initializeMpv(){\n' + observers + '\n}\n' + getter + r'''
int main(int argc,char** argv) {
  bool wolf=argc>1 && !strcmp(argv[1],"wolf");
  bool getterOnly=argc>2;
  poison=wolf;
  Mpv mpv;
  PlayerComponent player{&mpv};
  try {
    if (!getterOnly) player.initializeMpv();
    auto result=player.getAudioDeviceList();
    if (result.typeId()!=QMetaType::QVariantList) return 10;
    auto list=result.toList();
    if (list.size()!=1 || list[0].typeId()!=QMetaType::QVariantMap) return 11;
    auto entry=list[0].toMap();
    if (entry["name"].toString()!=(wolf?"auto":"native")) return 12;
    if (entry["description"].toString().isEmpty()) return 13;
    if (reads!=(wolf?0:1) || observations!=((wolf||getterOnly)?0:1)) return 14;
    player.m_mpv=nullptr;
    if (!wolf && player.getAudioDeviceList().isValid()) return 15;
  } catch (const std::exception& ex) { qCritical()<<ex.what(); return 20; }
  return 0;
}
'''
            (root / 'probe.cpp').write_text(cpp)
            image = os.environ.get('AUDIO_TEST_BUILDER', 'local')
            local = image == 'local'
            command = f'c++ -std=c++17 {tmp}/probe.cpp -o {tmp}/probe $(pkg-config --cflags --libs Qt6Core)'
            build_args = ['/bin/bash', '-c', command] if local else [
                'docker', 'run', '--rm', '--entrypoint', '/bin/bash',
                '-v', f'{tmp}:{tmp}', image, '-c', command]
            build = subprocess.run(build_args, capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            for flag in ('1', '0', '2', None):
                for getter_only in (False, True):
                    with self.subTest(flag=flag, getter_only=getter_only):
                        mode = 'wolf' if flag == '1' else 'native'
                        if local:
                            args = [str(root / 'probe'), mode]
                        else:
                            args = ['docker', 'run', '--rm', '--entrypoint', str(root / 'probe'), '-v', f'{tmp}:{tmp}']
                            if flag is not None:
                                args += ['-e', f'WOLF_JELLYFIN_KIOSK={flag}']
                            args += [image, mode]
                        if getter_only:
                            args += ['getter-only']
                        env = dict(os.environ)
                        env.pop('WOLF_JELLYFIN_KIOSK', None)
                        if flag is not None:
                            env['WOLF_JELLYFIN_KIOSK'] = flag
                        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)
                        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
