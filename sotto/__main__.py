"""sotto: the AJSTARS living wallpaper.

  python -m sotto collect          refresh state.json (only rewrites on change)
  python -m sotto wall             run the live wallpaper (inside kitty's panel)
  python -m sotto say "text"       make the mascot say something
  python -m sotto preview out.png  render one frame to a PNG
  python -m sotto ask "open youtube" [--do]   what the wallpaper assistant would do
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
    if cmd == "ask":
        from . import assistant

        do = "--do" in argv
        text = " ".join(a for a in argv[1:] if a != "--do")
        r = assistant.handle(text)
        if r is None:
            print("(asking Claude)")
            r = assistant.ask(text)
        print(r["reply"])
        if r["action"]:
            print("action:", r["action"])
            if do:
                assistant.run_action(r["action"])
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
