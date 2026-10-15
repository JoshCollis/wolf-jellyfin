#!/usr/bin/env python3
"""Test-only X11 geometry/decorations probe; no window manager required."""
import ctypes as C
import json
import subprocess

x = C.CDLL('libX11.so.6')
x.XOpenDisplay.argtypes = [C.c_char_p]
x.XOpenDisplay.restype = C.c_void_p
x.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]
x.XInternAtom.restype = C.c_ulong
x.XGetWindowProperty.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong, C.c_long,
                               C.c_long, C.c_int, C.c_ulong,
                               C.POINTER(C.c_ulong), C.POINTER(C.c_int),
                               C.POINTER(C.c_ulong), C.POINTER(C.c_ulong),
                               C.POINTER(C.POINTER(C.c_ubyte))]
x.XFree.argtypes = [C.c_void_p]
x.XCloseDisplay.argtypes = [C.c_void_p]
display = x.XOpenDisplay(None)
assert display, 'Cannot connect to isolated Xvfb'
try:
    window = int(subprocess.check_output(['xdotool', 'search', '--onlyvisible',
                                         '--name', '^Jellyfin Desktop$'], text=True).splitlines()[0])
    geometry = subprocess.check_output(['xdotool', 'getwindowgeometry', '--shell', str(window)], text=True)
    geometry = dict(line.split('=', 1) for line in geometry.splitlines())
    atom = x.XInternAtom(display, b'_MOTIF_WM_HINTS', 0)
    actual = C.c_ulong(); fmt = C.c_int(); count = C.c_ulong(); remaining = C.c_ulong()
    data = C.POINTER(C.c_ubyte)()
    status = x.XGetWindowProperty(display, window, atom, 0, 5, 0, 0,
                                 C.byref(actual), C.byref(fmt), C.byref(count),
                                 C.byref(remaining), C.byref(data))
    hints = []
    if status == 0 and data:
        if fmt.value == 32:
            hints = list(C.cast(data, C.POINTER(C.c_ulong))[:count.value])
        x.XFree(data)
    print(json.dumps({'rect': {k: int(geometry[k]) for k in ['X', 'Y', 'WIDTH', 'HEIGHT']},
                      'frameless': len(hints) >= 3 and bool(hints[0] & 2) and hints[2] == 0,
                      'motif_hints': hints}))
finally:
    x.XCloseDisplay(display)
