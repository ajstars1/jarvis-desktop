"""Renders the README's pictures without touching the screen: the real wallpaper,
terminal, login screen and boot screen code, driven on a virtual clock with the
demo data, saved through grid.to_png and turned into GIFs with ffmpeg.

  .venv/bin/python demo/render.py [terminal|login|boot|social ...]   (default: all)

Writes docs/terminal.gif, docs/login.gif, docs/boot.gif and docs/social-preview.png.
"""
import io
import json
import os
import random
import select
import shutil
import subprocess
import sys
import tempfile
import time as _time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
for k in ("KITTY_LISTEN_ON", "KITTY_WINDOW_ID"):      # never reach the real kitty or dock from here
    os.environ.pop(k, None)
os.environ["SOTTO_GREETER_CONFIG"] = "/nonexistent"

from PIL import Image, ImageDraw  # noqa: E402

from sotto import bootsplash, greeter as G, wall as W  # noqa: E402
from sotto.art import BigFont, font_path  # noqa: E402
from sotto.grid import Grid, to_png  # noqa: E402

COLS, ROWS = 195, 54                     # 1366x768 at 7x14 cells, like the real wallpaper
FPS = 15
DOCS = REPO / "docs"
STATE = json.loads((REPO / "demo/state.json").read_text())
FONT = font_path()


class Clock:
    """A virtual clock, so effects last as long in the GIF as they do on screen."""

    def __init__(self):
        lt = _time.localtime()
        self.t = _time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 9, 41, 0, 0, 0, -1))

    def time(self):
        return self.t

    def localtime(self, t=None):
        return _time.localtime(self.t if t is None else t)

    def strftime(self, fmt, lt=None):
        return _time.strftime(fmt, lt if lt is not None else self.localtime())

    def __getattr__(self, name):
        return getattr(_time, name)


CLOCK = Clock()
W.time = G.time = CLOCK


class Film:
    """Frames on disk, then one GIF."""

    def __init__(self, name: str):
        self.name = name
        self.dir = Path(tempfile.mkdtemp(prefix=f"sotto-{name}-"))
        self.n = 0
        self.last = None

    def add(self, grid: Grid, cursor=None, hold: int = 1):
        path = self.dir / f"f{self.n:04d}.png"
        to_png(grid, str(path), FONT)
        if cursor:
            img = Image.open(path)
            draw_cursor(img, *cursor)
            img.save(path)
        self.last = path
        self.n += 1
        for _ in range(hold - 1):
            self.repeat()

    def repeat(self, times: int = 1):
        for _ in range(times):
            shutil.copy(self.last, self.dir / f"f{self.n:04d}.png")
            self.n += 1

    def save(self, fps: float = FPS, crop: str = ""):
        out = DOCS / f"{self.name}.gif"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", str(self.dir / "f%04d.png"),
                        "-vf", (f"crop={crop}," if crop else "") + "split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];"
                               "[b][p]paletteuse=dither=none:diff_mode=rectangle",
                        "-loop", "0", str(out)], check=True)
        shutil.rmtree(self.dir)
        print(f"wrote {out.relative_to(REPO)} ({out.stat().st_size / 1e6:.1f} MB, {self.n} frames)")


def draw_cursor(img: Image.Image, cx: int, cy: int):
    """An arrow, umber with a parchment outline, at cell (cx, cy)."""
    x, y = cx * 7 + 3, cy * 14 + 5
    pts = [(0, 0), (0, 17), (4, 13), (7, 20), (10, 19), (7, 12), (12, 12)]
    ImageDraw.Draw(img).polygon([(x + a, y + b) for a, b in pts], fill=(0x3D, 0x2C, 0x1F), outline=(0xF3, 0xEB, 0xDE))


def tick(w, dt: float = 1 / FPS):
    """What the wallpaper's own loop does between frames: time passes, effects expire."""
    CLOCK.t += dt
    now = CLOCK.t
    for i in [i for i, (_, born, life) in w.trail.items() if now - born >= life]:
        del w.trail[i]
    for i in [i for i, (born, life, _) in w.scatter.items() if now - born >= life]:
        del w.scatter[i]
    if getattr(w, "term", None):
        pump(w.term, 0.01)


def pump(t, seconds: float):
    end = _time.time() + seconds
    while True:
        r, _, _ = select.select([t.master], [], [], max(0.0, end - _time.time()))
        if r:
            while t.read():
                pass
        if _time.time() >= end:
            return


def wallpaper(state=STATE) -> W.Wall:
    w = W.Wall.__new__(W.Wall)
    w.cols, w.rows, w.out, w.rng = COLS, ROWS, io.BytesIO(), random.Random(3)
    w.trail, w.scatter, w.regions = {}, {}, []
    w.term, w.term_focused, w.term_dirty, w.drag, w.outer_modes = None, False, False, None, (False, False)
    w.last_cell, w.last_click, w.hover, w.say_text, w.say_until = (-1, -1), None, None, None, 0.0
    w.state, w.visible = state, True
    w.tell_dock = lambda msg: None              # no dock, no kitty: this is all off screen
    w.kitty_focus = lambda policy: None
    w.base = w.home()
    w.shown = w.compose()
    return w


def fade(film, src: Grid, dst: Grid, seconds: float, speed: float = 1.0, cursor=None):
    f = W.Fade(src, dst, random.Random(5), speed)
    for k in range(int(seconds * FPS)):
        frame = src.copy()
        f.apply(k / FPS, frame, src)
        film.add(frame, cursor)


def sweep(film, w, path, cursor_after=True):
    """Move the mouse along path (cells), the way kitty reports motion to the wallpaper."""
    for x, y in path:
        w.on_mouse(35, x, y, False)
        tick(w)
        w.shown = w.compose()
        film.add(w.shown, (x, y) if cursor_after else None)


def line(a, b, steps):
    return [(round(a[0] + (b[0] - a[0]) * k / steps), round(a[1] + (b[1] - a[1]) * k / steps)) for k in range(1, steps + 1)]


def demo_shell() -> str:
    """A plain bash with a short prompt, started in this repo."""
    d = Path(tempfile.mkdtemp(prefix="sotto-shell-"))
    (d / "rc").write_text(
        "PS1='\\[\\e[32m\\]sotto\\[\\e[0m\\] \\[\\e[33m\\]›\\[\\e[0m\\] '\n"
        f"cd {REPO}\n"
        "PROMPT_COMMAND='printf \"\\e]0;%s\\a\" \"~/sotto\"'\n")
    sh = d / "shell"
    sh.write_text(f"#!/bin/sh\nexec bash --noprofile --rcfile {d / 'rc'} -i\n")
    sh.chmod(0o755)
    return str(sh)


# ── the terminal inside the wallpaper ─────────────────────────────────────
def film_terminal():
    film = Film("terminal")
    w = wallpaper()
    film.add(w.shown, (170, 30), hold=8)
    sweep(film, w, line((170, 30), (118, 17), 10) + line((118, 17), (78, 15), 14) + line((78, 15), (40, 26), 10))

    os.environ["SHELL"] = demo_shell()
    before = w.shown.copy()
    w.open_term(16 * 7, 22 * 14)
    t = w.term
    t.resize(74, 12, COLS, ROWS)
    pump(t, 1.2)
    fade(film, before, w.compose(), 0.7, speed=0.6, cursor=(40, 26))

    def type_(text, cursor):
        for ch in text:
            t.send(ch.encode())
            pump(t, 0.03)
            tick(w)
            film.add(w.compose(), cursor)
        t.send(b"\r")
        for _ in range(6):
            pump(t, 0.08)
            tick(w)
            film.add(w.compose(), cursor)

    type_("git --no-pager log --oneline -6", (40, 26))
    film.repeat(12)
    type_("ls", (40, 26))
    film.repeat(10)

    # drag it by its label up over the clock: it shakes the wallpaper loose on the way
    x, y = t.x + 8, t.y
    sweep(film, w, line((40, 26), (x, y), 8))
    w.on_mouse(0, x, y, True)
    for nx, ny in line((x, y), (x + 92, y - 13), 22):
        w.on_mouse(32, nx, ny, True)
        tick(w)
        film.add(w.compose(), (nx, ny))
    w.on_mouse(0, x + 92, y - 13, False)
    film.repeat(6)

    # click the wallpaper: the terminal lets go of the keyboard and turns grey,
    # then the mouse runs through it and shakes its text loose like everything else
    w.on_mouse(0, 40, 44, True)
    w.on_mouse(0, 40, 44, False)
    sweep(film, w, line((x + 92, y - 13), (40, 44), 6) + line((40, 44), (130, 14), 16) + line((130, 14), (182, 18), 12))
    for _ in range(14):
        tick(w)
        film.add(w.compose(), (182, 18))
    film.repeat(10)
    t.close()
    film.save()


# ── the login screen, then the desktop ────────────────────────────────────
def film_login():
    film = Film("login")
    g = G.Greeter.__new__(G.Greeter)
    g.cols, g.rows, g.out, g.rng = COLS, ROWS, io.BytesIO(), random.Random(9)
    g.trail, g.scatter, g.regions, g.term, g.term_focused, g.last_cell = {}, {}, [], None, False, (-1, -1)
    g.user, g.name = "friend", "Friend"
    g.sessions, g.sel = G.find_sessions(["hyprland", "ubuntu"]), 0
    g.password, g.busy, g.message, g.confirm, g.hover_kind, g.demo = "", False, "", None, None, True
    g.base = g.home()
    blank = Grid(COLS, ROWS)
    fade(film, blank, g.compose(), 1.4, speed=1.0)
    g.shown = g.compose()
    film.add(g.shown, None, hold=6)

    def frame(cursor=None):
        g.base = g.home()
        tick(g)
        g.shown = g.compose()
        film.add(g.shown, cursor)

    for x, y in line((150, 40), (112, 16), 10) + line((112, 16), (80, 17), 12) + line((80, 17), (60, 30), 8):
        g.on_mouse(35, x, y, False)
        frame((x, y))
    for ch in "••••••••":
        g.password += "x"
        frame((60, 30))
        frame((60, 30))
    g.busy = True
    for _ in range(12):
        frame((60, 30))
    g.busy, g.password = False, ""
    fade(film, g.compose(), blank, 0.9, speed=0.7)
    film.add(blank, None, hold=4)
    w = wallpaper()
    fade(film, blank, w.compose(), 1.6, speed=1.0)
    film.add(w.compose(), None, hold=18)
    film.save()


# ── the boot screen ───────────────────────────────────────────────────────
def film_boot():
    film = Film("boot")
    bootsplash.greetings = lambda: {"boot": "Welcome back, Friend", "shutdown": "See you soon, Friend",
                                    "reboot": "Back in a moment", "updates": "Updating · please keep it on"}
    cycle = int((7 + 3.5 + 2) / 0.09)              # one sweep of the dots, in Plymouth frames (50 a second)
    for k in range(0, cycle, 3):
        path = film.dir / f"f{film.n:04d}.png"
        bootsplash.preview(path, frame=k)
        film.last, film.n = path, film.n + 1
    film.save(fps=50 / 3, crop="640:300:363:210")      # just the middle, where everything is


# ── the picture GitHub shows when the repo is shared ─────────────────────
def social():
    """Drawn at half size and scaled up 2x, so the pixel font stays crisp and
    readable when GitHub or Reddit show it small."""
    cols, rows = 91, 22                            # 637x308 -> 1274x616, on a 1280x640 card
    w = wallpaper(dict(STATE, projects=[]))
    w.cols, w.rows = cols, rows
    g = w.home()
    bf = BigFont()
    top = next(y for y in range(rows) if any(c in "█▀▄" for c in g.ch[y * cols:(y + 1) * cols]))
    g = Grid(cols, rows)
    top = 2
    bf.draw(g, (cols - bf.width("sotto")) // 2, top, "sotto", "dim")
    tag = "a living wallpaper for Hyprland  ·  a shell inside it"
    g.text((cols - len(tag)) // 2, top + bf.height + 2, tag, "dim")
    w.base, w.regions = g, []
    os.environ["SHELL"] = demo_shell()
    w.open_term(14 * 7, 12 * 14)
    t = w.term
    t.resize(58, 4, cols, rows)
    t.move_to(16, 12, cols, rows)
    pump(t, 1.2)
    t.send(b"ls\r")
    pump(t, 0.8)
    w.term_focused = True
    for x, y in line((88, 3), (66, 7), 10) + line((66, 7), (52, 6), 6):
        w.drop_dots(x, y)
        w.disturb(x, y)
        w.last_cell = (-1, -1)
    CLOCK.t += 0.15
    tmp = Path(tempfile.mkdtemp()) / "s.png"
    to_png(w.compose(), str(tmp), FONT)
    t.close()
    small = Image.open(tmp)
    draw_cursor(small, 52, 6)
    big = small.resize((small.width * 2, small.height * 2), Image.NEAREST)
    img = Image.new("RGB", (1280, 640), (0xEC, 0xE2, 0xD0))
    img.paste(big, ((1280 - big.width) // 2, (640 - big.height) // 2))
    img.save(DOCS / "social-preview.png")
    print("wrote docs/social-preview.png")


if __name__ == "__main__":
    jobs = {"terminal": film_terminal, "login": film_login, "boot": film_boot, "social": social}
    for name in sys.argv[1:] or list(jobs):
        jobs[name]()
