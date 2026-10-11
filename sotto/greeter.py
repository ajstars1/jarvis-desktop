"""The login screen: the wallpaper's own home screen, with a password line where
your projects will be. Same clock in the same place, same greeting, same dot
trail; when you log in, the wallpaper fades in around a clock that never moved.

It runs under greetd (a small login manager), in kitty, inside the cage kiosk
compositor; bin/sotto-greeter sets that up. Type your password and press Enter.
Tab (or a click) picks the session: Hyprland or Ubuntu. Restart and shut down
sit in the bottom corner (click twice).

  python -m sotto greet --demo     try it in a terminal; the password is "sotto"
"""
import configparser
import json
import os
import shlex
import socket
import struct
import subprocess
import sys
import termios
import threading
import time
import tty
from pathlib import Path

os.environ.setdefault("SOTTO_DEMO", "1")      # the login screen has no projects to collect

from . import wall as W  # noqa: E402
from .grid import Grid  # noqa: E402
from .scene import LIST_W, Region, bigfont, greeting  # noqa: E402

CONFIG = Path(os.environ.get("SOTTO_GREETER_CONFIG", "/etc/sotto-greeter.json"))
CACHE = Path(os.environ.get("SOTTO_GREETER_CACHE", "/var/cache/sotto-greeter"))
SESSION_DIRS = [Path("/usr/share/wayland-sessions")]
CONFIRM_SECONDS = 3


def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def find_sessions(prefer: list[str] | None) -> list[dict]:
    """Desktop sessions from their .desktop files, the preferred ones first."""
    found = {}
    for d in SESSION_DIRS:
        for f in sorted(d.glob("*.desktop")):
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                cp.read(f, encoding="utf-8")
                e = cp["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            if e.get("Hidden", "").lower() == "true" or not e.get("Exec"):
                continue
            found[f.stem] = {"id": f.stem, "name": e.get("Name", f.stem), "cmd": shlex.split(e["Exec"]),
                             "desktops": e.get("DesktopNames", f.stem).strip(";").replace(";", ":")}
    if prefer:
        picked = [found[k] for k in prefer if k in found]
        if picked:
            return picked
    return list(found.values())


def session_env(s: dict) -> list[str]:
    env = [f"XDG_SESSION_TYPE=wayland", f"XDG_SESSION_DESKTOP={s['id']}", f"XDG_CURRENT_DESKTOP={s['desktops']}"]
    if s["id"] == "ubuntu":
        env.append("GNOME_SHELL_SESSION_MODE=ubuntu")
    return env


class Greetd:
    """greetd's IPC: length-prefixed JSON over the socket in $GREETD_SOCK."""

    def __init__(self, path: str):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.connect(path)

    def ask(self, req: dict) -> dict:
        data = json.dumps(req).encode()
        self.s.sendall(struct.pack("=I", len(data)) + data)
        n = struct.unpack("=I", self._read(4))[0]
        return json.loads(self._read(n))

    def _read(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("greetd closed the connection")
            buf += chunk
        return buf

    def close(self):
        self.s.close()


def login(user: str, password: str, session: dict) -> tuple[bool, str]:
    """Log in through greetd. Returns (ok, message to show if not)."""
    g = Greetd(os.environ["GREETD_SOCK"])
    try:
        r = g.ask({"type": "create_session", "username": user})
        answered = False
        while True:
            kind = r.get("type")
            if kind == "auth_message":
                if r.get("auth_message_type") in ("secret", "visible"):
                    if answered:              # asked again (an expired password, say): can't do that here
                        g.ask({"type": "cancel_session"})
                        return False, (r.get("auth_message") or "Can't log in here").strip()
                    answered = True
                    r = g.ask({"type": "post_auth_message_response", "response": password})
                else:                         # info or error text from PAM: acknowledge it
                    r = g.ask({"type": "post_auth_message_response", "response": None})
            elif kind == "success":
                r = g.ask({"type": "start_session", "cmd": session["cmd"], "env": session_env(session)})
                if r.get("type") == "success":
                    return True, ""
                return False, (r.get("description") or "The session wouldn't start")[:60]
            else:
                g.ask({"type": "cancel_session"})
                if r.get("error_type") == "auth_error":
                    return False, "Not quite. Try again."
                return False, (r.get("description") or "Something went wrong")[:60]
    finally:
        g.close()


class Greeter(W.Wall):
    def __init__(self, demo: bool = False):
        super().__init__()
        cfg = load_config()
        self.demo = demo
        self.user = cfg.get("user") or os.environ.get("USER", "")
        self.name = cfg.get("name") or self.user
        self.sessions = find_sessions(cfg.get("sessions"))
        last = self._read_last()
        self.sel = next((k for k, s in enumerate(self.sessions) if s["id"] == last), 0)
        self.password = ""
        self.busy = False
        self.message = ""
        self.result: tuple[bool, str] | None = None
        self.confirm: tuple[str, float] | None = None     # ("restart" | "shut down", until)
        self.hover_kind: tuple[str, int] | None = None
        self.second = -1
        self.leaving = 0.0

    # ── state ─────────────────────────────────────────────────────────────
    def _read_last(self) -> str:
        try:
            return (CACHE / "last-session").read_text().strip()
        except OSError:
            return ""

    def _save_last(self):
        try:
            (CACHE / "last-session").write_text(self.sessions[self.sel]["id"])
        except (OSError, IndexError):
            pass

    def redraw(self):
        self.set_base(self.home(), animate=False)

    # ── the screen ────────────────────────────────────────────────────────
    def home(self) -> Grid:
        lt = time.localtime()
        cols, rows = self.cols, self.rows
        g = Grid(cols, rows)
        bf = bigfont()
        self.regions = []
        # exactly where the wallpaper puts its clock (with six projects), so logging in doesn't move it
        y = max(4, (rows - (bf.height + 4 + 6 * 2)) // 2 - 2)
        clock = time.strftime("%H:%M", lt)
        bf.draw(g, (cols - bf.width(clock)) // 2, y, clock, "dim")
        y += bf.height + 2
        line = f"{time.strftime('%A %d %B', lt)}  ·  {greeting(self.name, lt.tm_hour)}"
        g.text((cols - len(line)) // 2, y, line, "dim")
        y += 4

        # the password line, where the first project will be
        x0 = (cols - LIST_W) // 2 + LIST_W // 2 - 14
        g.text(x0, y, "›", "accent")
        if self.busy:
            dots = "·" * (1 + int(time.time() * 3) % 3)
            g.text(x0 + 3, y, " ".join(dots), "accent")
        elif self.password:
            shown = "•" * min(len(self.password), 24)
            g.text(x0 + 3, y, shown, "text")
            if lt.tm_sec % 2 == 0:
                g.set(x0 + 3 + len(shown), y, "▏", "accent")
        else:
            g.text(x0 + 3, y, "password", "line")
            if lt.tm_sec % 2 == 0:
                g.set(x0 + 2, y, "▏", "accent")
        if self.message:
            g.text((cols - len(self.message)) // 2, y + 2, self.message, "alert")

        # the bottom line: sessions in the middle, power in the right corner
        by = rows - 3
        names = [s["name"] for s in self.sessions]
        total = sum(len(n) for n in names) + 6 * (len(names) - 1)
        x = (cols - total) // 2
        for k, n in enumerate(names):
            on = k == self.sel
            hot = self.hover_kind == ("session", k)
            g.text(x, by, n, "text" if on else ("dim" if hot else "line"))
            if on:
                g.set(x - 2, by, "›", "accent")
            self.regions.append(Region(x - 2, by, x + len(n) - 1, by, "session", k))
            x += len(n) + 6
        x = cols - 4
        for k, label in enumerate(("shut down", "restart")):
            text = f"{label}?" if self.confirm and self.confirm[0] == label else label
            x -= len(text)
            hot = self.hover_kind == ("power", k) or (self.confirm and self.confirm[0] == label)
            g.text(x, by, text, "alert" if self.confirm and self.confirm[0] == label else ("dim" if hot else "line"))
            self.regions.append(Region(x, by, x + len(text) - 1, by, "power", k))
            x -= 4
        return g

    # ── input ─────────────────────────────────────────────────────────────
    def on_keys(self, s: str):
        i = 0
        while i < len(s):
            c = s[i]
            if c == "\x1b":                       # an escape sequence (arrows...) or Esc itself
                j = i + 1
                if j < len(s) and s[j] in "[O":
                    j += 1
                    while j < len(s) and not ("@" <= s[j] <= "~"):
                        j += 1
                    if s[i:j + 1] == "\x1b[Z":     # Shift+Tab
                        self.pick(self.sel - 1)
                    i = j + 1
                    continue
                self.password, self.message = "", ""     # Esc clears
            elif self.busy:
                pass
            elif c in "\r\n":
                self.submit()
            elif c in "\x7f\x08":
                self.password = self.password[:-1]
            elif c == "\x15":                     # Ctrl+U
                self.password = ""
            elif c == "\t":
                self.pick(self.sel + 1)
            elif c >= " ":
                self.password += c
                self.message = ""
            i += 1
        self.redraw()

    def on_mouse(self, b: int, x: int, y: int, press: bool):
        if b & 64:
            return
        hit = next((r for r in self.regions if r.hit(x, y)), None)
        if b & 32:                                   # motion: the same trail and ripples as the wallpaper
            kind = (hit.kind, hit.index) if hit else None
            if kind != self.hover_kind:
                self.hover_kind = kind
                self.redraw()
            if not hit:
                self.drop_dots(x, y)
                self.disturb(x, y)
            return
        if not press or (b & 3) != 0 or not hit:
            return
        if hit.kind == "session":
            self.pick(hit.index)
        else:
            label = ("shut down", "restart")[hit.index]
            if self.confirm and self.confirm[0] == label and time.time() < self.confirm[1]:
                self.power(label)
            else:
                self.confirm = (label, time.time() + CONFIRM_SECONDS)
        self.redraw()

    def pick(self, k: int):
        if self.sessions:
            self.sel = k % len(self.sessions)

    def power(self, label: str):
        if self.demo:
            self.message = f"(demo) would {label} now"
            return
        subprocess.Popen(["systemctl", "poweroff" if label == "shut down" else "reboot"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def submit(self):
        if not self.password or not self.sessions:
            return
        self.busy, self.message = True, ""
        password, session = self.password, self.sessions[self.sel]

        def work():
            if self.demo:
                time.sleep(0.8)
                self.result = (password == "sotto", "" if password == "sotto" else "Not quite. Try again.")
                return
            try:
                self.result = login(self.user, password, session)
            except (OSError, ValueError, KeyError) as e:
                self.result = (False, f"Can't reach the login service ({e.__class__.__name__})")

        threading.Thread(target=work, daemon=True).start()

    # ── loop ──────────────────────────────────────────────────────────────
    def tick(self):
        now = time.time()
        if self.leaving:
            if now >= self.leaving:
                raise SystemExit(0)
        elif self.result is not None:
            ok, msg = self.result
            self.result, self.busy = None, False
            if ok:
                self._save_last()
                self.password = ""
                try:
                    Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "sotto-greeter-ok").touch()
                except OSError:
                    pass
                # the screen dissolves to bare parchment, then the desktop takes over
                self.set_base(Grid(self.cols, self.rows), animate=True, speed=0.7)
                self.leaving = now + 0.9
            else:
                self.password, self.message = "", msg
                y = max(4, (self.rows - (bigfont().height + 16)) // 2 - 2) + bigfont().height + 6
                for x in range(self.cols // 2 - 20, self.cols // 2 + 20):    # the line shivers
                    self._loosen(x, y, now)
                self.redraw()
        if self.confirm and now >= self.confirm[1]:
            self.confirm = None
            self.redraw()
        sec = int(now)
        if sec != self.second and not self.fade and not self.leaving:
            self.second = sec                        # the caret blinks; the busy dots move
            self.redraw()
        elif self.busy and not self.fade:
            self.redraw()
        super().tick()

    def timeout(self) -> float:
        return 1 / W.FPS if (self.busy or self.leaving) else min(super().timeout(), 0.5)


def run(argv: list[str]) -> int:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    g = Greeter(demo="--demo" in argv or not os.environ.get("GREETD_SOCK"))
    try:
        tty.setraw(fd)                               # Ctrl+C is just a key here, not a way out
        g.run(fd)
    except SystemExit as e:
        return int(e.code or 0)
    except Exception:
        W.log_error()
        raise
    finally:
        g.write("\x1b[?1003l\x1b[?1006l\x1b[?7h\x1b[?25h\x1b[0m\x1b[?1049l")
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        try:
            os.unlink(W.SOCKET)
        except OSError:
            pass
    return 0
