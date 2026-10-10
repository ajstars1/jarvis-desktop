"""The live wallpaper. Runs inside `kitty +kitten panel --edge=background`.

Default state is a pure black, empty screen. It materializes out of thin air
when summoned: dots appear, scramble through fragments of your own code, and
lock into place. It vanishes the same way.

Summon:  click empty desktop · SUPER+H (SIGUSR1) · `python -m jarvis say "..."`
Vanish:  right-click · SUPER+H again · 45 s without the mouse over it
Inside:  click a project tile to open it · click BYTE to hear it again
"""
import json
import os
import random
import re
import select
import shlex
import signal
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
GREET_SECONDS = 12      # login greeting stays this long, then fades to black
IDLE_HIDE = 45          # vanish after this long with no mouse movement over it
PIDFILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-wall.pid")
LOG = collect.CACHE / "wall.log"

MOUSE = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
GLYPHS = "01·:;+*=<>/\\|#%&$@!?{}[]()_-~^"
DOT_GLYPHS = "·•▪"
BLOCKS = set("▀▄█")


class Transition:
    """Cell-by-cell materialize/dissolve between two frames:
    a dot appears, it scrambles through glyphs, then locks with a hot flash."""

    def __init__(self, src: Grid, dst: Grid, tokens: list[str], rng: random.Random, speed: float = 1.0):
        self.dst = dst
        self.rng = rng
        self.pool = ("".join(tokens)[:3000] + GLYPHS) or GLYPHS
        self.plan: dict[int, tuple[float, float, float]] = {}
        cols = dst.cols
        for i in range(len(dst.ch)):
            if src.ch[i] == dst.ch[i] and src.fg[i] == dst.fg[i] and src.bg[i] == dst.bg[i]:
                continue
            t0 = ((i % cols) / cols * 0.35 + rng.random() * 0.45) * speed
            t1 = t0 + (0.06 + rng.random() * 0.10) * speed
            t2 = t1 + (0.12 + rng.random() * 0.40) * speed
            self.plan[i] = (t0, t1, t2)
        self.end = max((p[2] for p in self.plan.values()), default=0.0) + 0.14

    def apply(self, t: float, out: Grid, src: Grid):
        rnd = self.rng.random
        pool, npool = self.pool, len(self.pool)
        for i, (t0, t1, t2) in self.plan.items():
            if t < t0:
                out.ch[i], out.fg[i], out.bg[i] = src.ch[i], src.fg[i], src.bg[i]
            elif t < t1:
                out.ch[i], out.fg[i], out.bg[i] = DOT_GLYPHS[int(rnd() * 3)], "dim", "bg"
            elif t < t2:
                blocky = self.dst.ch[i] in BLOCKS or src.ch[i] in BLOCKS
                out.ch[i] = DOT_GLYPHS[int(rnd() * 3)] if blocky else pool[int(rnd() * npool)]
                out.fg[i] = "amber" if rnd() < 0.25 else "dim"
                out.bg[i] = "bg"
            else:
                out.ch[i], out.bg[i] = self.dst.ch[i], self.dst.bg[i]
                fresh = t < t2 + 0.12 and self.dst.ch[i] != " "
                out.fg[i] = "hot" if fresh else self.dst.fg[i]


class Wall:
    def __init__(self):
        self.out = sys.stdout.buffer
        self.flags: set[str] = set()
        self.rng = random.Random()
        self.cols, self.rows = self.size()
        self.blank = Grid(self.cols, self.rows)
        self.shown = self.blank.copy()          # what is on screen right now
        self.visible = False
        self.trans: Transition | None = None
        self.trans_src: Grid | None = None
        self.trans_t0 = 0.0
        self.state = self.load_state()
        self.state_mtime = self.mtime(collect.STATE)
        self.inbox_mtime = self.mtime(collect.INBOX)
        self.regions = []
        self.hover: int | None = None
        self.say_text: str | None = None
        self.talk_until = 0.0
        self.hide_at = 0.0
        self.next_blink = time.time() + 5
        self.blink_until = 0.0
        self.minute = -1
        self.collecting = False

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

    def mouse_mode(self, motion: bool):
        self.write("\x1b[?1003h" if motion else "\x1b[?1003l")

    def refresh_async(self):
        """Run the collector off the UI thread; the state.json watcher picks up the result."""
        if self.collecting:
            return
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
    def target(self) -> Grid:
        now = time.time()
        talking = now < self.talk_until
        mouth = ("talk" if int(now * 6) % 2 else "smile") if talking else "smile"
        eyes = "blink" if now < self.blink_until else None
        g, self.regions = build(self.state, self.cols, self.rows, now, self.hover, eyes, mouth,
                                self.say_text if (self.say_text and now < self.hide_at) else None)
        return g

    def start(self, dst: Grid, speed: float = 1.0):
        self.trans_src = self.shown.copy()
        self.trans = Transition(self.trans_src, dst, self.state.get("tokens", []), self.rng, speed)
        self.trans_t0 = time.time()

    def redraw(self):
        """Instant update (hover, blink, clock): no animation, only changed cells."""
        if self.trans:
            return
        g = self.target()
        self.write(ansi_diff(self.shown, g))
        self.shown = g

    # ── show / hide ───────────────────────────────────────────────────────
    def show(self, reason: str, text: str | None = None):
        now = time.time()
        if text:
            self.say_text = text
            self.talk_until = now + min(5.0, 1.0 + 0.05 * len(text))
        self.hide_at = now + (GREET_SECONDS if reason == "login" else IDLE_HIDE)
        if not self.visible:
            self.visible = True
            self.mouse_mode(True)
            self.refresh_async()
        self.start(self.target())

    def hide(self):
        if not self.visible:
            return
        self.visible = False
        self.hover = None
        self.say_text = None
        self.mouse_mode(False)
        self.start(self.blank, speed=0.6)

    # ── input ─────────────────────────────────────────────────────────────
    def on_mouse(self, b: int, x: int, y: int, press: bool):
        if b & 64:                                   # wheel
            return
        motion = bool(b & 32)
        button = b & 3
        if motion:
            if not self.visible:
                return
            self.hide_at = max(self.hide_at, time.time() + IDLE_HIDE)
            hit = next((r for r in self.regions if r.hit(x, y)), None)
            new = hit.index if hit and hit.kind == "project" else None
            if new != self.hover:
                self.hover = new
                self.redraw()
            return
        if not press:
            return
        if button == 2:                              # right click: vanish
            self.hide()
        elif button == 0:
            if not self.visible:
                self.show("click")
                return
            hit = next((r for r in self.regions if r.hit(x, y)), None)
            if hit is None:
                self.hide()
            elif hit.kind == "project":
                self.open_project(hit.index)
            elif hit.kind == "mascot":
                msgs = self.state.get("messages", [])
                self.show("say", self.rng.choice(msgs) if msgs else "WOOF.")

    def on_key(self, ch: str):
        if ch in "123456" and self.visible:
            self.open_project(int(ch) - 1)
        elif ch in ("h", "\x1b"):
            self.hide()

    def open_project(self, n: int):
        projects = self.state.get("projects", [])
        if n >= len(projects):
            return
        p = projects[n]
        cmds = p.get("open") or ["kitty --directory {path}"]
        in_hypr = bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))
        try:
            if in_hypr:
                subprocess.run(["hyprctl", "dispatch", "workspace", "emptym"], capture_output=True, timeout=3)
            for c in cmds:
                c = c.format(path=shlex.quote(p["path"]))
                if in_hypr:
                    subprocess.Popen(["hyprctl", "dispatch", "exec", c], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.Popen(c, shell=True, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            log_error()
        self.hide()

    def read_input(self, buf: str) -> str:
        pos = 0
        for m in MOUSE.finditer(buf):
            for ch in buf[pos:m.start()]:
                self.on_key(ch)
            self.on_mouse(int(m[1]), int(m[2]) - 1, int(m[3]) - 1, m[4] == "M")
            pos = m.end()
        rest = buf[pos:]
        if "\x1b[" in rest:                          # keep a partial escape for next read
            cut = rest.index("\x1b[")
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
            self.blank = Grid(self.cols, self.rows)
            self.shown = self.blank.copy()
            self.trans = None
            self.write("\x1b[48;2;0;0;0m\x1b[2J")
            if self.visible:
                self.redraw()
        if "toggle" in self.flags:
            self.flags.discard("toggle")
            self.hide() if self.visible else self.show("hotkey")

        m = self.mtime(collect.STATE)
        if m != self.state_mtime:
            self.state_mtime = m
            self.state = self.load_state()
            if self.visible:
                self.start(self.target())            # only the changed cells re-assemble
        m = self.mtime(collect.INBOX)
        if m != self.inbox_mtime:
            self.inbox_mtime = m
            try:
                self.show("say", json.loads(collect.INBOX.read_text()).get("text"))
            except (OSError, json.JSONDecodeError):
                pass

        if self.trans:
            t = now - self.trans_t0
            frame = self.shown.copy()
            self.trans.apply(t, frame, self.trans_src)
            self.write(ansi_diff(self.shown, frame, only=self.trans.plan.keys()))
            self.shown = frame
            if t >= self.trans.end:
                self.trans = None
            return

        if not self.visible:
            return
        if now >= self.hide_at:
            self.hide()
            return
        changed = False
        if now >= self.next_blink:
            self.blink_until = now + 0.14
            self.next_blink = now + self.rng.uniform(3.5, 7.0)
            changed = True
        elif self.blink_until and now >= self.blink_until:
            self.blink_until = 0.0
            changed = True
        if now < self.talk_until + 0.2:
            changed = True
        minute = time.localtime(now).tm_min
        if minute != self.minute:
            self.minute = minute
            changed = True
        if changed:
            self.redraw()

    def timeout(self) -> float:
        if self.trans or time.time() < self.talk_until + 0.2:
            return 1 / FPS
        if self.visible:
            return max(0.03, min(1.0, self.next_blink - time.time(), self.blink_until - time.time() if self.blink_until else 1.0))
        return 1.0

    def run(self, fd: int):
        self.write("\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[?1000h\x1b[?1006h\x1b[48;2;0;0;0m\x1b[2J")
        if not collect.STATE.exists():
            collect.write(collect.collect())
            self.state = self.load_state()
            self.state_mtime = self.mtime(collect.STATE)
        login_at = time.time() + 0.6
        pending = ""
        while True:
            if login_at and time.time() >= login_at:
                login_at = 0
                self.show("login")
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
        wall.write("\x1b[?1003l\x1b[?1000l\x1b[?1006l\x1b[?7h\x1b[?25h\x1b[0m\x1b[?1049l")
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        try:
            os.unlink(PIDFILE)
        except OSError:
            pass
    return 0
