"""The wallpaper assistant: double-click the wallpaper, type, press Enter.

Small requests are understood and done locally, instantly and for free:
opening apps, websites, folders and your projects, web and YouTube searches,
system info (time, RAM, disk, temperature, IP), lock, screenshot, volume,
and how-to questions about this desktop. Anything else is a real question
and goes to Claude (Haiku, through the Claude Code login), answered in a
couple of sentences. Claude can only ask for the same safe actions; it never
runs commands.

Pure standard library, so it works from the dock (system python + GTK) and
from `python -m jarvis ask "..."` alike.
"""
import configparser
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path

HOME = Path.home()
STATE = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "jarvis" / "state.json"
WORKDIR = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "jarvis" / "assistant"
APP_DIRS = [
    HOME / ".local/share/applications",
    HOME / ".local/share/flatpak/exports/share/applications",
    Path("/var/lib/flatpak/exports/share/applications"),
    Path("/var/lib/snapd/desktop/applications"),
    Path("/usr/local/share/applications"),
    Path("/usr/share/applications"),
]

SITES = {
    "youtube": "https://www.youtube.com", "gmail": "https://mail.google.com", "mail": "https://mail.google.com",
    "google": "https://www.google.com", "github": "https://github.com", "drive": "https://drive.google.com",
    "google drive": "https://drive.google.com", "calendar": "https://calendar.google.com",
    "maps": "https://maps.google.com", "google maps": "https://maps.google.com", "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai", "whatsapp": "https://web.whatsapp.com", "linkedin": "https://www.linkedin.com",
    "twitter": "https://x.com", "instagram": "https://www.instagram.com", "reddit": "https://www.reddit.com",
    "netflix": "https://www.netflix.com", "spotify": "https://open.spotify.com", "amazon": "https://www.amazon.in",
    "flipkart": "https://www.flipkart.com", "news": "https://news.google.com", "translate": "https://translate.google.com",
    "docs": "https://docs.google.com", "sheets": "https://sheets.google.com", "meet": "https://meet.google.com",
}
FOLDERS = {
    "home": "~", "home folder": "~", "downloads": "~/Downloads", "documents": "~/Documents",
    "pictures": "~/Pictures", "photos": "~/Pictures", "videos": "~/Videos", "music": "~/Music",
    "desktop": "~/Desktop", "developer": "~/Developer", "projects": "~/Developer",
    "screenshots": "~/Pictures/Screenshots", "wallpapers": "~/Pictures/Wallpapers",
}
ALIASES = {  # everyday words -> what to open
    "browser": "browser", "web browser": "browser", "internet": "browser",
    "terminal": "app:kitty.desktop", "console": "app:kitty.desktop", "files": "app:org.gnome.Nautilus.desktop",
    "file manager": "app:org.gnome.Nautilus.desktop", "file explorer": "app:org.gnome.Nautilus.desktop",
    "explorer": "app:org.gnome.Nautilus.desktop", "apps": "drawer", "all apps": "drawer", "app drawer": "drawer",
    "launcher": "drawer", "code": "app:code.desktop", "vs code": "app:code.desktop", "vscode": "app:code.desktop",
}

HELP = ("Try: open blender · open youtube · play lofi on youtube · search best laptops · "
        "open downloads · open <a project> · how much ram · what time is it · lock · screenshot · "
        "volume up · how do I snap windows. Anything else, just ask.")

# questions about this desktop, answered locally
HOWTO = [
    (r"\bsnap|half (the )?screen|side by side|split screen", "Drag a window by its title bar to the left or right edge for half the screen, the top edge to maximize, or a corner for a quarter. Pause there for a moment and it snaps."),
    (r"minimi[sz]e", "Click – on the title bar, or click the app's icon in the top bar while you're in it. Click the icon again to bring it back."),
    (r"maximi[sz]e|full ?screen|bigger", "Click + on the title bar, or double-click the title bar. Do it again to go back."),
    (r"\bclose\b", "Click × on the title bar, or press Super+Q."),
    (r"\bdock\b", "Move the mouse to the bottom edge and the dock slides up. Right-click an icon for its menu and Dock Settings."),
    (r"drawer|all (my )?apps|launcher|find (an )?app", "Click the dotted grid at the top left or the first dock icon, or press Super+Space, then type to search."),
    (r"shortcut|keyboard|hotkey", "Super+F1 shows every shortcut. Handy ones: Super+Space apps, Alt+Tab switch, Super+Q close, Ctrl+Alt+T terminal, Super+L lock."),
    (r"switch|alt.?tab|between (windows|apps)", "Click an app in the top bar, or press Alt+Tab."),
    (r"\block", "Press Super+L, or type lock here."),
    (r"screenshot|screen ?shot", "Press Print to pick an area or Shift+Print for the whole screen; it's copied and saved in Pictures/Screenshots. Or type screenshot here."),
    (r"wallpaper|this (box|prompt|thing)|what (is|are) you|who are you", "I'm the assistant on your wallpaper. Double-click anywhere on the wallpaper, type, and press Enter. Esc or a click elsewhere closes me."),
]

SYSTEM_PROMPT = (
    "You are the assistant built into the wallpaper of this computer: Ubuntu with the Hyprland "
    "desktop, a dock at the bottom, an app switcher in the top bar, title bars with × + – buttons, "
    "drag-to-edge snapping and a right-click desktop menu. Reply in plain text with no markdown, at most "
    "three short sentences, friendly and direct. If the user wants something done on the computer, end with "
    "one line that is exactly one of: 'ACTION: open_url <url>', 'ACTION: open_app <app name>', "
    "'ACTION: search <query>'. Never claim to have done anything else."
)


def reply(text, action=None):
    return {"reply": text, "action": action}


# ── apps ──────────────────────────────────────────────────────────────────
def desktop_apps():
    seen, apps = set(), []
    for d in APP_DIRS:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.desktop")):
            if f.name in seen:
                continue
            seen.add(f.name)
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                cp.read(f, encoding="utf-8")
                e = cp["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            if e.get("NoDisplay", "").lower() == "true" or e.get("Hidden", "").lower() == "true" or e.get("Type") != "Application":
                continue
            apps.append({"id": f.name, "path": str(f), "name": e.get("Name", f.stem),
                         "words": " ".join([e.get("GenericName", ""), e.get("Keywords", ""), f.stem]).lower()})
    return apps


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def find_app(target: str, min_score: float = 1):
    """Best installed app for a name: whole-word matches beat prefixes beat
    substrings; browser web-app shortcuts (brave-…-Default) lose ties."""
    t = norm(target)
    words_t = target.lower().split()
    if not t:
        return None
    best, best_score = None, 0.0
    for a in desktop_apps():
        n = norm(a["name"])
        words = [norm(w) for w in re.split(r"[\s\-_.]+", a["name"]) if w]
        if n == t:
            score = 5
        elif t in words or (len(words_t) > 1 and all(norm(w) in words for w in words_t)):
            score = 4
        elif n.startswith(t):
            score = 3
        elif any(w.startswith(t) for w in words):
            score = 2.5
        elif t in n:
            score = 2
        elif t in norm(a["words"]):
            score = 1
        else:
            continue
        if re.search(r"-Default\.desktop$|^(brave|chrome|msedge)-[a-z]{20,}", a["id"]):
            score -= 0.5                  # a web-app shortcut, not the real app
        if score > best_score or (score == best_score and best and len(a["name"]) < len(best["name"])):
            best, best_score = a, score
    return best if best and best_score >= min_score else None


def default_browser():
    out = subprocess.run(["xdg-settings", "get", "default-web-browser"], capture_output=True, text=True).stdout.strip()
    return out or None


def projects():
    try:
        return json.loads(STATE.read_text()).get("projects", [])
    except (OSError, json.JSONDecodeError):
        return []


# ── system info ───────────────────────────────────────────────────────────
def meminfo():
    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            mem[k] = int(v.split()[0])
    used = (mem["MemTotal"] - mem["MemAvailable"]) / 1048576
    return f"RAM: {used:.1f} of {mem['MemTotal'] / 1048576:.1f} GB in use ({round(100 * used * 1048576 / mem['MemTotal'])}%)."


def diskinfo():
    out = subprocess.run(["zpool", "list", "-H", "-o", "size,alloc,free,cap", "rpool"], capture_output=True, text=True).stdout.split()
    if len(out) == 4:
        return f"Disk: {out[2]} free of {out[0]} ({out[3]} used)."
    st = os.statvfs(HOME)
    return f"Disk: {st.f_bavail * st.f_frsize / 1e9:.0f} GB free."


def tempinfo():
    for h in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            if (h / "name").read_text().strip() == "coretemp":
                return f"CPU is at {round(int((h / 'temp1_input').read_text()) / 1000)}°C."
        except OSError:
            pass
    return "I can't read the CPU temperature."


def ipinfo():
    out = subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split()
    return f"Your local IP is {out[0]}." if out else "You don't seem to be connected."


def uptimeinfo():
    with open("/proc/uptime") as f:
        s = int(float(f.read().split()[0]))
    return f"Up for {s // 3600} h {s % 3600 // 60} min."


# ── understanding ─────────────────────────────────────────────────────────
def url_action(url):
    return {"type": "url", "url": url}


def open_target(target: str):
    """'open X': site, link, folder, project or app."""
    t = target.strip().strip(".").lower()
    t = re.sub(r"\s+(website|site|app|application|folder)$", "", t)
    if t in ALIASES:
        kind, _, val = ALIASES[t].partition(":")
        if kind == "drawer":
            return reply("Here are all your apps.", {"type": "drawer"})
        if kind == "browser":
            b = default_browser()
            return reply("Opening your browser.", {"type": "app", "id": b} if b else url_action("https://www.google.com"))
        return reply(f"Opening {t}.", {"type": "app", "id": val})
    strong = find_app(t, min_score=4)         # an installed app by that name wins over its website
    if strong:
        return reply(f"Opening {strong['name']}.", {"type": "app", "id": strong["id"], "path": strong["path"]})
    if t in SITES:
        return reply(f"Opening {t.title()}.", url_action(SITES[t]))
    if re.fullmatch(r"(https?://)?[\w.-]+\.[a-z]{2,}(/\S*)?", t):
        return reply(f"Opening {t}.", url_action(t if t.startswith("http") else "https://" + t))
    if t in FOLDERS:
        return reply(f"Opening {t}.", {"type": "path", "path": os.path.expanduser(FOLDERS[t])})
    for p in projects():
        if norm(p["name"]).startswith(norm(t)) and len(norm(t)) >= 3:
            return reply(f"Opening {p['name'].title()}.", {"type": "project", "path": p["path"]})
    app = find_app(t)
    if app:
        return reply(f"Opening {app['name']}.", {"type": "app", "id": app["id"], "path": app["path"]})
    return None


def handle(text: str):
    """Returns {'reply', 'action'} for things done locally, or None for a real question."""
    raw = text.strip()
    low = raw.lower().strip().rstrip("?!. ")
    if not low:
        return None
    is_question = raw.endswith("?") or re.match(r"^(how|what|where|why|when|which|who|can|is|are|do|does)\b", low)

    if low in ("help", "?", "commands", "what can you do", "what can i do", "what can i ask"):
        return reply(HELP)
    if is_question:
        for pattern, answer in HOWTO:
            if re.search(pattern, low):
                return reply(answer)

    m = (re.match(r"^(?:play|search|find|watch|look up)\s+(.+?)\s+(?:on|in)\s+youtube$", low)
         or re.match(r"^(?:search\s+)?youtube\s+(?:for\s+)?(.+)$", low))
    if m:
        q = m.group(1)
        return reply(f"Searching YouTube for {q}.", url_action("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q)))
    m = re.match(r"^(?:search|google|look up|search for|search the web for)\s+(?:for\s+)?(.+)$", low)
    if m:
        q = m.group(1)
        return reply(f"Searching for {q}.", url_action("https://www.google.com/search?q=" + urllib.parse.quote_plus(q)))
    m = re.match(r"^(?:open|launch|start|run|show(?: me)?|go to)\s+(?:up\s+)?(?:the\s+|my\s+)?(.+)$", low)
    if m:
        r = open_target(m.group(1))
        if r:
            return r
    if low in SITES:
        return reply(f"Opening {low.title()}.", url_action(SITES[low]))

    if re.search(r"\b(time)\b", low) and not re.search(r"(time zone|timer|times)", low):
        return reply(time.strftime("It's %H:%M."))
    if re.search(r"\b(date|day is it|today)\b", low):
        return reply(time.strftime("Today is %A, %d %B %Y."))
    if re.search(r"\b(ram|memory)\b", low):
        return reply(meminfo())
    if re.search(r"\b(disk|storage|space left|free space)\b", low):
        return reply(diskinfo())
    if re.search(r"\b(temp|temperature|hot)\b", low):
        return reply(tempinfo())
    if re.search(r"\b(ip|ip address)\b", low):
        return reply(ipinfo())
    if re.search(r"\buptime\b|how long .*(on|running)", low):
        return reply(uptimeinfo())

    if re.fullmatch(r"(lock|lock (the )?screen|lock (my )?(pc|computer))", low):
        return reply("Locking.", {"type": "cmd", "argv": ["loginctl", "lock-session"]})
    if re.fullmatch(r"(take a )?screenshot|screen ?shot", low):
        return reply("Pick an area.", {"type": "cmd", "argv": [os.path.expanduser("~/.config/hypr/scripts/screenshot.sh"), "region"]})
    m = re.fullmatch(r"(?:turn )?(?:the )?volume (up|down)|(mute|unmute)", low)
    if m:
        what = m.group(1) or m.group(2)
        argv = {"up": ["wpctl", "set-volume", "-l", "1", "@DEFAULT_AUDIO_SINK@", "10%+"],
                "down": ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%-"],
                "mute": ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"],
                "unmute": ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"]}[what]
        return reply({"up": "Volume up.", "down": "Volume down.", "mute": "Muted.", "unmute": "Unmuted."}[what], {"type": "cmd", "argv": argv})

    if is_question:
        return None                       # a real question: ask Claude
    # an unknown short command ("blender", "spotify") is most likely an app or site
    if len(low.split()) <= 3:
        r = open_target(low)
        if r:
            return r
    return None


def ask(question: str, timeout: int = 45):
    """Ask Claude (Haiku). Returns {'reply', 'action'}; never raises."""
    claude = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    if not os.path.exists(claude):
        return reply("I can only do quick local things right now (Claude isn't installed).")
    WORKDIR.mkdir(parents=True, exist_ok=True)
    cmd = [claude, "-p", "--model", "haiku", "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--no-session-persistence", "--setting-sources", "", "--system-prompt", SYSTEM_PROMPT, question]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=WORKDIR)
    except subprocess.TimeoutExpired:
        return reply("That took too long. Try again in a moment?")
    except OSError as e:
        return reply(f"I couldn't reach Claude ({e.strerror}).")
    text = (out.stdout or "").strip()
    if out.returncode != 0 or not text:
        err = (out.stderr or "").strip().splitlines()
        return reply("I couldn't get an answer" + (f": {err[-1][:120]}" if err else "."))
    lines = text.splitlines()
    action = None
    if lines and lines[-1].strip().upper().startswith("ACTION:"):
        verb, _, arg = lines.pop().split(":", 1)[1].strip().partition(" ")
        arg = arg.strip()
        if verb == "open_url" and re.match(r"^https?://", arg):
            action = url_action(arg)
        elif verb == "search" and arg:
            action = url_action("https://www.google.com/search?q=" + urllib.parse.quote_plus(arg))
        elif verb == "open_app" and arg:
            app = find_app(arg)
            action = {"type": "app", "id": app["id"], "path": app["path"]} if app else None
    return reply(" ".join(l.strip() for l in lines if l.strip()) or "Done.", action)


def run_action(action, launch_app=None):
    """Carry out an action. launch_app(id) lets the dock launch through GTK."""
    if not action:
        return
    kind = action["type"]

    def hypr_exec(cmdline: str):
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            subprocess.Popen(["hyprctl", "dispatch", "exec", cmdline], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(cmdline, shell=True, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if kind == "url":
        hypr_exec("xdg-open " + _q(action["url"]))
    elif kind == "path":
        hypr_exec("xdg-open " + _q(action["path"]))
    elif kind == "project":
        hypr_exec("kitty --directory " + _q(action["path"]))
    elif kind == "drawer":
        hypr_exec("rofi -show drun -theme drawer")
    elif kind == "app":
        if launch_app and launch_app(action["id"]):
            return
        hypr_exec("gtk-launch " + _q(action["id"].removesuffix(".desktop")))
    elif kind == "cmd":
        subprocess.Popen(action["argv"], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _q(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"
