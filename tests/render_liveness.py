#!/usr/bin/env python3
"""Real Qt/Wayland liveness A/B, isolated from host display/HOME/network.

TEST_IMAGE=wolf-jellyfin:unpinned-test python3 tests/render_liveness.py
python3 tests/render_liveness.py --cycles 100 --stall-ms 150
python3 tests/render_liveness.py --loops threaded --inject-native-stop

Unlike headless.sh, explicitly exercises BOTH actual render loops. No source or
session.py overrides: launches image's real native Jellyfin Desktop directly.
Each cycle checks asynchronous QWebChannel RPC callbacks (not cached JS state),
fullscreen/window exposure, and compositor-presented pixel canaries. Temporary
workspace switches simulate occlusion, not QWindow::hide(); see report limits.
Optional SIGSTOP of the native process is a deliberately failing detector check,
NOT evidence of a spontaneous Qt bug. Compositor pauses resume automatically.
Only stdlib and existing image tools; no installs, devices or external services.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid


def command(args, timeout=15, check=True, **kw):
    p = subprocess.run(args, capture_output=True, timeout=timeout, **kw)
    if check and p.returncode:
        raise RuntimeError(f'{args}: {p.stdout!r} {p.stderr!r}')
    return p


def inside(args):
    from cdp import evaluate
    home = Path.home()
    out = home / 'render-evidence'
    out.mkdir(exist_ok=True)
    runtime = home / 'render-runtime'
    runtime.mkdir(mode=0o700, exist_ok=True)
    os.environ.update(XDG_RUNTIME_DIR=str(runtime), WLR_BACKENDS='headless',
                      WLR_RENDERER='pixman', WLR_LIBINPUT_NO_DEVICES='1',
                      LIBGL_ALWAYS_SOFTWARE='1', QT_QPA_PLATFORM='wayland',
                      QSG_RENDER_LOOP=args.inside, QSG_INFO='1',
                      QT_LOGGING_RULES='qt.scenegraph.general=true',
                      LP_NUM_THREADS='2')
    for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'SWAYSOCK', 'PULSE_SERVER'):
        os.environ.pop(key, None)
    config = runtime / 'sway.conf'
    config.write_text('xwayland disable\noutput HEADLESS-1 mode 960x540@60Hz\n'
                      'default_border none\nfocus_follows_mouse no\n')
    result = dict(loop=args.inside, cycles_requested=args.cycles, cycles=[],
                  stall_ms=args.stall_ms, injection=args.inject_native_stop,
                  limits=['software Mesa/llvmpipe + headless Sway, not live Wolf/GPU',
                          'workspace hide/show is exposure, not QWindow::hide()',
                          'no actual Jellyfin server or media playback'])
    app = sway = None
    timers = []

    def save():
        (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')

    def wait_for(fn, seconds=20):
        deadline = time.monotonic() + seconds
        last = None
        while time.monotonic() < deadline:
            try:
                value = fn()
                if value:
                    return value
            except Exception as exc:
                last = repr(exc)
            time.sleep(.05)
        raise TimeoutError(f'condition deadline: {last}')

    def ipc(text):
        replies = json.loads(command(['swaymsg', '-s', os.environ['SWAYSOCK'],
                                      '-r', text]).stdout)
        assert all(r.get('success') for r in replies), replies

    def rpc(fullscreen=None):
        # isWayland/isFullScreen are native method invocations with fresh callback
        # IDs; Promise.race is in the renderer so a frozen Qt GUI cannot pass.
        setter = '' if fullscreen is None else f'api.window.setFullScreen({str(fullscreen).lower()});'
        expression = '''(async()=>{await apiPromise; SETTER
          const began=performance.now();
          return await Promise.race([
            new Promise(resolve=>api.window.isWayland(w=>
              api.window.isFullScreen(f=>resolve({native:true,wayland:w,fullscreen:f,
                                                elapsed_ms:performance.now()-began})))),
            new Promise(resolve=>setTimeout(()=>resolve({native:false,renderer:true}),2000))]);
        })()'''.replace('SETTER', setter)
        value = evaluate(expression)
        assert value and value.get('native') and value.get('wayland'), ('native GUI RPC failed', value)
        if fullscreen is not None:
            # State change delivery can race its acknowledgment; retry outside RPC.
            wait_for(lambda: evaluate('new Promise(r=>api.window.isFullScreen(r))') is fullscreen, 3)
        return value

    def paint(rgb):
        # Solid opaque overlay makes the centre output pixel a strict present
        # oracle; JS/RAF alone is insufficient when Qt's GUI/render threads wedge.
        evaluate(f'''(()=>{{let d=document.getElementById('render-canary');
          if(!d){{d=document.createElement('div');d.id='render-canary';document.body.append(d);}}
          d.style.cssText='position:fixed;inset:0;z-index:2147483647;background:rgb{tuple(rgb)}';
          return true;}})()''')

    def presented(rgb, filename=None):
        data = command(['grim', '-t', 'ppm', '-'], timeout=5).stdout
        # grim's P6 header is fixed format; retain image on mismatch for diagnosis.
        magic, dimensions, maxval, pixels = data.split(b'\n', 3)
        assert magic == b'P6' and maxval == b'255', data[:80]
        width, height = map(int, dimensions.split())
        offset = ((height // 2) * width + width // 2) * 3
        sample = list(pixels[offset:offset + 3])
        if filename:
            (out / filename).write_bytes(data)
        return sample == rgb, dict(size=[width, height], centre_rgb=sample,
                                  sha256=hashlib.sha256(data).hexdigest())

    try:
        sway = subprocess.Popen(['sway', '-c', str(config)],
                                stdout=(out / 'sway.log').open('w'), stderr=subprocess.STDOUT)
        display = wait_for(lambda: next(iter(runtime.glob('wayland-[0-9]')), None))
        sock = wait_for(lambda: next(iter(runtime.glob('sway-ipc.*.sock')), None))
        os.environ.update(WAYLAND_DISPLAY=str(display), SWAYSOCK=str(sock))
        app = subprocess.Popen(['/usr/local/bin/jellyfin-desktop', '--disable-gpu',
                                '--remote-debugging-port=9222'],
                               stdout=(out / 'client.log').open('w'), stderr=subprocess.STDOUT)
        result['pids'] = dict(native=app.pid, compositor=sway.pid)
        wait_for(lambda: evaluate('typeof api === "object"'), 45)
        rpc(True)
        names = [(p / 'comm').read_text().strip() for p in Path(f'/proc/{app.pid}/task').iterdir()]
        result['render_thread_observed'] = 'QSGRenderThread' in names
        assert result['render_thread_observed'] == (args.inside == 'threaded'), names
        result['initial_native_rpc'] = rpc()
        save()
        for cycle in range(args.cycles):
            began = time.monotonic()
            item = dict(index=cycle)
            result['current_phase'] = f'cycle {cycle}: fullscreen/exposure'
            save()
            item['fullscreen_on'] = rpc(True)
            ipc('workspace 2')
            time.sleep(.025)
            ipc('workspace 1')
            item['fullscreen_off'] = rpc(False)
            if cycle % 4 == 0:
                ipc(f'output HEADLESS-1 mode {"960x540" if cycle % 8 else "1024x576"}@60Hz')
            if cycle % 5 == 0:
                ipc('output HEADLESS-1 power off')
                time.sleep(.025)
                ipc('output HEADLESS-1 power on')
            rgb = [220, 30, 50] if cycle % 2 else [20, 180, 80]
            paint(rgb)
            if args.stall_ms and cycle % 5 == 0:
                os.kill(sway.pid, signal.SIGSTOP)
                timer = threading.Timer(args.stall_ms / 1000,
                                        lambda: os.kill(sway.pid, signal.SIGCONT))
                timer.start()
                timers.append(timer)
                item['compositor_pause_ms'] = args.stall_ms
                # Wait out injected starvation, then require automatic recovery.
                timer.join()
            if args.inject_native_stop and cycle == 2:
                os.kill(app.pid, signal.SIGSTOP)
                result['current_phase'] = 'negative control: native SIGSTOP'
                save()
            item['native_after_exposure'] = rpc()
            deadline = time.monotonic() + 3
            while True:
                ok, sample = presented(rgb)
                if ok:
                    item['presentation'] = sample
                    break
                if time.monotonic() > deadline:
                    presented(rgb, 'failed-frame.ppm')
                    raise AssertionError(('compositor pixel did not update', rgb, sample))
                time.sleep(.05)
            item['elapsed_ms'] = round((time.monotonic() - began) * 1000, 1)
            result['cycles'].append(item)
            save()
        result['status'] = 'pass'
    except Exception as exc:
        result.update(status='fail', error=repr(exc))
        if app:
            threads = []
            for p in Path(f'/proc/{app.pid}/task').glob('*'):
                try:
                    threads.append(dict(tid=p.name, name=(p / 'comm').read_text().strip(),
                                        wchan=(p / 'wchan').read_text().strip(),
                                        status=(p / 'status').read_text()))
                except OSError:
                    pass
            (out / 'threads.json').write_text(json.dumps(threads, indent=2))
            try:
                result['renderer_after_failure'] = evaluate('({alive:true,now:Date.now()})')
            except Exception as probe_error:
                result['renderer_after_failure'] = repr(probe_error)
    finally:
        for timer in timers:
            timer.join()
        for process in (app, sway):
            if process:
                try:
                    os.kill(process.pid, signal.SIGCONT)
                    process.terminate()
                    process.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                        process.wait(timeout=3)
                    except ProcessLookupError:
                        pass
        logs = list((home / '.local/share').glob('jellyfin-desktop/profiles/*/logs/jellyfin-desktop.log'))
        for index, log in enumerate(logs):
            (out / f'native-{index}.log').write_bytes(log.read_bytes())
        result['render_loop_log_verified'] = any(
            (f'{args.inside} render loop' in log.read_text()) for log in logs)
        if not result['render_loop_log_verified']:
            result.update(status='fail', log_error='actual render loop not verified')
        result.pop('current_phase', None) if result.get('status') == 'pass' else None
        save()
    print(json.dumps({k: v for k, v in result.items() if k != 'cycles'}), flush=True)
    return int(result['status'] != 'pass')


def host(args):
    root = Path(__file__).resolve().parents[1]
    name = 'render-liveness-' + uuid.uuid4().hex[:8]
    out = root / 'artifacts' / name
    out.mkdir(parents=True)
    image = os.environ.get('TEST_IMAGE', 'wolf-jellyfin:test')
    image_id = command(['docker', 'image', 'inspect', image, '--format', '{{.Id}}']).stdout.decode().strip()
    reports = []
    for loop in args.loops.split(','):
        if loop not in ('threaded', 'basic'):
            raise ValueError(loop)
        container = name + '-' + loop
        try:
            entry = f'exec gosu retro python3 /probe/render_liveness.py --inside {loop} --cycles {args.cycles} --stall-ms {args.stall_ms}'
            if args.inject_native_stop:
                entry += ' --inject-native-stop'
            command(['docker', 'run', '-d', '--name', container, '--network', 'none',
                     '--security-opt', 'seccomp=unconfined', '--security-opt', 'apparmor=unconfined',
                     '--shm-size=512m', '--mount', f'type=bind,src={root}/tests,dst=/probe,readonly',
                     image_id, entry], timeout=60)
            exitcode = command(['docker', 'wait', container], timeout=max(120, args.cycles * 15)).stdout.decode().strip()
            logs = command(['docker', 'logs', container], check=False).stdout
            (out / f'{loop}-container.log').write_bytes(logs)
            command(['docker', 'cp', f'{container}:/home/retro/render-evidence', str(out / loop)])
            report = json.loads((out / loop / 'result.json').read_text())
            reports.append(dict(loop=loop, status=report['status'], exitcode=exitcode,
                                completed=len(report['cycles']), error=report.get('error'),
                                render_loop_log_verified=report['render_loop_log_verified']))
        finally:
            command(['docker', 'rm', '-f', '-v', container], check=False)
    summary = dict(image=image, image_id=image_id, cases=reports,
                   spontaneous_reproduction=any(r['status'] != 'pass' for r in reports)
                   if not args.inject_native_stop else 'negative control only')
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))
    print('Evidence:', out)
    return int(any(r['status'] != 'pass' for r in reports))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside', choices=['threaded', 'basic'])
    parser.add_argument('--loops', default='threaded,basic')
    parser.add_argument('--cycles', type=int, default=40)
    parser.add_argument('--stall-ms', type=int, default=150)
    parser.add_argument('--inject-native-stop', action='store_true')
    opts = parser.parse_args()
    if opts.cycles < 1 or opts.stall_ms < 0:
        parser.error('cycles must be positive and stall-ms must be nonnegative')
    if opts.inject_native_stop and opts.cycles < 3:
        parser.error('the native-stop control requires at least three cycles')
    sys.exit(inside(opts) if opts.inside else host(opts))
