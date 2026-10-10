"""A character grid shared by both outputs: ANSI escape codes for the live
wallpaper in kitty, and a PNG for previews."""

PALETTE = {
    # fresco palette, taken from the old ceiling-painting wallpaper
    "bg": (0x1A, 0x13, 0x0D),        # deep umber: the whole wallpaper at rest
    "faint": (0x2A, 0x1F, 0x16),
    "surface": (0x2F, 0x21, 0x16),
    "line": (0x44, 0x3B, 0x2B),
    "dim": (0x86, 0x6C, 0x52),
    "amber": (0xD6, 0xC3, 0xA5),     # cream text (key kept for compatibility)
    "hot": (0xC9, 0xA2, 0x6B),       # ochre gold accent
    "alert": (0xB8, 0x61, 0x3D),     # terracotta
}
SGR_FG = {k: f"\x1b[38;2;{r};{g};{b}m" for k, (r, g, b) in PALETTE.items()}
SGR_BG = {k: f"\x1b[48;2;{r};{g};{b}m" for k, (r, g, b) in PALETTE.items()}

BOX = {"tl": "┌", "tr": "┐", "bl": "└", "br": "┘", "h": "─", "v": "│"}


class Grid:
    __slots__ = ("cols", "rows", "ch", "fg", "bg")

    def __init__(self, cols: int, rows: int, bg: str = "bg"):
        self.cols, self.rows = cols, rows
        n = cols * rows
        self.ch = [" "] * n
        self.fg = ["amber"] * n
        self.bg = [bg] * n

    def copy(self) -> "Grid":
        g = Grid.__new__(Grid)
        g.cols, g.rows = self.cols, self.rows
        g.ch, g.fg, g.bg = self.ch[:], self.fg[:], self.bg[:]
        return g

    def set(self, x: int, y: int, ch: str, fg: str | None = None, bg: str | None = None):
        if 0 <= x < self.cols and 0 <= y < self.rows:
            i = y * self.cols + x
            self.ch[i] = ch
            if fg:
                self.fg[i] = fg
            if bg:
                self.bg[i] = bg

    def text(self, x: int, y: int, s: str, fg: str = "amber", bg: str | None = None, width: int | None = None) -> int:
        if width is not None and len(s) > width:
            s = s[: max(0, width - 1)] + "…"
        for k, c in enumerate(s):
            self.set(x + k, y, c, fg, bg)
        return len(s)

    def fill(self, x: int, y: int, w: int, h: int, ch: str = " ", fg: str | None = None, bg: str | None = None):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.set(xx, yy, ch, fg, bg)

    def box(self, x: int, y: int, w: int, h: int, fg: str = "line", bg: str | None = None):
        self.fill(x + 1, y + 1, w - 2, h - 2, " ", fg, bg)
        for xx in range(x + 1, x + w - 1):
            self.set(xx, y, BOX["h"], fg, bg)
            self.set(xx, y + h - 1, BOX["h"], fg, bg)
        for yy in range(y + 1, y + h - 1):
            self.set(x, yy, BOX["v"], fg, bg)
            self.set(x + w - 1, yy, BOX["v"], fg, bg)
        self.set(x, y, BOX["tl"], fg, bg)
        self.set(x + w - 1, y, BOX["tr"], fg, bg)
        self.set(x, y + h - 1, BOX["bl"], fg, bg)
        self.set(x + w - 1, y + h - 1, BOX["br"], fg, bg)


def ansi_diff(prev: Grid | None, cur: Grid, only=None) -> str:
    """Escape codes that turn `prev` into `cur` on screen, touching only cells
    that changed. `only` limits the check to a set of cell indices."""
    out = []
    last_fg = last_bg = None
    cursor = -1
    cols = cur.cols
    indices = range(len(cur.ch)) if only is None else sorted(only)
    for i in indices:
        c, f, b = cur.ch[i], cur.fg[i], cur.bg[i]
        if prev is not None and prev.ch[i] == c and prev.fg[i] == f and prev.bg[i] == b:
            continue
        if cursor != i:
            y, x = divmod(i, cols)
            out.append(f"\x1b[{y + 1};{x + 1}H")
        if f != last_fg:
            out.append(SGR_FG[f])
            last_fg = f
        if b != last_bg:
            out.append(SGR_BG[b])
            last_bg = b
        out.append(c)
        cursor = i + 1 if (i + 1) % cols else -1
    if not out:
        return ""
    # synchronized update: kitty shows the frame all at once, no tearing
    return "\x1b[?2026h" + "".join(out) + "\x1b[?2026l"


def to_png(grid: Grid, path: str, font_path: str, cw: int = 7, chh: int = 14):
    """Render the grid like kitty would, for previews. Box and block characters
    are drawn as exact pixels, the way kitty draws them itself."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (grid.cols * cw, grid.rows * chh), PALETTE["bg"])
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    font = ImageFont.truetype(font_path, 11)
    hx, hy = cw // 2, chh // 2
    for i, c in enumerate(grid.ch):
        y, x = divmod(i, grid.cols)
        px, py = x * cw, y * chh
        fg, bg = PALETTE[grid.fg[i]], PALETTE[grid.bg[i]]
        if grid.bg[i] != "bg":
            d.rectangle([px, py, px + cw - 1, py + chh - 1], fill=bg)
        if c == " ":
            continue
        if c == "█":
            d.rectangle([px, py, px + cw - 1, py + chh - 1], fill=fg)
        elif c == "▀":
            d.rectangle([px, py, px + cw - 1, py + hy - 1], fill=fg)
        elif c == "▄":
            d.rectangle([px, py + hy, px + cw - 1, py + chh - 1], fill=fg)
        elif c in "─┌┐└┘│":
            if c in "─┌└":
                d.line([px + (hx if c != "─" else 0), py + hy, px + cw - 1, py + hy], fill=fg)
            if c in "─┐┘":
                d.line([px, py + hy, px + (hx if c != "─" else cw - 1), py + hy], fill=fg)
            if c in "│┌┐":
                d.line([px + hx, py + (hy if c != "│" else 0), px + hx, py + chh - 1], fill=fg)
            if c in "│└┘":
                d.line([px + hx, py, px + hx, py + (hy if c != "│" else chh - 1)], fill=fg)
        else:
            d.text((px, py), c, font=font, fill=fg)
    img.save(path)
