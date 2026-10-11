#!/usr/bin/env python3
"""AJSTARS dock: an Apple-style dock for Hyprland, in GTK4 + gtk4-layer-shell.

- hides itself and slides up when the mouse touches the bottom edge
- one icon per app: pinned apps get a dot when running, unpinned running
  apps appear after a divider (no duplicate icons)
- click: open the app, or bring its window forward (cycles if several;
  restores minimized ones)
- right-click: its windows, New Window, Maximize, Keep in Dock / Remove,
  Quit, Dock Settings…
- Dock Settings: pick, order and remove apps, icon size, auto-hide

Settings live in ~/.config/jarvis/dock.json. Runs with the system python3
(python3-gi); bin/jarvis-dock preloads libgtk4-layer-shell as GTK requires.
"""
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import gi

import assistant  # the wallpaper assistant's brain (same folder)

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

try:
    gi.require_foreign("cairo")       # needs python3-gi-cairo; without it, clicks after an answer close the prompt
    import cairo  # noqa: E402
except ImportError:
    cairo = None

try:
    gi.require_version("GioUnix", "2.0")
    from gi.repository import GioUnix  # noqa: E402
    DesktopAppInfo = GioUnix.DesktopAppInfo
except (ValueError, ImportError):
    DesktopAppInfo = Gio.DesktopAppInfo

try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell as LS  # noqa: E402
    LS.get_major_version()          # the typelib can exist without the library behind it
except (ValueError, ImportError, GLib.Error):
    LS = None

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "jarvis" / "dock.json"
LAUNCHPAD = "launchpad"
DEFAULTS = {
    "pinned": [LAUNCHPAD, "org.gnome.Nautilus.desktop", "google-chrome.desktop", "kitty.desktop",
               "cursor.desktop", "code.desktop", "blender_blender.desktop", "discord.desktop"],
    "autohide": True,
    "icon_size": 44,
    "show_unpinned": True,
}
MARGIN = 8            # gap between dock and screen edge when shown
SLIDE_MS = 180

CSS = """
window.dock-window, window.snap-preview-window { background: transparent; }
window.prompt-window { background: transparent; }
.prompt { background: rgba(236, 226, 208, 0.97); border-radius: 10px; padding: 8px 12px; }
.prompt-chevron { color: #a7783f; font-family: "DepartureMono Nerd Font"; font-size: 11px; }
entry.prompt-entry { background: transparent; border: none; box-shadow: none; outline: none; padding: 0; min-height: 0;
    color: #3d2c1f; caret-color: #a7783f; font-family: "DepartureMono Nerd Font"; font-size: 11px; }
entry.prompt-entry > text > placeholder { color: #b5a185; }
.prompt-reply { color: #6b5540; font-family: "DepartureMono Nerd Font"; font-size: 11px; }
.prompt-reply.thinking { color: #a7783f; }
.snap-preview {
    background: rgba(167, 120, 63, 0.16);
    border: 2px solid rgba(167, 120, 63, 0.75);
    border-radius: 14px;
}
.dock {
    background: rgba(243, 235, 222, 0.97);
    border: 1px solid #cdb99b;
    border-radius: 20px;
    padding: 6px 10px 4px 10px;
}
.dock-item { background: transparent; border: none; box-shadow: none; padding: 2px 4px; min-width: 0; }
.dock-item image { transition: transform 140ms ease-out; }
.dock-item:hover image { transform: scale(1.16) translateY(-3px); }
.dock-item:hover { background: transparent; }
.apps-icon { color: #3d2c1f; }
.dot { min-width: 5px; min-height: 5px; border-radius: 3px; background: #2b2019; margin-top: 3px; }
.dot.off { background: transparent; }
.divider { background: #cdb99b; min-width: 1px; margin: 8px 6px 10px 6px; }
popover > contents { background: #f3ebde; border: 1px solid #cdb99b; border-radius: 12px; padding: 6px; }
popover label, popover button { color: #3d2c1f; }
popover button { background: transparent; border: none; box-shadow: none; padding: 6px 10px; border-radius: 8px; }
popover button:hover { background: #e2d4bd; }
popover .title { font-weight: bold; padding: 4px 10px 6px 10px; }
popover separator { background: #cdb99b; margin: 4px 6px; }
window.dock-settings, window.dock-settings > * { background: #ece2d0; color: #3d2c1f; }
.dock-settings label { color: #3d2c1f; }
.dock-settings .heading { font-weight: bold; margin-top: 8px; }
.dock-settings list, .dock-settings row { background: #f3ebde; color: #3d2c1f; }
.dock-settings button { color: #3d2c1f; }
"""


# ── config ───────────────────────────────────────────────────────────────
def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        cfg = {}
    return {**DEFAULTS, **cfg}


def save_config(cfg: dict):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    os.replace(tmp, CONFIG)


# ── hyprland ─────────────────────────────────────────────────────────────
def hypr(*args) -> str:
    try:
        return subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def clients() -> list[dict]:
    try:
        return [c for c in json.loads(hypr("clients", "-j") or "[]") if c.get("mapped", True) and c.get("class")]
    except json.JSONDecodeError:
        return []


def focus_window(c: dict):
    addr = c["address"]
    if c["workspace"]["name"] == "special:minimized":
        ws = json.loads(hypr("activeworkspace", "-j") or '{"id": 1}')["id"]
        hypr("dispatch", "movetoworkspacesilent", f"{ws},address:{addr}")
    hypr("dispatch", "focuswindow", f"address:{addr}")
    hypr("dispatch", "alterzorder", f"top,address:{addr}")


# ── apps ─────────────────────────────────────────────────────────────────
class Apps:
    """Maps Hyprland window classes to installed .desktop apps. Re-reads the app
    list when apps are installed or removed, so new apps show up right away."""

    def __init__(self):
        self.all = []
        self.cache: dict = {}
        self.loaded_at = 0.0
        self.reload()
        self.monitor = Gio.AppInfoMonitor.get()
        self.monitor.connect("changed", lambda *_: self.reload())

    def reload(self):
        self.all = [a for a in Gio.AppInfo.get_all() if isinstance(a, DesktopAppInfo)]
        self.cache.clear()
        self.loaded_at = GLib.get_monotonic_time() / 1e6

    def get(self, app_id: str):
        try:
            return DesktopAppInfo.new(app_id)
        except TypeError:
            return None

    def match(self, cls: str):
        c = cls.lower()
        for a in self.all:
            wm = (a.get_startup_wm_class() or "").lower()
            aid = a.get_id().lower().removesuffix(".desktop")
            exe = os.path.basename(a.get_executable() or "").lower()
            if c in (wm, aid, exe) or aid.endswith("." + c) or aid.split("_")[0] == c:
                return a
        return None

    def for_class(self, cls: str):
        if cls in self.cache:
            return self.cache[cls]
        found = self.match(cls)
        if found is None and GLib.get_monotonic_time() / 1e6 - self.loaded_at > 5:
            self.reload()                      # maybe it was installed after the dock started
            found = self.match(cls)
        if found is not None:
            self.cache[cls] = found
        return found


# ── dock ─────────────────────────────────────────────────────────────────
class Dock(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="dev.ajstars.dock", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.cfg = load_config()
        self.apps = Apps()
        self.win = None
        self.items: dict[str, tuple[Gtk.Widget, Gtk.Widget]] = {}   # app id -> (button, dot)
        self.running: dict[str, list[dict]] = {}
        self.margin = MARGIN
        self.target = MARGIN
        self.anim = 0
        self.hide_timer = 0
        self.popover_open = False
        self.settings_win = None
        self.refresh_pending = False

    # startup / command line
    def do_command_line(self, cmd):
        args = cmd.get_arguments()[1:]
        if self.win is None:
            self.build()
        if "--settings" in args:
            self.open_settings()
        return 0

    def build(self):
        prov = Gtk.CssProvider()
        prov.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.win = Gtk.Window(application=self)
        self.win.add_css_class("dock-window")
        # full-width transparent strip with the pill centred in it; when hidden, its
        # bottom 2px stay on screen and catch the mouse anywhere along the edge
        strip = Gtk.Box(hexpand=True)
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2, halign=Gtk.Align.CENTER, hexpand=True)
        self.box.add_css_class("dock")
        strip.append(self.box)
        self.win.set_child(strip)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self.on_enter())
        motion.connect("motion", lambda *_: self.on_enter())
        motion.connect("leave", lambda *_: self.schedule_hide())
        self.win.add_controller(motion)

        if LS:
            LS.init_for_window(self.win)
            LS.set_namespace(self.win, "jarvis-dock")
            LS.set_layer(self.win, LS.Layer.TOP)
            for e in (LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
                LS.set_anchor(self.win, e, True)
            # never take the keyboard: on Hyprland a panel holding keyboard focus keeps it
            # even when you click back into a window (typing and title-bar buttons stop working)
            LS.set_keyboard_mode(self.win, LS.KeyboardMode.NONE)
        self.populate()
        self.apply_autohide()
        self.win.present()
        self.make_preview()
        self.make_prompt()
        self.refresh_running()
        threading.Thread(target=self.listen, daemon=True).start()
        if self.cfg["autohide"]:
            self.schedule_hide(1500)

    # snap preview: an outline showing where a dragged window will land (driven by snap.py)
    def make_preview(self):
        if not LS:
            return
        w = Gtk.Window(application=self)
        w.add_css_class("snap-preview-window")
        w.set_resizable(False)
        self.preview_box = Gtk.Box()
        self.preview_box.add_css_class("snap-preview")
        w.set_child(self.preview_box)
        LS.init_for_window(w)
        LS.set_namespace(w, "jarvis-snap-preview")
        LS.set_layer(w, LS.Layer.OVERLAY)
        LS.set_anchor(w, LS.Edge.TOP, True)
        LS.set_anchor(w, LS.Edge.LEFT, True)
        LS.set_exclusive_zone(w, -1)
        LS.set_keyboard_mode(w, LS.KeyboardMode.NONE)
        self.preview = w
        threading.Thread(target=self.preview_server, daemon=True).start()

    def preview_server(self):
        path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-dock.sock")
        try:
            os.unlink(path)
        except OSError:
            pass
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.bind(path)
        while True:
            msg = s.recv(256).decode(errors="ignore").split()
            GLib.idle_add(self.on_preview, msg)

    def on_preview(self, msg):
        if msg and msg[0] == "prompt" and len(msg) == 3:
            self.open_prompt(int(msg[1]), int(msg[2]))
            return False
        if msg and msg[0] == "prompt-close":
            self.close_prompt()
            return False
        if msg and msg[0] == "prompt-demo" and len(msg) >= 4:   # for demo recordings: type it out, then Enter
            self.open_prompt(int(msg[1]), int(msg[2]))
            text, typed = " ".join(msg[3:]), [0]

            def key():
                typed[0] += 1
                self.prompt_entry.set_text(text[:typed[0]])
                self.prompt_entry.set_position(-1)
                if typed[0] >= len(text):
                    GLib.timeout_add(350, lambda: self.on_prompt_submit(self.prompt_entry) or False)
                    return False
                return True

            GLib.timeout_add(70, key)
            return False
        if msg and msg[0] == "prompt-ask":          # for testing: submit text as if typed
            self.open_prompt(400, 300)
            self.prompt_entry.set_text(" ".join(msg[1:]))
            self.on_prompt_submit(self.prompt_entry)
            return False
        inset = 6
        if len(msg) == 5 and msg[0] == "show":
            x, y, w, h = (int(v) for v in msg[1:])
            LS.set_margin(self.preview, LS.Edge.LEFT, x + inset)
            LS.set_margin(self.preview, LS.Edge.TOP, y + inset)
            self.preview_box.set_size_request(max(1, w - 2 * inset), max(1, h - 2 * inset))
            self.preview.set_visible(True)
            surf = self.preview.get_surface()
            if surf is not None and cairo is not None and not getattr(self, "preview_passthrough", False):
                try:
                    surf.set_input_region(cairo.Region())   # never catches the mouse
                    self.preview_passthrough = True
                except Exception:
                    pass
        else:
            self.preview.set_visible(False)
        return False

    # ── wallpaper prompt: double-click the wallpaper, type, Enter ──────────
    # The prompt lives in a transparent full-screen layer (kept below the top bar).
    # While you type it holds the keyboard, and Hyprland then won't move focus on a
    # click elsewhere, so the transparent area catches that click and closes the
    # prompt, like any popup. After Enter it only listens on the box itself.
    def make_prompt(self):
        self.prompt = None
        if not LS:
            return
        w = Gtk.Window(application=self)
        w.add_css_class("prompt-window")
        self.prompt_fixed = Gtk.Fixed()
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        col.add_css_class("prompt")
        row = Gtk.Box(spacing=8)
        chevron = Gtk.Label(label="›")
        chevron.add_css_class("prompt-chevron")
        self.prompt_entry = Gtk.Entry(has_frame=False, hexpand=True, width_chars=46,
                                      placeholder_text="ask, or tell me to open something")
        self.prompt_entry.add_css_class("prompt-entry")
        self.prompt_entry.connect("activate", self.on_prompt_submit)
        row.append(chevron)
        row.append(self.prompt_entry)
        self.prompt_reply = Gtk.Label(xalign=0, wrap=True, max_width_chars=58, visible=False)
        self.prompt_reply.add_css_class("prompt-reply")
        col.append(row)
        col.append(self.prompt_reply)
        self.prompt_box = col
        self.prompt_fixed.put(col, 0, 0)
        w.set_child(self.prompt_fixed)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_prompt_key)
        w.add_controller(keys)
        click = Gtk.GestureClick()
        click.connect("pressed", self.on_prompt_click)
        w.add_controller(click)
        LS.init_for_window(w)
        LS.set_namespace(w, "jarvis-prompt")
        LS.set_layer(w, LS.Layer.TOP)
        for e in (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
            LS.set_anchor(w, e, True)
        LS.set_exclusive_zone(w, 0)          # stays below the top bar, so the bar keeps working
        LS.set_keyboard_mode(w, LS.KeyboardMode.NONE)
        self.prompt = w
        self.prompt_timer = 0
        self.prompt_anim = 0
        self.prompt_done = False
        self.prompt_history: list[str] = []
        self.history_at = 0

    def inside_prompt_box(self, x: float, y: float) -> bool:
        widget = self.prompt.pick(x, y, Gtk.PickFlags.DEFAULT)
        while widget is not None:
            if widget is self.prompt_box:
                return True
            widget = widget.get_parent()
        return False

    def on_prompt_click(self, _gesture, _n, x, y):
        if not self.inside_prompt_box(x, y):
            self.close_prompt()              # a click anywhere else closes it
        elif self.prompt_done:
            self.reask()                     # click the answer to ask something new

    def set_prompt_input(self, box_only: bool):
        """Where the prompt layer accepts clicks: everywhere (while typing) or just the box."""
        surf = self.prompt.get_surface()
        if surf is None or cairo is None:
            return
        try:
            if box_only:
                a = self.prompt_box.get_allocation()
                region = cairo.Region(cairo.RectangleInt(a.x, a.y, max(1, a.width), max(1, a.height) + 220))
            else:
                region = cairo.Region(cairo.RectangleInt(0, 0, 10000, 10000))
            surf.set_input_region(region)
        except Exception:               # never let this break the prompt
            pass

    def open_prompt(self, x: int, y: int):
        if not self.prompt:
            return
        geo = Gdk.Display.get_default().get_monitors().get_item(0).get_geometry()
        try:
            top = json.loads(hypr("monitors", "-j") or "[]")[0]["reserved"][1]
        except (IndexError, KeyError, json.JSONDecodeError):
            top = 26
        x = max(8, min(x - 16, geo.width - 480))
        y = max(4, min(y - 10 - top, geo.height - top - 190))
        self.prompt_fixed.move(self.prompt_box, x, y)
        self.reask()

    def reask(self):
        """Ready for a (new) question: empty line, keyboard held while typing."""
        self.stop_anim()
        self.prompt_done = False
        self.prompt_entry.set_editable(True)
        self.prompt_entry.set_text("")
        self.prompt_reply.set_visible(False)
        self.history_at = len(self.prompt_history)
        LS.set_keyboard_mode(self.prompt, LS.KeyboardMode.EXCLUSIVE)
        self.prompt.set_visible(True)
        self.prompt.present()
        self.set_prompt_input(box_only=False)
        self.prompt_entry.grab_focus()
        self.arm_prompt_close(60)

    def close_prompt(self):
        if not self.prompt:
            return
        self.stop_anim()
        if self.prompt_timer:
            GLib.source_remove(self.prompt_timer)
            self.prompt_timer = 0
        LS.set_keyboard_mode(self.prompt, LS.KeyboardMode.NONE)
        self.prompt.set_visible(False)

    def arm_prompt_close(self, seconds: int):
        if self.prompt_timer:
            GLib.source_remove(self.prompt_timer)

        def done():
            self.prompt_timer = 0
            self.close_prompt()
            return False

        self.prompt_timer = GLib.timeout_add_seconds(seconds, done)

    def on_focus_event(self):
        """Something else got focus (Alt+Tab, a top-bar click): close a prompt still being typed."""
        if self.prompt and self.prompt.get_visible() and not self.prompt_done:
            self.close_prompt()
        return False

    def on_prompt_key(self, _ctrl, keyval, _code, _state):
        name = Gdk.keyval_name(keyval)
        if name == "Escape":
            self.close_prompt()
            return True
        if name in ("Up", "Down") and self.prompt_history and not self.prompt_done:
            self.history_at = max(0, min(len(self.prompt_history), self.history_at + (-1 if name == "Up" else 1)))
            text = self.prompt_history[self.history_at] if self.history_at < len(self.prompt_history) else ""
            self.prompt_entry.set_text(text)
            self.prompt_entry.set_position(-1)
            return True
        return False

    def on_prompt_submit(self, entry):
        text = entry.get_text().strip()
        if not text:
            self.close_prompt()
            return
        self.prompt_history.append(text)
        self.prompt_done = True
        entry.set_editable(False)
        LS.set_keyboard_mode(self.prompt, LS.KeyboardMode.NONE)   # hand the keyboard straight back
        self.set_prompt_input(box_only=True)                       # and stop catching clicks elsewhere
        local = assistant.handle(text)
        if local:
            self.show_reply(local["reply"])
            assistant.run_action(local["action"], self.launch_app_id)
            self.arm_prompt_close(6 if local["action"] else 20)
            return
        self.show_thinking()

        def work():
            r = assistant.ask(text)
            GLib.idle_add(self.got_answer, r)

        threading.Thread(target=work, daemon=True).start()

    def got_answer(self, r):
        self.show_reply(r["reply"])
        assistant.run_action(r["action"], self.launch_app_id)
        self.arm_prompt_close(40)
        return False

    def stop_anim(self):
        if self.prompt_anim:
            GLib.source_remove(self.prompt_anim)
            self.prompt_anim = 0
        self.prompt_reply.remove_css_class("thinking")

    def show_thinking(self):
        self.stop_anim()
        self.prompt_reply.add_css_class("thinking")
        self.prompt_reply.set_visible(True)
        step = [0]

        def tick():
            step[0] = (step[0] + 1) % 4
            self.prompt_reply.set_text(" ".join("·" * max(1, step[0])))
            return True

        tick()
        self.prompt_anim = GLib.timeout_add(280, tick)

    def show_reply(self, text: str):
        """Types the answer out, a few characters at a time."""
        self.stop_anim()
        self.prompt_reply.set_visible(True)
        shown = [0]

        def tick():
            shown[0] = min(len(text), shown[0] + 3)
            self.prompt_reply.set_text(text[:shown[0]])
            if shown[0] >= len(text):
                self.prompt_anim = 0
                return False
            return True

        self.prompt_reply.set_text("")
        self.prompt_anim = GLib.timeout_add(14, tick)

    def launch_app_id(self, app_id: str) -> bool:
        app = self.apps.get(app_id)
        if not app:
            return False
        app.launch([], Gdk.Display.get_default().get_app_launch_context())
        return True

    # items
    def populate(self):
        child = self.box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.box.remove(child)
            child = nxt
        self.items.clear()
        for app_id in self.cfg["pinned"]:
            self.add_item(app_id, pinned=True)
        if self.cfg["show_unpinned"]:
            extra = [a for a in self.running if a not in self.cfg["pinned"]]
            if extra:
                div = Gtk.Box()
                div.add_css_class("divider")
                self.box.append(div)
                for app_id in extra:
                    self.add_item(app_id, pinned=False)
        self.update_dots()

    def add_item(self, app_id: str, pinned: bool):
        size = self.cfg["icon_size"]
        if app_id == LAUNCHPAD:
            img = Gtk.Image.new_from_icon_name("view-app-grid-symbolic")
            img.add_css_class("apps-icon")
            name = "Apps"
        elif app_id.startswith("class:"):
            cls = app_id[6:]
            theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
            icon = next((n for n in (cls, cls.lower(), cls.split(".")[-1].lower()) if theme.has_icon(n)), "application-x-executable")
            img = Gtk.Image.new_from_icon_name(icon)
            name = cls.split(".")[-1].replace("-", " ").title()
        else:
            app = self.apps.get(app_id)
            if app is None:
                return
            img = Gtk.Image.new_from_gicon(app.get_icon()) if app.get_icon() else Gtk.Image.new_from_icon_name("application-x-executable")
            name = app.get_display_name()
        img.set_pixel_size(size)
        dot = Gtk.Box(halign=Gtk.Align.CENTER)
        dot.add_css_class("dot")
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        col.append(img)
        col.append(dot)
        btn = Gtk.Button(child=col, tooltip_text=name)
        btn.add_css_class("dock-item")
        btn.connect("clicked", lambda *_: self.on_click(app_id))
        rc = Gtk.GestureClick(button=3)
        rc.connect("pressed", lambda *_: self.on_menu(app_id, btn, pinned))
        btn.add_controller(rc)
        self.box.append(btn)
        self.items[app_id] = (btn, dot)

    def update_dots(self):
        for app_id, (_, dot) in self.items.items():
            if self.running.get(app_id):
                dot.remove_css_class("off")
            else:
                dot.add_css_class("off")

    # running windows
    def refresh_running(self):
        self.refresh_pending = False
        running: dict[str, list[dict]] = {}
        for c in clients():
            if c["class"] in ("jarvis-wall",):
                continue
            app = self.apps.for_class(c["class"])
            key = app.get_id() if app else "class:" + c["class"]   # no .desktop file: still show it
            running.setdefault(key, []).append(c)
        changed_set = set(running) != set(self.running)
        self.running = running
        if changed_set and self.cfg["show_unpinned"]:
            self.populate()
        else:
            self.update_dots()
        return False

    def listen(self):
        """Hyprland's event socket: refresh the dots when windows open, close or move."""
        try:
            path = os.path.join(os.environ["XDG_RUNTIME_DIR"], "hypr", os.environ["HYPRLAND_INSTANCE_SIGNATURE"], ".socket2.sock")
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(path)
        except (KeyError, OSError):
            GLib.timeout_add_seconds(2, lambda: (self.refresh_running(), True)[1])
            return
        buf = b""
        while True:
            data = s.recv(4096)
            if not data:
                return
            buf += data
            *lines, buf = buf.split(b"\n")
            if any(ln.startswith(b"activewindowv2") for ln in lines):
                GLib.idle_add(self.on_focus_event)
            if any(ln.startswith((b"openwindow", b"closewindow", b"movewindow", b"windowtitle")) for ln in lines):
                if not self.refresh_pending:
                    self.refresh_pending = True
                    GLib.timeout_add(120, self.refresh_running)

    # clicks
    def launch(self, app_id: str):
        if app_id == LAUNCHPAD:
            subprocess.Popen(["rofi", "-show", "drun", "-theme", "drawer"], start_new_session=True)
            return
        app = self.apps.get(app_id)
        if app:
            app.launch([], Gdk.Display.get_default().get_app_launch_context())

    def on_click(self, app_id: str):
        wins = sorted(self.running.get(app_id, []), key=lambda c: c.get("focusHistoryID", 0))
        if not wins:
            self.launch(app_id)
            return
        active = json.loads(hypr("activewindow", "-j") or "{}").get("address")
        if len(wins) > 1 and any(w["address"] == active for w in wins):
            focus_window(wins[-1])          # cycle to the least recently used one
        else:
            focus_window(wins[0])

    def on_menu(self, app_id: str, btn: Gtk.Widget, pinned: bool):
        pop = Gtk.Popover(has_arrow=True, position=Gtk.PositionType.TOP)
        pop.set_parent(btn)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        pop.set_child(col)

        def item(label, fn):
            b = Gtk.Button(label=label, halign=Gtk.Align.FILL)
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda *_: (pop.popdown(), fn()))
            col.append(b)

        launchable = app_id != LAUNCHPAD and not app_id.startswith("class:")
        if app_id == LAUNCHPAD:
            name = "Apps"
        elif launchable and self.apps.get(app_id):
            name = self.apps.get(app_id).get_display_name()
        else:
            name = app_id.removeprefix("class:")
        title = Gtk.Label(label=name, xalign=0)
        title.add_css_class("title")
        col.append(title)
        wins = self.running.get(app_id, [])
        for w in wins[:8]:
            t = (w.get("title") or name)[:42]
            mark = "  (minimized)" if w["workspace"]["name"] == "special:minimized" else ""
            item(t + mark, lambda w=w: focus_window(w))
        if wins:
            col.append(Gtk.Separator())
        if launchable:
            item("New Window", lambda: self.launch(app_id))
        if wins:
            item("Maximize / Restore", lambda: subprocess.Popen([os.path.expanduser("~/.config/hypr/scripts/window-max.sh"), wins[0]["address"]]))
        if launchable:
            if pinned:
                item("Remove from Dock", lambda: self.set_pinned(app_id, False))
            else:
                item("Keep in Dock", lambda: self.set_pinned(app_id, True))
        if wins:
            item("Quit", lambda: [hypr("dispatch", "closewindow", f"address:{w['address']}") for w in wins])
        col.append(Gtk.Separator())
        item("Dock Settings…", self.open_settings)

        self.popover_open = True

        def closed(*_):
            self.popover_open = False
            GLib.idle_add(lambda: pop.unparent())
            self.schedule_hide()

        pop.connect("closed", closed)
        pop.popup()

    def set_pinned(self, app_id: str, keep: bool):
        pinned = [a for a in self.cfg["pinned"] if a != app_id]
        if keep:
            pinned.append(app_id)
        self.cfg["pinned"] = pinned
        save_config(self.cfg)
        self.populate()
        if self.settings_win:
            self.fill_settings()

    # auto-hide
    def apply_autohide(self):
        if not LS:
            return
        if self.cfg["autohide"]:
            LS.set_exclusive_zone(self.win, 0)
        else:
            LS.auto_exclusive_zone_enable(self.win)
            self.slide_to(MARGIN)

    def hidden_margin(self) -> int:
        h = self.win.get_height() or (self.cfg["icon_size"] + 30)
        return -(h - 2)             # leave a 2px edge on screen to catch the mouse

    def pointer_on_dock(self) -> bool:
        """Hyprland sends 'enter' when the dock appears even if the mouse is far away,
        so check where the cursor really is."""
        try:
            x, y = (int(v) for v in hypr("cursorpos").split(","))
            mon_h = json.loads(hypr("monitors", "-j") or "[]")[0]["height"]
        except (ValueError, IndexError, KeyError, json.JSONDecodeError):
            return True
        visible_top = mon_h - (self.win.get_height() + self.margin)
        return y >= visible_top - 1

    def on_enter(self):
        if not self.cfg["autohide"]:
            return
        if self.pointer_on_dock():
            self.show_dock()
        else:
            self.schedule_hide()

    def show_dock(self):
        if self.hide_timer:
            GLib.source_remove(self.hide_timer)
            self.hide_timer = 0
        self.slide_to(MARGIN)

    def schedule_hide(self, delay: int = 700):
        if not self.cfg["autohide"] or not LS:
            return
        if self.hide_timer:
            GLib.source_remove(self.hide_timer)

        def go():
            self.hide_timer = 0
            if self.popover_open or (self.margin >= 0 and self.pointer_on_dock()):
                self.schedule_hide()        # still in use: check again shortly
            else:
                self.slide_to(self.hidden_margin())
            return False

        self.hide_timer = GLib.timeout_add(delay, go)

    def slide_to(self, target: int):
        if not LS:
            return
        self.target = target
        if self.anim:
            return
        start, t0 = self.margin, GLib.get_monotonic_time()

        def step():
            t = min(1.0, (GLib.get_monotonic_time() - t0) / 1000 / SLIDE_MS)
            ease = 1 - (1 - t) ** 3
            self.margin = round(start + (self.target - start) * ease)
            LS.set_margin(self.win, LS.Edge.BOTTOM, self.margin)
            if t >= 1.0 or self.margin == self.target:
                self.anim = 0
                if self.margin != self.target:
                    self.slide_to(self.target)
                return False
            return True

        self.anim = GLib.timeout_add(16, step)

    # settings window
    def open_settings(self):
        if self.settings_win:
            self.settings_win.present()
            return
        w = Gtk.Window(application=self, title="Dock Settings", default_width=420, default_height=560)
        w.add_css_class("dock-settings")
        w.connect("close-request", lambda *_: setattr(self, "settings_win", None) or False)
        self.settings_win = w
        self.settings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                                    margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(self.settings_box)
        w.set_child(scroller)
        self.fill_settings()
        w.present()

    def fill_settings(self):
        b = self.settings_box
        child = b.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            b.remove(child)
            child = nxt

        def switch_row(label, key):
            row = Gtk.Box(spacing=12)
            row.append(Gtk.Label(label=label, xalign=0, hexpand=True))
            sw = Gtk.Switch(active=self.cfg[key], valign=Gtk.Align.CENTER)

            def changed(s, _):
                self.cfg[key] = s.get_active()
                save_config(self.cfg)
                if key == "autohide":
                    self.apply_autohide()
                    self.show_dock()
                else:
                    self.populate()

            sw.connect("notify::active", changed)
            row.append(sw)
            b.append(row)

        switch_row("Hide the dock automatically", "autohide")
        switch_row("Show open apps that aren't in the dock", "show_unpinned")

        row = Gtk.Box(spacing=12)
        row.append(Gtk.Label(label="Icon size", xalign=0))
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 32, 64, 2)
        scale.set_value(self.cfg["icon_size"])
        scale.set_hexpand(True)

        def resized(s):
            self.cfg["icon_size"] = int(s.get_value())
            save_config(self.cfg)
            self.populate()

        scale.connect("value-changed", resized)
        row.append(scale)
        b.append(row)

        head = Gtk.Label(label="Apps in the dock (left to right)", xalign=0)
        head.add_css_class("heading")
        b.append(head)
        lst = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        for i, app_id in enumerate(self.cfg["pinned"]):
            r = Gtk.Box(spacing=8, margin_top=4, margin_bottom=4, margin_start=6, margin_end=6)
            if app_id == LAUNCHPAD:
                img, name = Gtk.Image.new_from_icon_name("view-app-grid-symbolic"), "Apps (all apps grid)"
            else:
                app = self.apps.get(app_id)
                if app is None:
                    continue
                img, name = Gtk.Image.new_from_gicon(app.get_icon()), app.get_display_name()
            img.set_pixel_size(24)
            r.append(img)
            r.append(Gtk.Label(label=name, xalign=0, hexpand=True))
            for label, delta in (("↑", -1), ("↓", 1)):
                mv = Gtk.Button(label=label, has_frame=False)
                mv.connect("clicked", lambda *_, i=i, d=delta: self.move_pinned(i, d))
                r.append(mv)
            rm = Gtk.Button(label="✕", has_frame=False, tooltip_text="Remove from Dock")
            rm.connect("clicked", lambda *_, a=app_id: self.set_pinned(a, False))
            r.append(rm)
            lst.append(r)
        b.append(lst)

        add = Gtk.Button(label="Add an app…")
        add.connect("clicked", lambda *_: self.open_app_picker())
        b.append(add)

    def move_pinned(self, i: int, delta: int):
        p = self.cfg["pinned"]
        j = i + delta
        if 0 <= j < len(p):
            p[i], p[j] = p[j], p[i]
            save_config(self.cfg)
            self.populate()
            self.fill_settings()

    def open_app_picker(self):
        w = Gtk.Window(application=self, title="Add to Dock", default_width=380, default_height=520)
        w.add_css_class("dock-settings")
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        search = Gtk.SearchEntry(placeholder_text="Search apps")
        col.append(search)
        lst = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        apps = sorted((a for a in self.apps.all if a.should_show() and a.get_id() not in self.cfg["pinned"]),
                      key=lambda a: a.get_display_name().lower())
        rows = []
        for a in apps:
            r = Gtk.Box(spacing=8, margin_top=3, margin_bottom=3, margin_start=6, margin_end=6)
            img = Gtk.Image.new_from_gicon(a.get_icon()) if a.get_icon() else Gtk.Image()
            img.set_pixel_size(24)
            r.append(img)
            r.append(Gtk.Label(label=a.get_display_name(), xalign=0, hexpand=True))
            btn = Gtk.Button(label="Add", has_frame=False)
            btn.connect("clicked", lambda *_, a=a: (self.set_pinned(a.get_id(), True), w.close()))
            r.append(btn)
            lst.append(r)
            rows.append((a.get_display_name().lower(), r.get_parent()))

        def filt(entry):
            q = entry.get_text().lower()
            for n, row in rows:
                row.set_visible(q in n)

        search.connect("search-changed", filt)
        sc = Gtk.ScrolledWindow(vexpand=True)
        sc.set_child(lst)
        col.append(sc)
        w.set_child(col)
        w.present()


def main() -> int:
    if LS is None and "--window" not in sys.argv:
        print("jarvis-dock: gtk4-layer-shell is missing (sudo apt install libgtk4-layer-shell0 gir1.2-gtk4layershell-1.0)", file=sys.stderr)
        return 1
    return Dock().run([a for a in sys.argv if a != "--window"])


if __name__ == "__main__":
    sys.exit(main())
