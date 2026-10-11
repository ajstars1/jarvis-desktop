#!/bin/sh
# All apps: asks the sotto dock to show (or hide) its Apps list.
# Falls back to the rofi drawer when the dock isn't running.
python3 -I -c 'import os, socket
s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
s.sendto(b"apps", os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "sotto.sock"))' 2>/dev/null \
    || exec rofi -show drun -theme drawer
