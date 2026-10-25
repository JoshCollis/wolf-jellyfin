#!/usr/bin/env python3
"""Real pinned client startup, synthetic homes only; no playback-health claim.

Run in the matching builder (see docs/desktop-default.md). Uses production
client_args, never an independently constructed desktop launch command.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('session', ROOT/'overlay/opt/wolf-jellyfin/session.py')
session = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session)
BINARY = '/build/src/jellyfin-desktop'


def run_case(saved, extra, expected):
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        env = os.environ | {'HOME': directory, 'QT_QPA_PLATFORM': 'offscreen',
                            'WOLF_JELLYFIN_KIOSK': '1', 'QSG_RENDER_LOOP': 'basic'}
        for profile in ('Default', 'Other'):
            subprocess.run([BINARY, '--create-profile', profile], env=env,
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = home/'.local/share/jellyfin-desktop'
        # Resolve real upstream profile metadata, not assumed directory names.
        entries = {json.loads(p.read_text())['name']: p.parent
                   for p in (base/'profiles').glob('*/profile.json')}
        conf = entries['Default']/'jellyfin-desktop.conf'
        other_conf = entries['Other']/'jellyfin-desktop.conf'
        other_conf.parent.mkdir(parents=True, exist_ok=True)
        untouched = b'{"version":7,"sections":{"main":{"layout":"tv"}}}\n'
        other_conf.write_bytes(untouched)
        if saved is not None:
            conf.parent.mkdir(parents=True, exist_ok=True)
            conf.write_text(json.dumps({'version': 7, 'sections': {
                'main': {'layout': saved, 'fullscreen': False},
                'audio': {'channels': '2.0'}}}))
        args = session.client_args('Default', [*extra, '--log-level', 'info'])
        args[0] = BINARY  # builder location of the exact production executable
        with (home/'startup.log').open('w+') as log:
            child = subprocess.Popen(args, env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    log.flush(); log.seek(0)
                    if 'Auto-connect: starting' in log.read():
                        break
                    if child.poll() is not None:
                        raise AssertionError('Native client exited during startup')
                    time.sleep(.1)
                else:
                    raise AssertionError('Native web shell did not initialize')
            finally:
                child.terminate()
                child.wait(timeout=10)
        main = json.loads(conf.read_text())['sections']['main']
        assert main['layout'] == expected, (saved, extra, main['layout'], expected)
        assert main['fullscreen'] is True, main
        assert main['enableMPV'] is True, main
        assert other_conf.read_bytes() == untouched, 'Other profile changed'
        print(f'PASS saved={saved!r} extra={extra!r}: {expected}, fullscreen, native MPV, other profile intact')


if __name__ == '__main__':
    for saved in (None, 'tv', 'desktop'):
        run_case(saved, [], 'desktop')
    run_case('tv', ['--desktop'], 'desktop')
    run_case('desktop', ['--tv'], 'tv')
