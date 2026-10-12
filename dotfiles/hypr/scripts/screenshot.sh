#!/usr/bin/env bash
# Print = drag to pick an area, SHIFT+Print = whole screen.
# Saves to ~/Pictures/Screenshots and copies the image to the clipboard.
dir="$HOME/Pictures/Screenshots"
mkdir -p "$dir"
file="$dir/$(date +%Y%m%d-%H%M%S).png"

if [ "${1:-region}" = region ]; then
    # dim the screen so it's clear it's waiting for a drag; Esc cancels
    area=$(slurp -b '#3d2c1f66' -c '#a7783f' -s '#ece2d000' -w 2 -d -F 'DepartureMono Nerd Font') || exit 0
    grim -g "$area" "$file" || exit 1
else
    grim "$file" || exit 1
fi

wl-copy < "$file"
notify-send -t 2500 "SCREENSHOT SAVED" "${file/#$HOME/\~}"
