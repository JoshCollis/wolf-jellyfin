#!/usr/bin/env python3
"""Isolated real Qt/libmpv software playback and recreation acceptance."""
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
name='wolf-jellyfin-accept-'+uuid.uuid4().hex[:8]
ARTIFACTS=ROOT/'artifacts'/name
image=os.environ.get('TEST_IMAGE','wolf-jellyfin:test')

def docker(*args,input=None,check=True,timeout=30):
    p=subprocess.run(['docker',*args],input=input,text=True,capture_output=True,timeout=timeout)
    if check and p.returncode:raise RuntimeError(f'docker {args}: {p.stdout}\n{p.stderr}')
    return p

def js(expr):
    return json.loads(docker('exec','-i',name,'python3','/opt/wolf-jellyfin/tests/cdp.py',input=expr).stdout)

def start():
    docker('run','-d','--name',name,'--network','none','--shm-size=512m',
           '--security-opt','seccomp=unconfined','--security-opt','apparmor=unconfined',
           '--mount',f'source={name},target=/home/retro',
           '-v',f'{ROOT}/tests:/opt/wolf-jellyfin/tests:ro',image,
           'exec gosu retro bash /opt/wolf-jellyfin/tests/headless.sh')
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        if docker('exec',name,'test','-e','/run/wolf-jellyfin/test-ready',check=False).returncode==0:
            try:
                if js('typeof window.api')=='object':return
            except Exception:pass
        state=json.loads(docker('inspect',name,'--format','{{json .State}}').stdout)
        if not state['Running']:raise RuntimeError(docker('logs',name).stdout)
        time.sleep(.3)
    raise TimeoutError('Client readiness timeout')

def finish():
    docker('exec',name,'touch','/run/wolf-jellyfin/test-done')
    result=docker('wait',name,timeout=20).stdout.strip()
    assert result=='0',docker('logs',name).stdout
    docker('rm',name)

try:
    ARTIFACTS.mkdir(parents=True,exist_ok=True)
    docker('volume','create',name)
    start()
    assert js('document.title')=='Jellyfin'
    assert js('innerWidth')==1280 and js('innerHeight')==720
    # Exercise an actual HTTP-origin web UI, not the qrc discovery origin.
    js("api.settings.setValue('path','startupurl_desktop','http://127.0.0.1:8765/index.html');location.href='http://127.0.0.1:8765/index.html';true")
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        if js('document.title')=='Whale Jellyfin Synthetic UI' and js('typeof window.api')=='object':break
        time.sleep(.2)
    assert js("document.getElementById('custom-marker').innerText")== 'Original local HTML; not a Jellyfin server simulation.'
    # Exercise upstream key/controller mapping through the real local input socket.
    js("new Promise(r=>api.system.hello('isolated-fixture',r))")
    js("window.testInputs=[];api.input.hostInput.connect(a=>window.testInputs.push(...a));true")
    mapped=json.loads(docker('exec',name,'python3','-c',
        "import socket,json,time; s=socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect('/run/wolf-jellyfin/jellyfin-desktop.Default.input'); s.recv(4096); pairs=[('Keyboard Generic','A'),('Keyboard Generic','L'),('Keyboard Generic','P'),('Xbox One','KEY_BUTTON_0'),('Xbox One','KEY_BUTTON_4')]; [(s.sendall((json.dumps({'client':'test','source':source,'keycode':key})+'\\r\\n').encode()),time.sleep(.1)) for source,key in pairs]; print('true')").stdout)
    actions=js('window.testInputs')
    assert all(a in actions for a in ['cycle_audio','cycle_subtitles','play_pause','enter','seek_backward']),actions
    # Real embedded mpv playback. No pretend Jellyfin API or external server account.
    js("api.settings.setValue('video','hardwareDecoding','disabled');api.player.userCommand('set gpu-dumb-mode yes');true")
    time.sleep(.5)
    js("new Promise(r=>{api.player.load('file:///home/retro/evidence/synthetic.mkv',{autoplay:true,startMilliseconds:0},{type:'video',headers:{},metadata:{Name:'Original synthetic test'},media:{}},1,'#,file:///opt/wolf-jellyfin/tests/fixture/subtitle.srt',()=>r(true));api.player.setVideoOnlyMode(true);})")
    time.sleep(3)
    # A real PulseAudio UNIX null sink receives mpv audio (not Moonlight acceptance).
    inputs=docker('exec','-u','1000','-e','PULSE_SERVER=unix:/run/wolf-jellyfin/pulse/native',name,'pactl','list','short','sink-inputs').stdout
    assert inputs.strip(), 'No actual mpv PulseAudio sink input'
    audio=docker('exec','-u','1000','-e','PULSE_SERVER=unix:/run/wolf-jellyfin/pulse/native',name,'bash','-c',
                 "timeout 2 parec --device=test-sink.monitor --format=s16le --rate=48000 --channels=2 > /home/retro/evidence/audio.raw || test $? = 124")
    signal=docker('exec',name,'python3','-c',
                 "import array,pathlib,json; a=array.array('h'); a.frombytes(pathlib.Path('/home/retro/evidence/audio.raw').read_bytes()); print(json.dumps({'samples':len(a),'peak':max(map(abs,a)),'nonzero':sum(v!=0 for v in a)}))").stdout
    audio_stats=json.loads(signal)
    assert audio_stats['peak']>100 and audio_stats['nonzero']>1000,audio_stats
    p1=js('new Promise(r=>api.player.getPosition(r))')
    time.sleep(2)
    p2=js('new Promise(r=>api.player.getPosition(r))')
    duration=js('new Promise(r=>api.player.getDuration(r))')
    assert p2>p1>0 and duration==20,(p1,p2,duration)
    docker('exec','-u','1000',name,'bash','-c','export DISPLAY=:99 XAUTHORITY=/run/wolf-jellyfin/Xauthority; ffmpeg -v error -y -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /home/retro/evidence/video.png')
    docker('cp',name+':/home/retro/evidence/video.png',str(ARTIFACTS/'synthetic-video.png'))
    pixels=json.loads(docker('exec',name,'python3','-c',
        "import subprocess,json; raw=subprocess.check_output(['ffmpeg','-v','error','-i','/home/retro/evidence/video.png','-vf','crop=1280:600:0:0','-f','rawvideo','-pix_fmt','rgb24','-']); p=[raw[i:i+3] for i in range(0,len(raw),96)]; print(json.dumps({'sample_colors':len(set(p)),'lit_samples':sum(max(v)>50 for v in p)}))").stdout)
    js("api.player.userCommand('screenshot-to-file /home/retro/evidence/mpv-decoded.png video');true")
    time.sleep(.3)
    docker('cp',name+':/home/retro/evidence/mpv-decoded.png',str(ARTIFACTS/'mpv-decoded.png'),check=False)
    assert pixels['sample_colors']>100 and pixels['lit_samples']>1000, ('Video counter moved but presented image is blank',pixels)
    docker('cp',name+':/home/retro/evidence/client.log',str(ARTIFACTS/'client-playback.log'))
    js('api.player.pause();true');time.sleep(.5)
    paused=js('new Promise(r=>api.player.getPosition(r))');time.sleep(1)
    assert js('new Promise(r=>api.player.getPosition(r))')==paused
    js('api.player.seekTo(10000);true');time.sleep(.5)
    seek=js('new Promise(r=>api.player.getPosition(r))');assert 9<=seek<=11,seek
    docker('exec','-u','1000',name,'bash','-c','export DISPLAY=:99 XAUTHORITY=/run/wolf-jellyfin/Xauthority; ffmpeg -v error -y -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /home/retro/evidence/seek-paused.png')
    docker('cp',name+':/home/retro/evidence/seek-paused.png',str(ARTIFACTS/'seek-paused.png'))
    js("api.player.stop();api.player.setVideoOnlyMode(false);api.settings.setValue('main','allowBrowserZoom',false);localStorage.setItem('review-canary','synthetic-not-an-auth-token');true")
    time.sleep(1)
    # Existing unrelated root-owned content must not be recursively changed.
    docker('exec',name,'bash','-c','touch /home/retro/unrelated-owned-by-root; chmod 600 /home/retro/unrelated-owned-by-root')
    before=js("new Promise(r=>api.settings.value('main','allowBrowserZoom',r))")
    assert before is False
    finish()
    start()
    assert js("localStorage.getItem('review-canary')")=='synthetic-not-an-auth-token'
    assert js("new Promise(r=>api.settings.value('main','allowBrowserZoom',r))") is False
    assert docker('exec',name,'stat','-c','%u','/home/retro/unrelated-owned-by-root').stdout.strip()=='0'
    # A second cooperative launch must refuse sharing the complete HOME lease.
    second=docker('exec','-u','1000',name,'python3','/opt/wolf-jellyfin/session.py',check=False)
    assert second.returncode!=0 and 'Resource temporarily unavailable' in second.stderr,second.stderr
    docker('cp',name+':/home/retro/evidence/client.log',str(ARTIFACTS/'client-recreated.log'))
    finish()
    report={'software_qt_xvfb_launch':'pass','synthetic_libmpv_playback':'pass',
            'position_seconds':[p1,p2],'duration_seconds':duration,'pause_seek':'pass',
            'presented_video_pixels':pixels,'native_input_mappings':actions,
            'test_only_rendering':'Xvfb GLX/llvmpipe; hwdec disabled; gpu-dumb-mode yes; WebEngine --disable-gpu',
            'pulseaudio_unix_sink':'pass','audio_samples':audio_stats,
            'persistent_qt_storage_and_client_setting':'pass','nonrecursive_home_ownership':'pass',
            'concurrent_home_lease_refusal':'pass','graceful_exit':'pass',
            'image':image,'artifacts':str(ARTIFACTS),'native_gpu':'unverified','wolf_moonlight':'unverified',
            'real_server_login_custom_plugins':'unverified','shared_lobby_multi_client':'unverified'}
    (ARTIFACTS/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
finally:
    # Preserve diagnostics even when an assertion fails before the normal log copy.
    if ARTIFACTS.exists() and docker('inspect',name,check=False).returncode==0:
        docker('cp',name+':/home/retro/evidence/client.log',str(ARTIFACTS/'client-last.log'),check=False)
        logs=docker('logs',name,check=False)
        (ARTIFACTS/'container-last.log').write_text(logs.stdout+logs.stderr)
    docker('rm','-f',name,check=False)
    docker('volume','rm',name,check=False)