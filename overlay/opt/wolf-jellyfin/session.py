#!/usr/bin/env python3
"""Native Wayland session; the parent's current output is the timing authority."""
from decimal import Decimal
import fcntl
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time


def parent_mode(text):
    modes=re.findall(r'width:\s*(\d+) px, height:\s*(\d+) px, refresh:\s*([0-9.]+) (mHz|Hz),?\s+flags:([^\n]+)',text)
    current=[(int(w),int(h),int(Decimal(r)*(1000 if unit=='Hz' else 1))) for w,h,r,unit,flags in modes if 'current' in flags.split()]
    if len(current)!=1: raise ValueError('Expected exactly one current parent wl_output mode')
    return current[0]


def requested(env):
    values=[env.get(k,'') for k in ('GAMESCOPE_WIDTH','GAMESCOPE_HEIGHT','GAMESCOPE_REFRESH')]
    if any(not re.fullmatch(r'[0-9]+',v) for v in values): raise ValueError('Wolf must supply integer width/height/refresh')
    w,h,r=map(int,values)
    if not (320<=w<=7680 and 200<=h<=4320 and 24<=r<=240): raise ValueError('Unsupported negotiated mode')
    return w,h,r*1000


def agree(wanted,actual):
    if wanted!=actual: raise ValueError(f'Negotiated {wanted} differs from current parent {actual}')
    return actual


def changed(previous,actual): return previous!=actual


def completed(code,previous,actual):
    if changed(previous,actual): return 75
    return code if code>=0 else 128-code


def profile_name(name):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',name): raise ValueError('Profile must be 1-64 letters/digits/_/- (not a path)')
    return name


def lease(home):
    fd=os.open(home/'.wolf-jellyfin.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError('HOME lease must be a regular file')
    f=os.fdopen(fd,'w')
    try: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BaseException: f.close(); raise
    return f


def client_args(profile,extra):
    return ['/usr/local/bin/jellyfin-desktop','--fullscreen','--tv',*extra,'--profile',profile]


def shutdown(child,app_pid):
    # Qt must flush its renderer/storage before we terminate remaining descendants.
    try:
        if app_pid is not None and os.getpgid(app_pid)==child.pid:
            os.kill(app_pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:
        child.wait(timeout=8)
    except subprocess.TimeoutExpired:
        pass
    finally:
        try:os.killpg(child.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        child.wait()


def read_parent(env):
    result=subprocess.run(['wayland-info'],env=env,text=True,capture_output=True,timeout=5,check=True)
    return parent_mode(result.stdout)


def main():
    env=os.environ.copy()
    # This image is a single-app Wolf kiosk, not a managed desktop window.
    env['WOLF_JELLYFIN_KIOSK']='1'
    # Qt's threaded loop can deadlock GUI exposure against Wayland frame sync
    # during mpv video/UI transitions. Keep GPU rendering, but on the GUI thread.
    # Preserve an explicit override for controlled renderer A/B diagnostics.
    env.setdefault('QSG_RENDER_LOOP','basic')
    if os.getuid()==0: raise ValueError('Refusing to launch Qt WebEngine as root')
    home=Path(env['HOME']);profile=profile_name(env.get('JELLYFIN_PROFILE','Default'))
    # Lease deliberately covers the entire HOME: Qt global profiles.json also writes here.
    with lease(home):
        mode=agree(requested(env),read_parent(env))
        result=subprocess.run(['/usr/local/bin/jellyfin-desktop','--list-profiles'],env=env,capture_output=True,text=True,check=True,timeout=15)
        if profile not in [line.removesuffix(' *') for line in result.stdout.splitlines()]:
            subprocess.run(['/usr/local/bin/jellyfin-desktop','--create-profile',profile],env=env,check=True,timeout=15)
        pidfile=Path(env['XDG_RUNTIME_DIR'])/'client-main.pid'
        pidfile.unlink(missing_ok=True)
        app_pid=None
        stopped=False
        def stop(signum,frame):
            nonlocal stopped
            stopped=True
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,stop)
        child=subprocess.Popen(['dbus-run-session','--','/opt/wolf-jellyfin/client.sh',*client_args(profile,sys.argv[1:])],env=env,start_new_session=True)
        print(f'Jellyfin Desktop native Wayland, current parent {mode}, UID {os.getuid()}',flush=True)
        try:
            deadline=time.monotonic()+5
            while not pidfile.exists():
                if stopped: return 0
                if child.poll() is not None or time.monotonic()>deadline:
                    raise RuntimeError('Client PID handoff failed')
                time.sleep(.02)
            app_pid=int(pidfile.read_text())
            if os.getpgid(app_pid)!=child.pid:raise RuntimeError('Client PID is outside isolated app group')
            while child.poll() is None:
                if stopped: return 0
                if changed(mode,read_parent(env)):
                    print('Parent output changed: recreate lobby with fresh negotiation',file=sys.stderr)
                    return 75
                time.sleep(1)
            # Parent loss must not be masked by an app's simultaneous clean exit.
            return completed(child.returncode,mode,read_parent(env))
        finally:
            shutdown(child,app_pid)

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:print(f'wolf-jellyfin: {e}',file=sys.stderr);sys.exit(1)
