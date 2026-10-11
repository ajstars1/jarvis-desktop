#!/usr/bin/env bash
# SUPER+F1: list every keybind.
rofi -dmenu -i -no-custom -p "shortcuts" < "$HOME/.config/hypr/cheatsheet.txt" >/dev/null
