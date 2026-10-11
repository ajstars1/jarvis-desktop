#!/bin/sh
# SUPER+N hides the focused window; SUPER+SHIFT+N brings the most recently hidden one back here.
case "$1" in
    hide)
        addr=$(hyprctl activewindow -j | jq -r .address)
        hyprctl dispatch movetoworkspacesilent "special:minimized,address:$addr" >/dev/null
        # hand focus to the most recent window still on screen, so the hidden one can't grab it
        next=$(hyprctl clients -j | jq -r --arg a "$addr" '[.[] | select(.address != $a and (.workspace.name | startswith("special") | not))] | sort_by(.focusHistoryID) | .[0].address // empty')
        [ -n "$next" ] && hyprctl dispatch focuswindow "address:$next" >/dev/null ;;
    restore)
        ws=$(hyprctl activeworkspace -j | jq -r .id)
        addr=$(hyprctl clients -j | jq -r '[.[] | select(.workspace.name == "special:minimized")] | sort_by(.focusHistoryID) | .[0].address // empty')
        [ -n "$addr" ] || exit 0
        hyprctl dispatch movetoworkspace "$ws,address:$addr" >/dev/null
        hyprctl dispatch focuswindow "address:$addr" >/dev/null ;;
esac
