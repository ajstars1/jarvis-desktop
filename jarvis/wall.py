"""The live wallpaper. Runs inside `kitty +kitten panel --edge=background`.

Always on screen: a quiet clock, one greeting line and your recent projects
on light fresco parchment. Move the mouse over empty space and a faint trail
of dots follows it and fades. Click a project to open it; right-click
anywhere for the desktop menu. `python -m jarvis say "..."` shows a message
in place of the greeting for a few seconds.
"""
import json
import os
import random
import re
import select
import shlex
import signal
import socket
import struct
import fcntl
import subprocess
import sys
import termios
import threading
import time
import traceback
import tty

from . import collect
from .grid import Grid, ansi_diff
from .scene import build

FPS = 30
REFRESH_EVERY = 300            # re-read projects/system this often (seconds)
SAY_SECONDS = 8                # a `say` message stays this long
PIDFILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-wall.pid")
LOG = collect.CACHE / "wall.log"

MOUSE = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
DOTS = "·•∙"
MATRIX = "01"
# a trail dot ages through these colours, then disappears
TRAIL_COLORS = ["hot", "dim", "line", "faint"]


class Fade:
    """Home screen in/out: each changed cell flickers as a dot, then settles."""

    def __init__(self, src: Grid, dst: Grid, rng: random.Random, speed: float = 1.0):
        self.dst = dst
        self.rng = rng
        self.plan: dict[int, tuple[float, float]] = {}
        cols = dst.cols
        for i in range(len(dst.ch)):
            if src.ch[i] == dst.ch[i] and src.fg[i] == dst.fg[i] and src.bg[i] == dst.bg[i]:
                continue
            t0 = ((i % cols) / cols * 0.2 + rng.random() * 0.25) * speed
            self.plan[i] = (t0, t0 + (0.10 + rng.random() * 0.20) * speed)
        self.end = max((p[1] for p in self.plan.values()), default=0.0)

    def apply(self, t: float, out: Grid, src: Grid):
        rnd = self.rng.random
        for i, (t0, t1) in self.plan.items():
            if t < t0:
                out.ch[i], out.fg[i], out.bg[i] = src.ch[i], src.fg[i], src.bg[i]
            elif t < t1:
                out.ch[i], out.fg[i], out.bg[i] = DOTS[int(rnd() * 3)], "line" if rnd() < 0.6 else "dim", "bg"
            else:
                out.ch[i], out.fg[i], out.bg[i] = self.dst.ch[i], self.dst.fg[i], self.dst.bg[i]


class Wall:
    def __init__(self):
        self.out = sys.stdout.buffer
        self.flags: set[str] = set()
        self.rng = random.Random()
        self.cols, self.rows = self.size()
        self.base = Grid(self.cols, self.rows)     # what sits under the trail
        self.shown = self.base.copy()              # what is on screen
        self.visible = False
        self.fade: Fade | None = None
        self.fade_src: Grid | None = None
        self.fade_t0 = 0.0
        self.trail: dict[int, tuple[str, float, float]] = {}   # cell -> (char, born, life)
        self.state = self.load_state()
        self.state_mtime = self.mtime(collect.STATE)
        self.inbox_mtime = self.mtime(collect.INBOX)
        self.regions = []
        self.hover: int | None = None
        self.say_text: str | None = None
        self.say_until = 0.0
        self.hide_at = 0.0
        self.minute = -1
        self.collecting = False
        self.last_cell = (-1, -1)
        self.last_click = None
        self.next_refresh = 0.0

    # ── plumbing ──────────────────────────────────────────────────────────
    @staticmethod
    def size():
        s = os.get_terminal_size()
        return s.columns, s.lines

    @staticmethod
    def mtime(path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    def load_state(self) -> dict:
        try:
            return json.loads(collect.STATE.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def write(self, s: str):
        if s:
            self.out.write(s.encode())
            self.out.flush()

    def refresh_async(self):
        if self.collecting or os.environ.get("JARVIS_DEMO"):
            return                            # demo mode: show the given state.json as is
        self.collecting = True

        def work():
            try:
                collect.write(collect.collect())
            except Exception:
                log_error()
            finally:
                self.collecting = False

        threading.Thread(target=work, daemon=True).start()

    # ── frames ────────────────────────────────────────────────────────────
    def home(self) -> Grid:
        say = self.say_text if time.time() < self.say_until else None
        g, self.regions = build(self.state, self.cols, self.rows, time.time(), self.hover, say)
        return g

    def compose(self) -> Grid:
        """base + live trail dots."""
        g = self.base.copy()
        now = time.time()
        for i, (ch, born, life) in self.trail.items():
            k = min(len(TRAIL_COLORS) - 1, int((now - born) / life * len(TRAIL_COLORS)))
            if g.ch[i] == " ":
                g.ch[i], g.fg[i] = ch, TRAIL_COLORS[k]
        return g

    def present(self, frame: Grid, only=None):
        self.write(ansi_diff(self.shown, frame, only))
        self.shown = frame

    def set_base(self, new: Grid, animate: bool, speed: float = 1.0):
        if animate:
            self.fade_src = self.shown.copy()
            self.fade = Fade(self.fade_src, new, self.rng, speed)
            self.fade_t0 = time.time()
        self.base = new
        if not animate:
            self.present(self.compose())

    # ── show / hide ───────────────────────────────────────────────────────
    def show(self, text: str | None = None):
        now = time.time()
        if text:
            self.say_text, self.say_until = text, now + SAY_SECONDS
        if not self.visible:
            self.visible = True
            self.trail.clear()
            self.refresh_async()
        self.set_base(self.home(), animate=True)

    def hide(self):
        """The wallpaper never hides; kept so old callers stay harmless."""

    # ── input ─────────────────────────────────────────────────────────────
    def drop_dots(self, x: int, y: int):
        """Leave a few dots where the cursor passed; some drift down like rain."""
        if (x, y) == self.last_cell:
            return
        self.last_cell = (x, y)
        now = time.time()
        for _ in range(2):
            dx, dy = self.rng.randint(-1, 1), self.rng.randint(0, 1)
            cx, cy = x + dx, y + dy
            if 0 <= cx < self.cols and 0 <= cy < self.rows:
                ch = MATRIX[self.rng.randrange(2)] if self.rng.random() < 0.12 else DOTS[self.rng.randrange(3)]
                self.trail[cy * self.cols + cx] = (ch, now, self.rng.uniform(0.5, 1.1))

    def on_mouse(self, b: int, x: int, y: int, press: bool):
        if b & 64:                                   # wheel
            return
        if b & 32:                                   # motion
            hit = next((r for r in self.regions if r.hit(x, y)), None)
            if not hit:
                self.drop_dots(x, y)
            new = hit.index if hit else None
            if new != self.hover:
                self.hover = new
                self.set_base(self.home(), animate=False)
            return
        if not press:
            return
        if (b & 3) == 2:                             # right click: desktop menu
            subprocess.Popen([os.path.expanduser("~/.config/hypr/scripts/desktop-menu.sh")],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        elif (b & 3) == 0:
            hit = next((r for r in self.regions if r.hit(x, y)), None)
            if hit:
                self.open_project(hit.index)
                return
            now = time.time()
            last = self.last_click
            if last and now - last[0] < 0.45 and abs(x - last[1]) <= 2 and abs(y - last[2]) <= 1:
                self.last_click = None           # double-click on empty wallpaper: open the prompt here
                cw, ch = self.cell_px()
                self.tell_dock(f"prompt {x * cw} {y * ch}")
            else:
                self.last_click = (now, x, y)
                self.tell_dock("prompt-close")   # a single click elsewhere closes an open prompt

    def cell_px(self) -> tuple[int, int]:
        """Pixel size of one character cell, from the terminal (falls back to 7x14)."""
        try:
            rows, cols, xp, yp = struct.unpack("HHHH", fcntl.ioctl(sys.stdin.fileno(), termios.TIOCGWINSZ, b"\0" * 8))
            if xp and yp and cols and rows:
                return xp // cols, yp // rows
        except OSError:
            pass
        return 7, 14

    def tell_dock(self, msg: str):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
                s.sendto(msg.encode(), os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-dock.sock"))
        except OSError:
            pass

    def on_key(self, ch: str):
        if self.visible and ch in "123456":
            self.open_project(int(ch) - 1)


    def open_project(self, n: int):
        projects = self.state.get("projects", [])
        if n >= len(projects):
            return
        p = projects[n]
        cmds = p.get("open") or ["kitty --directory {path}"]
        in_hypr = bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))
        try:
            for c in cmds:
                c = c.format(path=shlex.quote(p["path"]))
                if in_hypr:
                    subprocess.Popen(["hyprctl", "dispatch", "exec", c], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.Popen(c, shell=True, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            log_error()

    def read_input(self, buf: str) -> str:
        pos = 0
        for m in MOUSE.finditer(buf):
            for ch in buf[pos:m.start()]:
                self.on_key(ch)
            self.on_mouse(int(m[1]), int(m[2]) - 1, int(m[3]) - 1, m[4] == "M")
            pos = m.end()
        rest = buf[pos:]
        cut = rest.find("\x1b[")
        if cut >= 0:                                 # keep a partial escape for the next read
            for ch in rest[:cut]:
                self.on_key(ch)
            return rest[cut:]
        for ch in rest:
            self.on_key(ch)
        return ""

    # ── main loop ─────────────────────────────────────────────────────────
    def tick(self):
        now = time.time()
        if "quit" in self.flags:
            raise SystemExit
        if "resize" in self.flags:
            self.flags.discard("resize")
            self.cols, self.rows = self.size()
            self.fade, self.trail = None, {}
            self.base = self.home() if self.visible else Grid(self.cols, self.rows)
            self.shown = Grid(self.cols, self.rows)
            self.write("\x1b[48;2;236;226;208m\x1b[2J")
            self.present(self.compose())
        if "toggle" in self.flags:
            self.flags.discard("toggle")
            self.refresh_async()

        m = self.mtime(collect.STATE)
        if m != self.state_mtime:
            self.state_mtime = m
            self.state = self.load_state()
            if self.visible and not self.fade:
                self.set_base(self.home(), animate=True, speed=0.6)
        m = self.mtime(collect.INBOX)
        if m != self.inbox_mtime:
            self.inbox_mtime = m
            try:
                self.show(json.loads(collect.INBOX.read_text()).get("text"))
            except (OSError, json.JSONDecodeError):
                pass

        if self.fade:
            t = now - self.fade_t0
            frame = self.shown.copy()
            self.fade.apply(t, frame, self.fade_src)
            self.present(frame, only=self.fade.plan.keys())
            if t >= self.fade.end:
                self.fade = None
            return

        if self.trail:
            dead = [i for i, (_, born, life) in self.trail.items() if now - born >= life]
            for i in dead:
                del self.trail[i]
            self.present(self.compose(), only=set(self.trail) | set(dead))

        if now >= self.next_refresh:
            self.next_refresh = now + REFRESH_EVERY
            self.refresh_async()
        if self.visible:
            minute = time.localtime(now).tm_min
            if minute != self.minute or (self.say_text and now >= self.say_until):
                self.minute = minute
                if self.say_text and now >= self.say_until:
                    self.say_text = None
                self.set_base(self.home(), animate=False)

    def timeout(self) -> float:
        return 1 / FPS if (self.fade or self.trail) else 1.0

    def run(self, fd: int):
        # any-motion mouse tracking stays on: motion only arrives when the pointer is over the bare desktop
        self.write("\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[?1003h\x1b[?1006h\x1b[48;2;236;226;208m\x1b[2J")
        self.show()
        pending = ""
        while True:
            r, _, _ = select.select([fd], [], [], self.timeout())
            if r:
                try:
                    data = os.read(fd, 4096).decode(errors="ignore")
                except OSError:
                    data = ""
                pending = self.read_input(pending + data)
            self.tick()


def log_error():
    try:
        collect.CACHE.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as f:
            f.write(time.strftime("%F %T ") + traceback.format_exc() + "\n")
    except OSError:
        pass


def run() -> int:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    wall = Wall()
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    signal.signal(signal.SIGUSR1, lambda *_: wall.flags.add("toggle"))
    signal.signal(signal.SIGTERM, lambda *_: wall.flags.add("quit"))
    signal.signal(signal.SIGHUP, lambda *_: wall.flags.add("quit"))
    signal.signal(signal.SIGWINCH, lambda *_: wall.flags.add("resize"))
    try:
        tty.setcbreak(fd)
        wall.run(fd)
    except (SystemExit, KeyboardInterrupt):
        pass
    except Exception:
        log_error()
        raise
    finally:
        wall.write("\x1b[?1003l\x1b[?1006l\x1b[?7h\x1b[?25h\x1b[0m\x1b[?1049l")
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        try:
            os.unlink(PIDFILE)
        except OSError:
            pass
    return 0
