"""Lays out one wallpaper frame from state.json: headline, status line,
project tiles, the mascot with its speech bubble, and a faint field of dots
and code behind everything. Returns the frame and its clickable regions."""
import random
import textwrap
import time
from dataclasses import dataclass

from .art import BigFont, draw_sprite, pup
from .grid import Grid

TOP = 3          # rows 0-1 sit under the 22px Waybar
MARGIN = 5
TILE_W, TILE_H, TILE_GAP = 56, 6, 2
BUBBLE_W = 58
MASCOT_W = 32


@dataclass
class Region:
    x0: int
    y0: int
    x1: int
    y1: int
    kind: str
    index: int

    def hit(self, x: int, y: int) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1


_bigfont = None


def bigfont() -> BigFont:
    global _bigfont
    if _bigfont is None:
        _bigfont = BigFont()
    return _bigfont


def texture(g: Grid, tokens: list[str], seed: int):
    """Sparse dots and a few fragments of your own code, barely visible, only in
    empty space so nothing sits on top of the content. Seeded by the day, so it
    stays put instead of flickering."""
    rng = random.Random(seed)
    cols, rows = g.cols, g.rows

    def free(x, y, w):
        if y < TOP or y >= rows - 1 or x < 1 or x + w >= cols - 1:
            return False
        return all(g.ch[yy * cols + xx] == " " and g.bg[yy * cols + xx] == "bg"
                   for yy in (y - 1, y, y + 1) for xx in range(x - 2, x + w + 2))

    for t in tokens[:14]:
        for _ in range(20):
            x, y = rng.randrange(1, max(2, cols - len(t) - 1)), rng.randrange(TOP, rows - 1)
            if free(x, y, len(t)):
                g.text(x, y, t, "faint")
                break
    for i in range(cols * rows):
        if g.ch[i] == " " and g.bg[i] == "bg" and i // cols >= TOP and rng.random() < 0.012:
            g.ch[i], g.fg[i] = "·", "faint"


def tile(g: Grid, x: int, y: int, n: int, p: dict, hover: bool):
    edge = "hot" if hover else "line"
    g.box(x, y, TILE_W, TILE_H, edge, "bg")
    title = f" {n:02d} {p['name']} "
    g.text(x + 2, y, title, "bg" if hover else "amber", "amber" if hover else "bg", width=TILE_W - 10)
    if p["dirty"]:
        g.text(x + TILE_W - 6, y, " * ", "alert", "bg")
    inner = TILE_W - 4
    g.text(x + 2, y + 1, p["display_path"], "dim", width=inner)
    branch = f"BRANCH {p['branch']}"
    g.text(x + 2, y + 2, branch, "amber", width=inner)
    if p["dirty"]:
        g.text(x + 3 + len(branch), y + 2, f"· {p['dirty']} CHANGED", "alert", width=inner - len(branch) - 1)
    when = p["commit_ago"]
    msg_w = inner - len(when) - 2
    g.text(x + 2, y + 3, f"\"{p['commit']}\"" if p["commit"] else "NO COMMITS YET", "hot", width=msg_w)
    g.text(x + TILE_W - 2 - len(when), y + 3, when, "dim")
    if p["claude_ago"]:
        g.text(x + 2, y + 4, f"CLAUDE SESSION {p['claude_ago']}", "dim", width=inner)


def bubble(g: Grid, x: int, y: int, lines: list[str], talking: bool) -> int:
    """Speech bubble with a tail pointing down to the mascot. Returns its height."""
    wrapped = []
    for line in lines:
        wrapped += textwrap.wrap(line, BUBBLE_W - 6) or [""]
    h = len(wrapped) + 2
    g.box(x, y, BUBBLE_W, h, "amber" if talking else "dim", "bg")
    for k, line in enumerate(wrapped):
        g.text(x + 3, y + 1 + k, ("> " if k == 0 else "  ") + line, "amber" if k == 0 else "hot")
    tail_x = x + BUBBLE_W - 14
    g.set(tail_x, y + h - 1, "┬", "amber" if talking else "dim")
    g.set(tail_x, y + h, "│", "amber" if talking else "dim")
    return h + 1


def build(state: dict, cols: int, rows: int, now: float | None = None,
          hover: int | None = None, eyes: str | None = None, mouth: str = "smile",
          say: str | None = None) -> tuple[Grid, list[Region]]:
    now = now or time.time()
    lt = time.localtime(now)
    seed = int(time.strftime("%Y%m%d", lt))
    g = Grid(cols, rows)
    regions: list[Region] = []
    bf = bigfont()

    # headline: big pixel letters
    y = TOP + 1
    for line in state.get("headline", ["HELLO,", state.get("user", "") + "."]):
        bf.draw(g, MARGIN, y, line, "amber")
        y += bf.height + 1

    # status line
    s = state.get("system", {})
    parts = [time.strftime("%a %d %b %Y", lt).upper(), time.strftime("%H:%M", lt),
             f"RAM {s.get('ram', '?')}%", f"DISK {s.get('disk', '?')}%"]
    if s.get("temp") is not None:
        parts.append(f"CPU {s['temp']}°C")
    parts.append(f"UP {s.get('uptime', '?')}")
    x = MARGIN
    for k, part in enumerate(parts):
        if k:
            x += g.text(x, y + 1, "  ·  ", "line")
        hot = part.startswith("RAM") and s.get("ram", 0) >= 85
        x += g.text(x, y + 1, part, "alert" if hot else ("hot" if k == 1 else "dim"))

    # project tiles, two columns
    py = y + 4
    g.text(MARGIN, py, "RECENT PROJECTS ", "amber")
    g.text(MARGIN + 16, py, "─" * (TILE_W * 2 + TILE_GAP - 16), "line")
    py += 2
    for n, p in enumerate(state.get("projects", [])[:6]):
        cx = MARGIN + (n % 2) * (TILE_W + TILE_GAP)
        cy = py + (n // 2) * (TILE_H + 1)
        if cy + TILE_H > rows - 3:
            break
        tile(g, cx, cy, n + 1, p, hover == n)
        regions.append(Region(cx, cy, cx + TILE_W - 1, cy + TILE_H - 1, "project", n))

    # mascot and bubble, right side
    mood = state.get("mood", "happy")
    mx = cols - MASCOT_W - 10
    lines = [say] if say else state.get("messages", [])
    bx = cols - BUBBLE_W - 4
    bh = bubble(g, bx, TOP + 2, lines, talking=bool(say))
    my = max(TOP + 2 + bh, rows // 2 - 6)
    face = eyes or {"happy": "open", "worried": "worried", "sleepy": "sleep"}.get(mood, "open")
    draw_sprite(g, mx, my, pup(face, mouth if mood != "sleepy" or say else "flat"))
    if mood == "sleepy" and not say:
        g.text(mx + MASCOT_W - 2, my - 1, "z", "dim")
        g.text(mx + MASCOT_W, my - 2, "Z", "amber")
    g.text(mx + 9, my + 15, "B Y T E", "dim")
    regions.append(Region(mx, my, mx + MASCOT_W - 1, my + 13, "mascot", 0))

    # footer
    hint = "CLICK A PROJECT TO OPEN IT  ·  RIGHT-CLICK OR SUPER+H TO VANISH  ·  SUPER+F1 KEYS"
    g.text(MARGIN, rows - 2, hint, "line")
    texture(g, state.get("tokens", []), seed)
    return g, regions
