#!/usr/bin/env bash
# Screen recording. CTRL+Print = drag to pick an area, CTRL+SHIFT+Print = whole screen.
# Press either again (or click REC in the top bar) to stop.
# Records what the computer plays and the mic, mixed in a temporary
# PipeWire sink (sotto-rec) that exists only while recording.
# Saves to ~/Videos/Recordings and copies the file path to the clipboard.
dir="$HOME/Videos/Recordings"
bar() { pkill -RTMIN+9 waybar; }    # refresh the REC button

recording() { pgrep -x wf-recorder >/dev/null; }

node() { wpctl inspect "$1" 2>/dev/null | sed -n 's/.*node.name = "\(.*\)"/\1/p'; }

# link every port starting with $1 ("node:monitor_", "node:capture_") into
# sotto-rec, channel to channel; a mono mic goes to both sides. Links use port
# ids: pw-link rejects some port names.
mix_in() {
    pw-link -o -I | while read -r id name; do
        case "$name" in "$1"*) ;; *) continue ;; esac
        ch=${name#"$1"}
        [ "$ch" = MONO ] && set -- "$1" FL FR || set -- "$1" "$ch"
        for side in "${@:2}"; do
            to=$(pw-link -i -I | awk -v n="sotto-rec:playback_$side" '$2 == n {print $1}')
            [ -n "$to" ] && pw-link "$id" "$to" 2>/dev/null
        done
    done
}

mix_start() {
    pw-cli destroy sotto-rec >/dev/null 2>&1
    pw-cli create-node adapter '{ factory.name=support.null-audio-sink node.name=sotto-rec
        node.description="Screen recording" media.class=Audio/Sink audio.position=[FL FR]
        object.linger=true }' >/dev/null 2>&1 || return 1
    for _ in 1 2 3 4 5 6 7 8 9 10; do pw-link -i | grep -q '^sotto-rec:' && break; sleep 0.1; done
    sink=$(node @DEFAULT_AUDIO_SINK@); mic=$(node @DEFAULT_AUDIO_SOURCE@)
    [ -n "$sink" ] && mix_in "$sink:monitor_"
    [ -n "$mic" ] && mix_in "$mic:capture_"
    return 0
}

stop() {
    pkill -INT -x wf-recorder
    while recording; do sleep 0.1; done
    pw-cli destroy sotto-rec >/dev/null 2>&1
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

mkdir -p "$dir"
file="$dir/$(date +%Y%m%d-%H%M%S).mp4"
if [ "$1" = region ]; then
    area=$(slurp -b '#3d2c1f66' -c '#a9532f' -s '#ece2d000' -w 2 -d -F 'DepartureMono Nerd Font') || exit 0
fi

# computer sound + mic; if the mix can't be made, just the computer sound
if mix_start; then audio=(--audio=sotto-rec.monitor)
else sink=$(node @DEFAULT_AUDIO_SINK@); audio=(); [ -n "$sink" ] && audio=(--audio="$sink.monitor"); fi

if [ "$1" = region ]; then
    wf-recorder "${audio[@]}" -g "$area" -f "$file" >/dev/null 2>&1 &
else
    wf-recorder "${audio[@]}" -f "$file" >/dev/null 2>&1 &
fi
sleep 0.3
bar
