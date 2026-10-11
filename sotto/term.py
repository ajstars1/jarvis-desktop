"""A shell inside the wallpaper: type /terminal in the wallpaper prompt.

The wallpaper is itself a terminal (kitty), so this runs your shell in a pty,
lets pyte keep its screen, and the wall draws that screen as a card in its own
font and colours. Drag the top bar to move the card and the corner to resize
it; × closes it (or type `exit`).
"""
import fcntl
import os
import pty
import signal
import struct
import subprocess
import termios

import pyte

PAPER = "#f3ebde"          # the card, a shade lighter than the wallpaper
# ANSI colours for a light background (white stays readable, black is the light one)
ANSI = {
    "black": "#e2d4bd", "red": "#a9532f", "green": "#6f7d3c", "brown": "#a7783f",
    "blue": "#4f6d82", "magenta": "#8c5b68", "cyan": "#4f7f72", "white": "#8f7759",
    "brightblack": "#a08a6c", "brightred": "#c0623c", "brightgreen": "#82913f", "brightbrown": "#b98a4c",
    "brightblue": "#62829a", "brightmagenta": "#a1707c", "brightcyan": "#629486", "brightwhite": "#3d2c1f",
}
DECCKM = 1 << 5            # pyte keeps private modes shifted by 5: application cursor keys
PASTE = 2004 << 5          # bracketed paste
# don't let programs in the shell find (and drive) the wallpaper's own kitty
HIDE_ENV = ("KITTY_WINDOW_ID", "KITTY_LISTEN_ON", "KITTY_PID", "KITTY_PUBLIC_KEY", "TERMINFO", "TERM_PROGRAM")


def color(c: str, default: str) -> str:
    if c == "default":
        return default
    if c in ANSI:
        return ANSI[c]
    return "#" + c if len(c) == 6 else default


class Term:
    MIN_COLS, MIN_ROWS = 30, 6

    def __init__(self, x: int, y: int, cols: int = 80, rows: int = 20, cwd: str | None = None):
        self.x, self.y = x, y              # top-left cell of the card (its title bar)
        self.cols, self.rows = cols, rows
        self.screen = pyte.HistoryScreen(cols, rows, history=3000, ratio=0.5)
        self.screen.write_process_input = self.send_text     # answers to "where is the cursor?" etc.
        self.stream = pyte.ByteStream(self.screen)
        self.master, slave = pty.openpty()
        self._winsize()
        env = {k: v for k, v in os.environ.items() if k not in HIDE_ENV}
        env.update(TERM="xterm-256color", COLORTERM="truecolor")
        self.shell = os.environ.get("SHELL") or "/bin/bash"
        # setsid -c: a new session with the pty as its controlling terminal, so Ctrl+C and jobs work
        self.proc = subprocess.Popen(["setsid", "-c", self.shell], stdin=slave, stdout=slave, stderr=slave,
                                     cwd=cwd or os.path.expanduser("~"), env=env, close_fds=True)
        os.close(slave)
        os.set_blocking(self.master, False)
        self.alive = True
        self.hover_close = False

    # ── geometry ────────────────────────────────────────────────────────
    @property
    def width(self) -> int:                # card size in cells: a cell of padding each side,
        return self.cols + 2               # the title bar on top and a row at the bottom

    @property
    def height(self) -> int:
        return self.rows + 2

    def part(self, x: int, y: int) -> str | None:
        if not (self.x <= x < self.x + self.width and self.y <= y < self.y + self.height):
            return None
        if y == self.y:
            return "close" if self.x + self.width - 4 <= x <= self.x + self.width - 2 else "title"
        if y == self.y + self.height - 1 and x >= self.x + self.width - 2:
            return "corner"
        return "body"

    def cells(self, cols: int, rows: int) -> set[int]:
        return {yy * cols + xx
                for yy in range(max(0, self.y), min(rows, self.y + self.height))
                for xx in range(max(0, self.x), min(cols, self.x + self.width))}

    def move_to(self, x: int, y: int, cols: int, rows: int):
        self.x = max(0, min(cols - self.width, x))
        self.y = max(0, min(rows - self.height, y))

    def resize(self, cols: int, rows: int, max_cols: int, max_rows: int):
        cols = max(self.MIN_COLS, min(cols, max_cols - self.x - 2))
        rows = max(self.MIN_ROWS, min(rows, max_rows - self.y - 2))
        if (cols, rows) != (self.cols, self.rows):
            self.cols, self.rows = cols, rows
            self.screen.resize(rows, cols)
            self._winsize()

    def _winsize(self):
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, self.cols, 0, 0))

    # ── the shell ───────────────────────────────────────────────────────
    def read(self) -> bool:
        """Feed whatever the shell printed into the screen. False when nothing came."""
        try:
            data = os.read(self.master, 65536)
        except BlockingIOError:
            return False
        except OSError:                    # EIO: the shell has gone
            data = b""
        if not data:
            self.alive = False
            return True
        self.stream.feed(data)
        return True

    def send(self, data: bytes):
        if self.screen.history.position < self.screen.history.size:
            self.screen.next_page()        # typing jumps back to the bottom, like any terminal
        while data and self.alive:
            try:
                n = os.write(self.master, data)
                data = data[n:]
            except BlockingIOError:
                continue
            except OSError:
                self.alive = False

    def send_text(self, text: str):
        self.send(text.encode())

    def scroll(self, up: bool):
        (self.screen.prev_page if up else self.screen.next_page)()

    def close(self):
        if self.alive:
            try:
                os.killpg(self.proc.pid, signal.SIGHUP)   # the whole session, like closing a window
            except OSError:
                pass
        self.alive = False
        try:
            os.close(self.master)
        except OSError:
            pass
        try:
            self.proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass

    def title(self) -> str:
        t = (self.screen.title or "").strip()
        return t or os.path.basename(self.shell)

    # ── drawing ─────────────────────────────────────────────────────────
    def draw(self, g, focused: bool):
        X, Y, w = self.x, self.y, self.width
        g.fill(X, Y, w, 1, " ", "dim", "surface")
        g.text(X + 2, Y, self.title(), "text" if focused else "dim", "surface", width=w - 7)
        g.set(X + w - 3, Y, "×", "alert" if self.hover_close else "dim", "surface")
        g.fill(X, Y + 1, w, self.height - 1, " ", "text", PAPER)
        g.set(X + w - 1, Y + self.height - 1, "┘", "line", PAPER)       # resize grip
        scr = self.screen
        cur = scr.cursor
        show_cursor = not cur.hidden and scr.history.position >= scr.history.size
        cols = g.cols
        for r in range(self.rows):
            line = scr.buffer[r]
            gy = Y + 1 + r
            if not 0 <= gy < g.rows:
                continue
            for c in range(self.cols):
                gx = X + 1 + c
                if not 0 <= gx < cols:
                    continue
                cell = line[c]
                ch = cell.data                 # "" is the right half of a wide character
                if ch and (ord(ch[0]) < 32 or ord(ch[0]) == 127):
                    ch = " "                   # never pass control characters to the outer terminal
                fg, bg = color(cell.fg, "text"), color(cell.bg, PAPER)
                if cell.reverse:
                    fg, bg = bg, fg
                if show_cursor and r == cur.y and c == cur.x:
                    fg, bg = (PAPER, "text") if focused else (fg, "line")
                i = gy * cols + gx
                g.ch[i], g.fg[i], g.bg[i] = ch, fg, bg
