#!/usr/bin/env python3
"""Window helper. Raises the window you click to the front (Hyprland only moves
keyboard focus), and makes minimize feel normal, since Hyprland has none of its own:
- an app asks to be minimized (e.g. clicking it in the top bar while it's
  focused): hide it in the special 'minimized' workspace
(Restoring is done by the top bar and dock click handlers. Restoring on focus
events here made busy windows, e.g. a terminal updating its title, pop back up.)
Listens to Hyprland's event socket; idle otherwise."""
import json
import os
import socket
import subprocess


def hypr(*args):
    return subprocess.run(["hyprctl", *args], capture_output=True, text=True).stdout


def restore(addr: str):
    clients = json.loads(hypr("clients", "-j") or "[]")
    win = next((c for c in clients if c["address"] == addr), None)
    if not win or win["workspace"]["name"] != "special:minimized":
        return
    ws = json.loads(hypr("activeworkspace", "-j"))["id"]
    hypr("dispatch", "movetoworkspacesilent", f"{ws},address:{addr}")
    for mon in json.loads(hypr("monitors", "-j") or "[]"):
        if mon.get("specialWorkspace", {}).get("name") == "special:minimized":
            hypr("dispatch", "togglespecialworkspace", "minimized")
    hypr("dispatch", "focuswindow", f"address:{addr}")


def close_hidden_area():
    for mon in json.loads(hypr("monitors", "-j") or "[]"):
        if mon.get("specialWorkspace", {}).get("name") == "special:minimized":
            hypr("dispatch", "togglespecialworkspace", "minimized")


def main():
    last_active = ""
    path = os.path.join(os.environ["XDG_RUNTIME_DIR"], "hypr", os.environ["HYPRLAND_INSTANCE_SIGNATURE"], ".socket2.sock")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(path)
    buf = b""
    while True:
        data = s.recv(4096)
        if not data:
            return
        buf += data
        *lines, buf = buf.split(b"\n")
        for line in lines:
            if line.startswith(b"activewindowv2>>"):
                addr = line.split(b">>", 1)[1].decode().strip()
                if not addr or addr == last_active:
                    continue                    # same window again (e.g. its title changed): nothing to do
                last_active = addr
                a = addr if addr.startswith("0x") else "0x" + addr
                win = next((c for c in json.loads(hypr("clients", "-j") or "[]") if c["address"] == a), None)
                if not win:
                    continue
                if win["workspace"]["name"] == "special:minimized":
                    # something brought a minimized window forward (an app asking to be
                    # shown, Alt+Tab): put it back on screen instead of opening the hidden area
                    ws = json.loads(hypr("activeworkspace", "-j"))["id"]
                    hypr("dispatch", "movetoworkspacesilent", f"{ws},address:{a}")
                    close_hidden_area()
                    hypr("dispatch", "focuswindow", f"address:{a}")
                if win["floating"]:
                    # normal-desktop behaviour: the window you click comes to the front
                    hypr("dispatch", "alterzorder", f"top,address:{a}")
            elif line.startswith(b"minimized>>"):
                addr, _, state = line.split(b">>", 1)[1].decode().strip().partition(",")
                if state == "1" and addr:
                    a = addr if addr.startswith("0x") else "0x" + addr
                    hypr("dispatch", "movetoworkspacesilent", f"special:minimized,address:{a}")



if __name__ == "__main__":
    main()
