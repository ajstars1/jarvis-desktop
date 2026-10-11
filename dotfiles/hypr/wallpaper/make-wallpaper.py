#!/usr/bin/env python3
"""Draw the AMBER CRT wallpaper: a BIOS-style boot screen built from this
machine's real specs, with a pixel paw and an AJSTARS logo.

Everything is drawn at half resolution with DepartureMono at 11px, the only
size where it is perfectly sharp, then scaled 2x with nearest-neighbour. That
keeps the pixels square. Scanlines, phosphor glow and a vignette go on last.

Run it again after a hardware change (e.g. the RAM upgrade) to refresh the specs:
    python3 ~/.config/hypr/wallpaper/make-wallpaper.py
"""
import os
import platform
import re
import subprocess
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

NAME = (os.environ.get("JARVIS_NAME") or os.environ.get("USER", "friend")).upper()
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "amber-boot.png")
FONT_PATHS = [
    os.path.expanduser("~/.local/share/fonts/DepartureMonoNerdFont-Regular.otf"),
    os.path.expanduser("~/.fonts/DepartureMonoNerdFont-Regular.otf"),
]

BG = (0x12, 0x0B, 0x00)
DIM = (0x7A, 0x52, 0x00)
AMBER = (0xFF, 0xB0, 0x00)
HOT = (0xFF, 0xD2, 0x7A)

PAW = [
    "....##...##....",
    "...####.####...",
    "...####.####...",
    "....##...##....",
    ".##.........##.",
    "####.......####",
    "####..###..####",
    ".##..#####..##.",
    "....#######....",
    "...#########...",
    "...#########...",
    "....###.###....",
]


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def specs():
    cpu = "UNKNOWN CPU"
    with open("/proc/cpuinfo") as f:
        for line in f:
            if line.startswith("model name"):
                cpu = re.sub(r"\((R|TM)\)|CPU ", "", line.split(":", 1)[1]).strip()
                cpu = re.sub(r"\s+", " ", cpu)
                break
    cores = os.cpu_count() or 1

    with open("/proc/meminfo") as f:
        kb = int(re.search(r"MemTotal:\s+(\d+)", f.read()).group(1))
    mem_mb = round(kb / 1024 / 1024) * 1024

    gpu = "INTEGRATED"
    m = re.search(r"(?:VGA compatible controller|3D controller): (.*)", run(["lspci"]))
    if m:
        gpu = re.sub(r"Intel Corporation |\(rev \w+\)", "", m.group(1)).strip()

    parts = run(["zpool", "list", "-H", "-o", "size,health", "rpool"]).split()
    disk = (f"ZFS RPOOL {parts[0]}", parts[1]) if len(parts) == 2 else ("SYSTEM DISK", "OK")

    net = ("NO LINK", "DOWN")
    for iface in sorted(os.listdir("/sys/class/net")):
        if re.match(r"(lo|docker|veth|virbr|br-|tailscale)", iface):
            continue
        try:
            with open(f"/sys/class/net/{iface}/operstate") as f:
                if f.read().strip() == "up":
                    net = (iface, "UP")
                    break
        except OSError:
            pass

    return [
        ("CPU", f"{cpu} x{cores}", "OK"),
        ("MEM", f"{mem_mb} MB", "OK"),
        ("GPU", gpu, "OK"),
        ("DISK", disk[0], disk[1]),
        ("KERN", f"LINUX {platform.release()}", "OK"),
        ("NET", net[0], net[1]),
    ]


def main():
    font_path = next((p for p in FONT_PATHS if os.path.exists(p)), None)
    if not font_path:
        sys.exit("DepartureMono Nerd Font not found")
    font = ImageFont.truetype(font_path, 11)

    W, H = 683, 384                      # half of 1366x768
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"                     # no anti-aliasing: hard pixels
    cw = round(font.getlength("M"))      # monospace cell width
    lh = 13                              # line height

    x, y = 18, 22                        # clear of the 22px bar once scaled
    d.text((x, y), "AJSTARS SYSTEMS   BIOS v26.04   (C) 2026 AMBER CRT", font=font, fill=HOT)
    y += lh * 2

    col = 52                             # column where the status words sit
    for key, value, status in specs():
        label = f"{key:<5} {value.upper()} "
        dots = "." * max(3, col - len(label))
        d.text((x, y), label, font=font, fill=AMBER)
        d.text((x + cw * len(label), y), dots, font=font, fill=DIM)
        d.text((x + cw * (len(label) + len(dots) + 1), y), status, font=font, fill=HOT)
        y += lh

    y += lh
    label = "LOADING HYPRLAND "
    d.text((x, y), label, font=font, fill=AMBER)
    d.text((x + cw * len(label), y), "." * (col - len(label)), font=font, fill=DIM)
    d.text((x + cw * (col + 1), y), "DONE", font=font, fill=HOT)
    y += lh
    d.text((x, y), f"WELCOME BACK, {NAME}.", font=font, fill=AMBER)
    y += lh * 2
    d.text((x, y), "> _", font=font, fill=HOT)

    # AJSTARS logo: 11px text drawn on its own, then scaled 4x
    word = "AJSTARS"
    tw, th = cw * len(word), 11
    logo = Image.new("RGB", (tw, th + 3), BG)
    ld = ImageDraw.Draw(logo)
    ld.fontmode = "1"
    ld.text((0, 0), word, font=font, fill=AMBER)
    logo = logo.resize((logo.width * 4, logo.height * 4), Image.Resampling.NEAREST)
    lx, ly = W - logo.width - 20, H - logo.height - 34
    img.paste(logo, (lx, ly))

    # pixel paw to the left of the logo
    cell = 3
    px = lx - len(PAW[0]) * cell - 14
    py = ly + (logo.height - len(PAW) * cell) // 2
    for r, row in enumerate(PAW):
        for c, ch in enumerate(row):
            if ch == "#":
                d.rectangle([px + c * cell, py + r * cell, px + c * cell + cell - 1, py + r * cell + cell - 1], fill=AMBER)

    tag = "AMBER CRT  ·  HYPRLAND  ·  TERMINAL 01"
    d.text((W - cw * len(tag) - 20, H - 26), tag, font=font, fill=DIM)

    # 2x nearest-neighbour: every source pixel becomes a crisp 2x2 block
    img = img.resize((W * 2, H * 2), Image.Resampling.NEAREST)

    # phosphor glow: a blurred copy, screen-blended back in
    glow = img.filter(ImageFilter.GaussianBlur(4))
    glow = Image.eval(glow, lambda v: int(v * 0.55))
    img = ImageChops.screen(img, glow)

    # scanlines: every second row darker, one dark row per source pixel row
    lines = Image.new("L", img.size, 255)
    ld = ImageDraw.Draw(lines)
    for yy in range(1, img.height, 2):
        ld.line([(0, yy), (img.width, yy)], fill=196)
    img = ImageChops.multiply(img, Image.merge("RGB", (lines, lines, lines)))

    # vignette: darken toward the corners
    vig = Image.radial_gradient("L").resize(img.size, Image.Resampling.BILINEAR)
    vig = Image.eval(vig, lambda v: 255 - int(v * 0.45))
    img = ImageChops.multiply(img, Image.merge("RGB", (vig, vig, vig)))

    img.save(OUT, optimize=True)
    print(f"wrote {OUT} ({img.width}x{img.height})")


if __name__ == "__main__":
    main()
