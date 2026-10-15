#!/usr/bin/env python3
"""Real-client fullscreen regression: larger output, no WM, existing HOME.

TEST_IMAGE=wolf-jellyfin:fullscreen-test python3 tests/fullscreen.py
No external network, GPU, personal HOME or live Wolf changes.
"""
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = os.environ.get('TEST_IMAGE', 'wolf-jellyfin:test')
NAME = 'jellyfin-fullscreen-' + uuid.uuid4().hex[:8]
OUT = ROOT / 'artifacts' / NAME
OUT.mkdir(parents=True)


def docker(*args, input=None, check=True):
    result = subprocess.run(['docker', *args], input=input, text=True,
                            capture_output=True, timeout=60)
    if check and result.returncode:
        raise RuntimeError(f'{args}: {result.stdout}\n{result.stderr}')
    return result.stdout


def js(expression):
    return json.loads(docker('exec', '-i', NAME, 'python3',
                            '/opt/wolf-jellyfin/tests/cdp.py', input=expression))


def start(platform, width, height):
    docker('run', '-d', '--name', NAME, '--network', 'none', '--shm-size=512m',
           '--security-opt', 'seccomp=unconfined', '--security-opt', 'apparmor=unconfined',
           '--mount', f'source={NAME},target=/home/retro',
           '-v', f'{ROOT}/tests:/opt/wolf-jellyfin/tests:ro',
           '-e', f'TEST_QT_PLATFORM={platform}', '-e', f'TEST_WIDTH={width}',
           '-e', f'TEST_HEIGHT={height}', IMAGE,
           'exec gosu retro bash /opt/wolf-jellyfin/tests/headless.sh')
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if js('typeof window.api') == 'object':
                time.sleep(1)
                return
        except Exception:
            pass
        time.sleep(.3)
    raise TimeoutError(docker('logs', NAME))


def stop():
    docker('exec', NAME, 'touch', '/run/wolf-jellyfin/test-done')
    assert docker('wait', NAME).strip() == '0'
    docker('rm', NAME)


def probe(platform, width, height):
    viewport = js('[innerWidth,innerHeight]')
    assert viewport == [width, height], ('Not output-sized', platform, viewport, [width, height])
    if platform == 'xcb':
        data = json.loads(docker('exec', '-u', '1000', '-e', 'DISPLAY=:99',
                                '-e', 'XAUTHORITY=/run/wolf-jellyfin/Xauthority',
                                NAME, 'python3', '/opt/wolf-jellyfin/tests/window_probe.py'))
        assert data['rect'] == {'X': 0, 'Y': 0, 'WIDTH': width, 'HEIGHT': height}, data
        assert data['frameless'], ('Window still permits decorations', data)
    else:
        tree = json.loads(docker('exec', '-u', '1000', NAME, 'bash', '-c',
                                'swaymsg -s /run/wolf-jellyfin/sway-ipc.*.sock -t get_tree -r'))
        def walk(node):
            yield node
            for child in node.get('nodes', []) + node.get('floating_nodes', []):
                yield from walk(child)
        window = next(n for n in walk(tree) if n.get('name') == 'Jellyfin Desktop')
        assert window['fullscreen_mode'] == 1, window
        assert window['rect'] == {'x': 0, 'y': 0, 'width': width, 'height': height}, window
        assert window['deco_rect']['height'] == 0, window
        data = {key: window[key] for key in ['rect', 'fullscreen_mode', 'deco_rect']}
    return {'platform': platform, 'viewport': viewport, 'window': data}


try:
    docker('volume', 'create', NAME)
    report = []
    for platform, width, height in [('xcb', 1920, 1200), ('xcb', 1920, 1080),
                                    ('wayland', 1920, 1200)]:
        start(platform, width, height)
        report.append(probe(platform, width, height))
        # The kiosk must not be escaped by API/window-state changes.
        js("api.window.setFullScreen(false);true")
        time.sleep(.5)
        probe(platform, width, height)
        # Persist an origin marker and deliberately windowed/stale geometry.
        js("api.settings.setValue('path','startupurl_desktop','http://127.0.0.1:8765/index.html');location.href='http://127.0.0.1:8765/index.html';true")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if js('typeof window.api') == 'object' and js('document.title') == 'Whale Jellyfin Synthetic UI':
                break
            time.sleep(.2)
        js("localStorage.setItem('fullscreen-canary','keep-me');api.settings.setValue('main','fullscreen',false);api.settings.setValue('state','geometry','50,60,800,600');true")
        if platform == 'xcb':
            docker('exec', '-u', '1000', '-e', 'DISPLAY=:99',
                   '-e', 'XAUTHORITY=/run/wolf-jellyfin/Xauthority', NAME,
                   'ffmpeg', '-v', 'error', '-y', '-f', 'x11grab', '-video_size', f'{width}x{height}',
                   '-i', ':99', '-frames:v', '1', '/home/retro/evidence/fullscreen.png')
        else:
            docker('exec', '-u', '1000', '-e', 'WAYLAND_DISPLAY=/run/wolf-jellyfin/wayland-1', NAME,
                   'grim', '/home/retro/evidence/fullscreen.png')
        docker('cp', NAME + ':/home/retro/evidence/fullscreen.png', str(OUT / f'{platform}-{width}x{height}.png'))
        stop()
        start(platform, width, height)
        probe(platform, width, height)
        assert js("localStorage.getItem('fullscreen-canary')") == 'keep-me'
        stop()
    (OUT / 'result.json').write_text(json.dumps({'image': IMAGE, 'cases': report,
        'recreation_and_storage': 'pass', 'native_gpu_and_live_wolf': 'unverified'}, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    print('PASS; evidence:', OUT)
finally:
    docker('logs', NAME, check=False)
    docker('cp', NAME + ':/home/retro/evidence/client.log', str(OUT / 'client-last.log'), check=False)
    docker('rm', '-f', NAME, check=False)
    docker('volume', 'rm', NAME, check=False)
