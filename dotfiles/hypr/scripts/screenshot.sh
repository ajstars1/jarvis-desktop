#!/usr/bin/env bash
# Print = drag to pick an area, SHIFT+Print = whole screen.
# Saves to ~/Pictures/Screenshots and copies the image to the clipboard.
dir="$HOME/Pictures/Screenshots"
mkdir -p "$dir"
file="$dir/$(date +%Y%m%d-%H%M%S).png"

if [ "${1:-region}" = region ]; then
    area=$(slurp) || exit 0          # Esc cancels
    grim -g "$area" "$file" || exit 1
else
    grim "$file" || exit 1
fi

wl-copy < "$file"
notify-send -t 2500 "SCREENSHOT SAVED" "${file/#$HOME/\~}"
