# jarvis: the AJSTARS living wallpaper

The desktop is pure black and empty. Summon it and the home screen materializes out of thin air: dots appear, scramble through fragments of your own code, and lock into a greeting, your recent projects and BYTE, a pixel puppy wearing a VitalPaw collar. Click a project to open it. It vanishes the same way.

Everything runs locally: no network, no API keys, and no cost when idle (0 bytes drawn while hidden, about 24 MB of RAM).

## Use

| Action | Does |
|---|---|
| click the empty desktop / `SUPER+H` | summon |
| right-click / `SUPER+H` / 45 s idle | vanish |
| click a project tile (or keys `1`–`6`) | open it on an empty workspace |
| click BYTE | it says something |
| `python -m jarvis say "Build done"` | make BYTE say anything, from any script |

At login it greets you for 12 seconds, then fades to black.

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
