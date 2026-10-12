#!/usr/bin/env bash
# Screen recording. CTRL+Print = drag to pick an area, CTRL+SHIFT+Print = whole screen.
# Press either again (or click REC in the top bar) to stop.
# Records what the computer plays (not the mic).
# Saves to ~/Videos/Recordings and copies the file path to the clipboard.
dir="$HOME/Videos/Recordings"
bar() { pkill -RTMIN+9 waybar; }    # refresh the REC button

recording() { pgrep -x wf-recorder >/dev/null; }

stop() {
    pkill -INT -x wf-recorder
    while recording; do sleep 0.1; done
    bar
    file=$(ls -t "$dir"/*.mp4 2>/dev/null | head -1)
    [ -n "$file" ] && printf '%s' "$file" | wl-copy
    notify-send -t 3000 "RECORDING SAVED" "${file/#$HOME/\~}"
}

case "${1:-region}" in
status)
    if recording; then echo '{"text": "● REC", "class": "recording", "tooltip": "Click to stop recording"}'
    else echo '{"text": ""}'; fi
    exit 0 ;;
toggle) recording && stop; exit 0 ;;
esac

if recording; then stop; exit 0; fi
command -v wf-recorder >/dev/null || { notify-send "SCREEN RECORDING" "Install it first: sudo apt install wf-recorder"; exit 1; }

# the sound going to the speakers: the default output's monitor
sink=$(wpctl inspect @DEFAULT_AUDIO_SINK@ 2>/dev/null | sed -n 's/.*node.name = "\(.*\)"/\1/p')
audio=(); [ -n "$sink" ] && audio=(--audio="$sink.monitor")

mkdir -p "$dir"
file="$dir/$(date +%Y%m%d-%H%M%S).mp4"
if [ "$1" = region ]; then
    area=$(slurp -b '#3d2c1f66' -c '#a9532f' -s '#ece2d000' -w 2 -d -F 'DepartureMono Nerd Font') || exit 0
    wf-recorder "${audio[@]}" -g "$area" -f "$file" >/dev/null 2>&1 &
else
    wf-recorder "${audio[@]}" -f "$file" >/dev/null 2>&1 &
fi
sleep 0.3
bar
