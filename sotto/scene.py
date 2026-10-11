"""The wallpaper: a quiet clock, one greeting line, and your recent
projects as a plain clickable list. Lots of empty space; nothing else."""
import time
from dataclasses import dataclass

from .art import BigFont
from .grid import Grid

LIST_W = 84          # width of the centred column, in cells


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


def greeting(name: str, hour: int) -> str:
    if 5 <= hour < 12:
        part = "morning"
    elif 12 <= hour < 17:
        part = "afternoon"
    elif 17 <= hour < 22:
        part = "evening"
    else:
        part = "night"
    return f"Good {part}, {name.title()}"


def build(state: dict, cols: int, rows: int, now: float | None = None,
          hover: int | None = None, say: str | None = None) -> tuple[Grid, list[Region]]:
    now = now or time.time()
    lt = time.localtime(now)
    g = Grid(cols, rows)
    regions: list[Region] = []
    bf = bigfont()

    projects = state.get("projects", [])[:6]
    block_h = bf.height + 4 + len(projects) * 2
    y = max(4, (rows - block_h) // 2 - 2)

    clock = time.strftime("%H:%M", lt)
    bf.draw(g, (cols - bf.width(clock)) // 2, y, clock, "dim")
    y += bf.height + 2

    line = say or f"{time.strftime('%A %d %B', lt)}  ·  {greeting(state.get('user', ''), lt.tm_hour)}"
    g.text((cols - len(line)) // 2, y, line, "hot" if say else "dim")
    y += 4

    x0 = (cols - LIST_W) // 2
    for n, p in enumerate(projects):
        on = hover == n
        when = p["claude_ago"] or p["commit_ago"]
        detail = p["branch"] + (f" · {p['dirty']} changed" if p["dirty"] else "")
        g.text(x0, y, "›" if on else " ", "hot")
        g.text(x0 + 3, y, p["name"].title(), "hot" if on else "amber", width=30)
        g.text(x0 + 36, y, detail, "dim", width=32)
        g.text(x0 + LIST_W - len(when), y, when, "dim")
        regions.append(Region(x0, y, x0 + LIST_W - 1, y, "project", n))
        y += 2
    return g, regions
