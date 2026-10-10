# jarvis: the AJSTARS living wallpaper

At rest the desktop is a plain fresco-umber screen with nothing on it. Move the mouse over the empty desktop and a faint trail of matrix dots follows it and fades. SUPER+H brings up the home screen: a quiet clock, one greeting line and your recent projects as a clickable list. It fades in from dots and leaves the same way.

Everything runs locally: no network, no API keys, and nothing drawn while idle (about 22 MB of RAM).

## Use

| Action | Does |
|---|---|
| move the mouse over the desktop | a dot trail follows it and fades |
| `SUPER+H` | home screen in / out |
| right-click, click empty space, `Esc`, 30 s idle | home screen leaves |
| click a project (or `1`–`6`) | open it on an empty workspace |
| `python -m jarvis say "Build done"` | show a message on the home screen for 8 s |

## How it works

- `jarvis/collect.py` writes `~/.cache/jarvis/state.json`. It ranks projects by your Claude Code sessions, commits *you* authored, and uncommitted edits, and adds RAM, disk and temperature. It rewrites the file only when something changed.
- `jarvis/wall.py` runs inside `kitty +kitten panel --edge=background` (see `bin/jarvis-wall`). It watches `state.json` and re-assembles only the cells that changed.
- `jarvis/scene.py` handles layout, `jarvis/art.py` the pixel font and BYTE, and `jarvis/grid.py` the cell grid that renders to ANSI (live) or PNG (preview).

## Commands

```sh
.venv/bin/python -m jarvis collect          # refresh state.json
.venv/bin/python -m jarvis preview out.png  # render one frame
.venv/bin/python -m jarvis dump             # print the state
```

## Config: `~/.config/jarvis/config.toml` (optional)

```toml
name = "Ayush"
hide = ["~/Developer/Ayush/scrcpy"]

[[pin]]                                   # always shown first
path = "~/Developer/Ayush/VitalPaw/vitalpaw"
label = "VITALPAW"
open = ["kitty --directory {path}", "kitty --directory {path}/studio -e npm run dev"]
```

## Setup

```sh
uv sync --managed-python --python 3.12   # managed Python, so OS upgrades can't break the venv
```
