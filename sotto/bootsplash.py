"""The boot screen: a Plymouth theme in the wallpaper's style. Parchment, the word
"sotto" in the clock's big pixel font, a greeting, and the wallpaper's dot trail
sweeping underneath while the machine starts or shuts down.

Plymouth runs before your fonts are available, so every bit of text is drawn here
into PNGs. bin/sotto-bootsplash installs the result (that part needs sudo).
"""
import getpass
import os
from pathlib import Path

from .art import BigFont, font_path
from .collect import config
from .grid import PALETTE

PIXEL = 7                 # screen pixels per font pixel; the wallpaper clock uses 7 too
DOT_SCALE = 3
THEME_DIR = "/usr/share/plymouth/themes/sotto"

SCRIPT = """\
# sotto boot screen. Drawn by sotto/bootsplash.py; edit that file, not this one.
Window.SetBackgroundTopColor([BG]);
Window.SetBackgroundBottomColor([BG]);

W = Window.GetWidth();
H = Window.GetHeight();
X0 = Window.GetX();
Y0 = Window.GetY();

logo.image = Image("wordmark.png");
logo.sprite = Sprite(logo.image);
logo.x = X0 + W / 2 - logo.image.GetWidth() / 2;
logo.y = Y0 + H * 0.42 - logo.image.GetHeight() / 2;
logo.sprite.SetPosition(logo.x, logo.y, 10);

mode = Plymouth.GetMode();
if (mode == "shutdown") greet.image = Image("greet-shutdown.png");
else if (mode == "reboot") greet.image = Image("greet-reboot.png");
else if (mode == "updates" || mode == "system-upgrade" || mode == "firmware-upgrade") greet.image = Image("greet-updates.png");
else greet.image = Image("greet-boot.png");
greet.sprite = Sprite(greet.image);
greet.y = logo.y + logo.image.GetHeight() + 30;
greet.sprite.SetPosition(X0 + W / 2 - greet.image.GetWidth() / 2, greet.y, 10);

# the dot trail: faint dots, with an ochre head sweeping across and fading behind it
N = 7;
GAP = 20;
TAIL = 3.5;
faint = Image("dot-faint.png");
lit = Image("dot-accent.png");
trail.y = greet.y + greet.image.GetHeight() + 26;
for (i = 0; i < N; i++) {
    x = X0 + W / 2 - (N - 1) * GAP / 2 + i * GAP - faint.GetWidth() / 2;
    base[i] = Sprite(faint);
    base[i].SetPosition(x, trail.y, 10);
    glow[i] = Sprite(lit);
    glow[i].SetPosition(x, trail.y, 11);
    glow[i].SetOpacity(0);
}
frame = 0;

fun refresh_callback () {
    global.frame = global.frame + 1;
    cycle = N + TAIL + 2;
    head = global.frame * 0.09;
    head = head - Math.Int(head / cycle) * cycle;
    for (i = 0; i < N; i++) {
        d = head - i;
        if (d >= 0 && d < TAIL) glow[i].SetOpacity(1 - d / TAIL);
        else glow[i].SetOpacity(0);
    }
}
Plymouth.SetRefreshFunction(refresh_callback);

# disk passwords and questions (only if the system asks for one)
prompt.sprite = Sprite();
prompt.sprite.SetZ(20);
MAXB = 32;
bullet = Image("dot-text.png");
for (i = 0; i < MAXB; i++) {
    bullets[i] = Sprite(bullet);
    bullets[i].SetOpacity(0);
}

fun show_prompt (text, count) {
    global.prompt.image = Image.Text(text, [DIM], 1);
    global.prompt.sprite.SetImage(global.prompt.image);
    global.prompt.sprite.SetPosition(X0 + W / 2 - global.prompt.image.GetWidth() / 2, trail.y + 40, 20);
    global.prompt.sprite.SetOpacity(1);
    shown = Math.Min(count, MAXB);
    for (i = 0; i < MAXB; i++) {
        bullets[i].SetPosition(X0 + W / 2 - shown * 6 + i * 12, trail.y + 70, 20);
        if (i < shown) bullets[i].SetOpacity(1);
        else bullets[i].SetOpacity(0);
    }
}

fun display_password_callback (text, count) {
    show_prompt(text, count);
}
Plymouth.SetDisplayPasswordFunction(display_password_callback);

fun display_question_callback (text, entry) {
    show_prompt(text + "  " + entry, 0);
}
Plymouth.SetDisplayQuestionFunction(display_question_callback);

fun display_normal_callback () {
    global.prompt.sprite.SetOpacity(0);
    for (i = 0; i < MAXB; i++) bullets[i].SetOpacity(0);
}
Plymouth.SetDisplayNormalFunction(display_normal_callback);

# status lines (disk checks and the like), quietly at the bottom
message.sprite = Sprite();
fun display_message_callback (text) {
    global.message.image = Image.Text(text, [DIM], 1);
    global.message.sprite.SetImage(global.message.image);
    global.message.sprite.SetPosition(X0 + W / 2 - global.message.image.GetWidth() / 2, Y0 + H - 56, 20);
    global.message.sprite.SetOpacity(1);
}
Plymouth.SetDisplayMessageFunction(display_message_callback);

fun hide_message_callback (text) {
    global.message.sprite.SetOpacity(0);
}
Plymouth.SetHideMessageFunction(hide_message_callback);
"""

THEME = f"""\
[Plymouth Theme]
Name=sotto
Description=Parchment, a pixel wordmark and the wallpaper's dot trail
ModuleName=script

[script]
ImageDir={THEME_DIR}
ScriptFile={THEME_DIR}/sotto.script
"""


def _rgb(key: str) -> tuple[int, int, int]:
    return PALETTE[key]


def _plymouth_rgb(key: str) -> str:
    return ", ".join(f"{c / 255:.3f}" for c in _rgb(key))


def wordmark(text: str = "sotto"):
    from PIL import Image, ImageDraw

    big = BigFont()
    glyphs = [big.glyph(ch) for ch in text]
    rows = ["".join(g[r] for g in glyphs) for r in range(len(glyphs[0]))]
    used = [x for x in range(len(rows[0])) if any(row[x] == "#" for row in rows)]
    left, right = min(used), max(used)
    img = Image.new("RGBA", ((right - left + 1) * PIXEL, len(rows) * PIXEL), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y, row in enumerate(rows):
        for x in range(left, right + 1):
            if row[x] == "#":
                X, Y = (x - left) * PIXEL, y * PIXEL
                d.rectangle([X, Y, X + PIXEL - 1, Y + PIXEL - 1], fill=_rgb("dim") + (255,))
    return img


def text_image(text: str, color: str, scale: int = 1):
    """DepartureMono at 11px, its pixel-sharp size, like the wallpaper's own text."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(font_path(), 11)
    l, t, r, b = font.getbbox(text)
    mask = Image.new("L", (r - l, b - t), 0)
    d = ImageDraw.Draw(mask)
    d.fontmode = "1"
    d.text((-l, -t), text, font=font, fill=255)
    img = Image.new("RGBA", mask.size, _rgb(color) + (255,))
    img.putalpha(mask)
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    return img


def greetings() -> dict[str, str]:
    name = str(config().get("name") or os.environ.get("SOTTO_NAME") or getpass.getuser()).title()
    return {
        "boot": f"Welcome back, {name}",
        "shutdown": f"See you soon, {name}",
        "reboot": "Back in a moment",
        "updates": "Updating · please keep it on",
    }


def render(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    files = {"wordmark.png": wordmark()}
    for mode, line in greetings().items():
        files[f"greet-{mode}.png"] = text_image(line, "dim")
    for color in ("accent", "faint", "text"):
        files[f"dot-{color}.png"] = text_image("•", color, DOT_SCALE)
    written = []
    for name, img in files.items():
        img.save(out / name)
        written.append(out / name)
    script = (SCRIPT.replace("[BG]", _plymouth_rgb("bg"))
                    .replace("[DIM]", _plymouth_rgb("dim")))
    (out / "sotto.script").write_text(script)
    (out / "sotto.plymouth").write_text(THEME)
    written += [out / "sotto.script", out / "sotto.plymouth"]
    return written


def preview(out: Path, width: int = 1366, height: int = 768, frame: int = 30) -> Path:
    """What the boot screen looks like mid-animation, for checking it without a reboot."""
    from PIL import Image

    img = Image.new("RGB", (width, height), _rgb("bg"))
    logo = wordmark()
    lx, ly = width // 2 - logo.width // 2, int(height * 0.42 - logo.height / 2)
    img.paste(logo, (lx, ly), logo)
    greet = text_image(greetings()["boot"], "dim")
    gy = ly + logo.height + 30
    img.paste(greet, (width // 2 - greet.width // 2, gy), greet)
    faint, lit = text_image("•", "faint", DOT_SCALE), text_image("•", "accent", DOT_SCALE)
    n, gap, tail = 7, 20, 3.5
    head = (frame * 0.09) % (n + tail + 2)
    ty = gy + greet.height + 26
    for i in range(n):
        x = int(width / 2 - (n - 1) * gap / 2 + i * gap - faint.width / 2)
        img.paste(faint, (x, ty), faint)
        d = head - i
        if 0 <= d < tail:
            glow = lit.copy()
            glow.putalpha(glow.getchannel("A").point(lambda a, o=1 - d / tail: int(a * o)))
            img.paste(glow, (x, ty), glow)
    img.save(out)
    return out
