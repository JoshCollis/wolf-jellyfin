#!/usr/bin/env python3
"""Real Qt native-menu differential test (isolated software-rendered X11).

TEST_IMAGE=wolf-jellyfin:test TEST_CLIENT=/path/to/built/jellyfin-desktop \
    python3 tests/context_menu.py
Requires the existing test image's Xvfb/ffmpeg/xdotool/CDP dependencies.
Screenshots use the whole X screen, NOT CDP (which cannot see native menus).
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = os.environ.get('TEST_IMAGE', 'wolf-jellyfin:test')
NAME = 'jellyfin-context-menu-' + uuid.uuid4().hex[:8]
OUT = ROOT / 'artifacts' / NAME
OUT.mkdir(parents=True)


def docker(*args, input=None, check=True):
    result = subprocess.run(['docker', *args], input=input, text=True,
                            capture_output=True, timeout=90)
    if check and result.returncode:
        raise RuntimeError(f'{args}: {result.stdout}\n{result.stderr}')
    return result.stdout


def js(code):
    return json.loads(docker('exec', '-i', NAME, 'python3',
                            '/opt/wolf-jellyfin/tests/cdp.py', input=code))


def xrun(*args):
    return docker('exec', '-u', '1000', '-e', 'DISPLAY=:99',
                  '-e', 'XAUTHORITY=/run/wolf-jellyfin/Xauthority', NAME, *args)


def frame(label):
    xrun('ffmpeg', '-v', 'error', '-y', '-f', 'x11grab', '-draw_mouse', '0',
         '-video_size', '1280x720', '-i', ':99', '-frames:v', '1',
         f'/home/retro/evidence/{label}.png')
    docker('cp', f'{NAME}:/home/retro/evidence/{label}.png', str(OUT / f'{label}.png'))
    return xrun('ffmpeg', '-v', 'error', '-i', f'/home/retro/evidence/{label}.png',
                '-f', 'md5', '-').strip()


report = []
with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
    headless = Path(tmp) / 'headless.sh'
    source = (ROOT / 'tests/headless.sh').read_text()
    anchor = 'python3 /opt/wolf-jellyfin/session.py --disable-gpu'
    if source.count(anchor) != 1:
        raise RuntimeError('Headless launcher changed; re-review context-menu control')
    source = source.replace(anchor,
                            '/usr/local/bin/jellyfin-desktop --fullscreen --tv --disable-gpu')
    headless.write_text(source)
    for kiosk in ('0', '1'):
        mounts = ['-v', f'{ROOT}/tests:/opt/wolf-jellyfin/tests:ro',
                  '-v', f'{headless}:/context-menu-headless.sh:ro']
        if os.environ.get('TEST_CLIENT'):
            mounts += ['-v', f'{Path(os.environ["TEST_CLIENT"]).resolve()}:/usr/local/bin/jellyfin-desktop:ro']
        try:
            docker('run', '-d', '--name', NAME, '--network', 'none', '--shm-size=512m',
                   '--security-opt', 'seccomp=unconfined', '--security-opt', 'apparmor=unconfined',
                   '-e', f'WOLF_JELLYFIN_KIOSK={kiosk}', *mounts, IMAGE,
                   'exec gosu retro bash /context-menu-headless.sh')
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    if js('typeof window.api') == 'object':
                        break
                except Exception:
                    pass
                time.sleep(.2)
            else:
                raise TimeoutError(docker('logs', NAME))
            # A static page that does NOT preventDefault: the native default must
            # appear in the control case, and the app event must reach both cases.
            js('document.body.innerHTML="<style>*{cursor:none!important}body{background:rgb(25,50,75)}</style>";window.contextHits=0;document.addEventListener("contextmenu",()=>window.contextHits++);true')
            xrun('xdotool', 'mousemove', '400', '300')
            time.sleep(1)
            before = frame(f'kiosk-{kiosk}-before')
            xrun('xdotool', 'click', '3')
            time.sleep(1)
            after = frame(f'kiosk-{kiosk}-after')
            hits = js('window.contextHits')
            assert hits == 1, ('Web-app contextmenu event lost', kiosk, hits)
            assert (before == after) == (kiosk == '1'), ('Native menu mismatch', kiosk, before, after)
            report.append({'kiosk': kiosk, 'native_menu_visible': before != after,
                           'web_app_contextmenu_events': hits})
            docker('exec', NAME, 'touch', '/run/wolf-jellyfin/test-done')
            assert docker('wait', NAME).strip() == '0'
        finally:
            docker('cp', NAME + ':/home/retro/evidence/client.log',
                   str(OUT / f'kiosk-{kiosk}-client.log'), check=False)
            docker('rm', '-f', '-v', NAME, check=False)
(OUT / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
print('PASS; evidence:', OUT)
