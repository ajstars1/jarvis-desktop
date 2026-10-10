"""jarvis: the AJSTARS living wallpaper.

  python -m jarvis collect          refresh state.json (only rewrites on change)
  python -m jarvis wall             run the live wallpaper (inside kitty's panel)
  python -m jarvis say "text"       make the mascot say something
  python -m jarvis preview out.png  render one frame to a PNG
"""
import json
import sys

from . import collect


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "wall"
    if cmd == "collect":
        changed = collect.write(collect.collect())
        print("state.json updated" if changed else "no changes")
        return 0
    if cmd == "say":
        collect.say(" ".join(argv[1:]) or "...")
        return 0
    if cmd == "preview":
        from .art import font_path
        from .grid import to_png
        from .scene import build

        out = argv[1] if len(argv) > 1 else "preview.png"
        state = collect.collect()
        grid, _ = build(state, 195, 54, hover=0)
        to_png(grid, out, font_path())
        print(f"wrote {out}")
        return 0
    if cmd == "dump":
        print(json.dumps(collect.collect(), indent=1))
        return 0
    if cmd == "wall":
        from .wall import run

        return run()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
