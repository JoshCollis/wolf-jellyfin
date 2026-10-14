#!/usr/bin/env python3
"""Small test-only CDP client; stdlib websocket transport inside the container."""
import base64
import json
import os
import socket
import struct
import sys
import urllib.request
from urllib.parse import urlsplit


def exact(sock,n):
    out=b''
    while len(out)<n:
        part=sock.recv(n-len(out))
        if not part:raise EOFError('CDP socket closed')
        out+=part
    return out


def evaluate(expression):
    targets=json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/list',timeout=5))
    url=urlsplit(next(t['webSocketDebuggerUrl'] for t in targets if t['type']=='page'))
    sock=socket.create_connection((url.hostname,url.port),timeout=10)
    key=base64.b64encode(os.urandom(16)).decode()
    sock.sendall(f'GET {url.path} HTTP/1.1\r\nHost: {url.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n'.encode())
    response=b''
    while not response.endswith(b'\r\n\r\n'):response+=exact(sock,1)
    assert b' 101 ' in response,response
    payload=json.dumps({'id':1,'method':'Runtime.evaluate','params':{'expression':expression,'returnByValue':True,'awaitPromise':True}}).encode()
    mask=os.urandom(4)
    header=bytes([0x81,0x80|len(payload)]) if len(payload)<126 else bytes([0x81,0xfe])+struct.pack('!H',len(payload))
    sock.sendall(header+mask+bytes(v^mask[i%4] for i,v in enumerate(payload)))
    while True:
        h=exact(sock,2);size=h[1]&127
        if size==126:size=struct.unpack('!H',exact(sock,2))[0]
        if size==127:size=struct.unpack('!Q',exact(sock,8))[0]
        body=exact(sock,size)
        message=json.loads(body)
        if message.get('id')==1:
            sock.close()
            if 'exceptionDetails' in message.get('result',{}):raise RuntimeError(message)
            return message['result']['result'].get('value')
if __name__=='__main__':print(json.dumps(evaluate(sys.stdin.read())))
