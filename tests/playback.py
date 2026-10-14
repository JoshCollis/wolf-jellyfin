#!/usr/bin/env python3
"""Exercise the actual Qt WebEngine -> QWebChannel -> libmpv path, not external mpv.
An isolated HTTP marker page is NOT a Jellyfin server/login acceptance test.
"""
import functools
import http.server
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.request
import websocket
EVIDENCE=Path(os.environ['HOME'])/'evidence'
class CDP:
    def __init__(self):
        target=json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/list',timeout=5))[0]
        self.ws=websocket.create_connection(target['webSocketDebuggerUrl'],suppress_origin=True,timeout=10);self.i=0
    def call(self,method,params):
        self.i+=1;self.ws.send(json.dumps({'id':self.i,'method':method,'params':params}))
        while True:
            result=json.loads(self.ws.recv())
            if result.get('id')==self.i:
                if 'error' in result:raise RuntimeError(result)
                return result['result']
    def js(self,expr):
        r=self.call('Runtime.evaluate',{'expression':expr,'returnByValue':True,'awaitPromise':True})
        if 'exceptionDetails' in r:raise RuntimeError(r)
        return r['result'].get('value')

def screenshot(name):
    env=os.environ.copy();env['DISPLAY']=':99';env['XAUTHORITY']='/run/wolf-jellyfin/Xauthority'
    subprocess.run(['ffmpeg','-v','error','-y','-f','x11grab','-video_size','1280x720',
                    '-i',':99','-frames:v','1',str(EVIDENCE/name)],env=env,check=True,timeout=10)

def main():
    EVIDENCE.mkdir(exist_ok=True)
    # Original server-delivered custom UI fixture, no stock bundled web copy.
    (EVIDENCE/'index.html').write_text('<!doctype html><title>Custom server UI fixture</title><style>body{background:#342056;color:white;font:40px sans-serif}</style><h1 id="marker">CUSTOM SERVER UI PRESERVED</h1>')
    (EVIDENCE/'test.srt').write_text('1\n00:00:00,000 --> 00:00:19,500\nWOLF JELLYFIN SUBTITLE TEST\n')
    handler=functools.partial(http.server.SimpleHTTPRequestHandler,directory=str(EVIDENCE))
    server=http.server.ThreadingHTTPServer(('127.0.0.1',8097),handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    c=CDP();c.call('Page.navigate',{'url':'http://127.0.0.1:8097/index.html'})
    for _ in range(100):
        if c.js('!!window.api?.player && !!document.getElementById("marker")'):break
        time.sleep(.1)
    else:raise AssertionError('Native bridge or server UI marker missing')
    assert c.js('document.title')=='Custom server UI fixture'
    assert c.js('!!window.NativeShell')
    prior=c.js('localStorage.getItem("synthetic-test-account")')
    settings_before=c.js('new Promise(r=>window.api.settings.value("main","allowBrowserZoom",r))')
    if os.environ.get('EXPECT_PERSISTENCE')=='1':
        assert prior=='persisted-not-a-real-credential',prior
        assert settings_before is False,settings_before
    if os.environ.get('EXPECT_FRESH')=='1':
        assert prior is None,prior
        assert settings_before is True,settings_before
    c.js('window.api.settings.setValue("main","allowBrowserZoom",false);true')
    c.js('localStorage.setItem("synthetic-test-account", "persisted-not-a-real-credential")')
    c.js('window.api.player.stop();window.api.player.setVideoOnlyMode(false);true');time.sleep(.5)
    screenshot('server-ui.png')
    # The fixture explicitly registers as a test web client; this is NOT server auth.
    c.js('new Promise(r=>window.api.system.hello("isolated-custom-ui-fixture",r))')
    c.js('window.testInputs=[]; window.api.input.hostInput.connect(actions=>window.testInputs.push(...actions));true')
    import socket
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(3);sock.connect('/run/wolf-jellyfin/jellyfin-desktop.Default.input');sock.recv(4096)
        for source,key in [('Keyboard Generic','A'),('Keyboard Generic','L'),('Keyboard Generic','P'),('Xbox One','KEY_BUTTON_0'),('Xbox One','KEY_BUTTON_4')]:
            sock.sendall((json.dumps({'client':'isolated-test','source':source,'keycode':key})+'\r\n').encode());time.sleep(.1)
    inputs=c.js('window.testInputs')
    assert all(action in inputs for action in ['cycle_audio','cycle_subtitles','play_pause','enter','seek_backward']),inputs
    c.js('window.testStates=[]; window.api.player.stateChanged.connect(s=>window.testStates.push(s)); true')
    media=(EVIDENCE/'synthetic.mkv').as_uri();subtitle=(EVIDENCE/'test.srt').as_uri()
    c.js('window.api.settings.setValue("video","hardwareDecoding","disabled");window.api.player.userCommand("set gpu-dumb-mode yes");true')
    time.sleep(.5)
    c.js('window.api.settings.setValue("audio","device","pulse/test-sink");true')
    c.js(f'new Promise(r=>window.api.player.load({json.dumps(media)},{{startMilliseconds:0,autoplay:true}},{{type:"video",frameRate:30,media:{{}}}},1,-1,r))')
    c.js('window.api.player.setVideoOnlyMode(true); true')
    for _ in range(100):
        position_seconds=c.js('new Promise(r=>window.api.player.getPosition(r))')
        if position_seconds>=2:break
        time.sleep(.1)
    else:raise AssertionError(f'Playback did not advance: {position_seconds}')
    c.js(f'window.api.player.setSubtitleStream({json.dumps("#,"+subtitle)});true')
    screenshot('playback.png')
    raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(EVIDENCE/'playback.png'),
        '-vf','crop=1280:600:0:0','-f','rawvideo','-pix_fmt','rgb24','-'],timeout=10)
    pixels=[raw[i:i+3] for i in range(0,len(raw),96)]
    assert len(set(pixels))>100 and sum(max(p)>50 for p in pixels)>1000, 'Presented video is blank'
    # Capture the actual client's Pulse output through a disposable null sink.
    env=os.environ.copy();env.pop('PULSE_SERVER',None)
    capture=subprocess.Popen(['parec','--device=test-sink.monitor','--format=s16le','--rate=48000','--channels=2'],env=env,stdout=subprocess.PIPE)
    try:
        try:
            audio,_=capture.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            capture.terminate()
            audio,_=capture.communicate(timeout=5)
        audio=audio[:192000]
    finally:
        if capture.poll() is None:
            capture.kill();capture.wait(timeout=5)
    import array,math
    samples=array.array('h',audio);rms=math.sqrt(sum(x*x for x in samples)/len(samples));assert rms>100,rms
    (EVIDENCE/'audio.pcm').write_bytes(audio)
    c.js('window.api.player.pause();true');time.sleep(.5)
    p1=c.js('new Promise(r=>window.api.player.getPosition(r))');time.sleep(.5)
    p2=c.js('new Promise(r=>window.api.player.getPosition(r))');assert p2==p1,(p1,p2)
    c.js('window.api.player.seekTo(8000);window.api.player.play();true');time.sleep(1)
    seek=c.js('new Promise(r=>window.api.player.getPosition(r))');assert seek>=8,seek
    screenshot('playback-after-seek.png')
    c.js('window.api.player.stop();window.api.player.setVideoOnlyMode(false);true');time.sleep(.3)
    assert c.js('localStorage.getItem("synthetic-test-account")')=='persisted-not-a-real-credential'
    report={'client':'real Jellyfin Desktop Qt6/libmpv','backend':'Xvfb GLX/llvmpipe software with gpu-dumb-mode, NOT native GPU','server_ui_fixture':True,'position_seconds':position_seconds,'seek_seconds':seek,'audio_pcm_rms':rms,'native_input_mappings':inputs,'pause_stability_seconds':abs(p2-p1),'states':c.js('window.testStates'),'unverified':['real server login/custom plugins','native GPU decode','Wolf/Moonlight','physical controllers','multi-client stream']}
    (EVIDENCE/'playback-result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    server.shutdown()
if __name__=='__main__':main()
