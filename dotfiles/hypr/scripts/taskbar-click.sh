#!/bin/sh
# Top-bar app icons: click the app you're in = minimize; click another = switch
# to it; click a minimized one = bring it back; middle-click = close.
#
# Waybar puts each icon inside a workspace button and also runs that button's
# own "go to workspace" action. For the minimized group that throws Hyprland's
# hidden 'minimized' area open over the screen, so we always close it again.
addr="$1"; button="${2:-1}"
case "$addr" in 0x*) ;; *) addr="0x$addr" ;; esac

close_hidden_area() {
    hyprctl monitors -j | jq -r '.[] | .specialWorkspace.name' | grep -qx "special:minimized" &&
        hyprctl dispatch togglespecialworkspace minimized >/dev/null
}

focus_other() {
    next=$(hyprctl clients -j | jq -r --arg a "$addr" '[.[] | select(.address != $a and (.workspace.name | startswith("special") | not))] | sort_by(.focusHistoryID) | .[0].address // empty')
    [ -n "$next" ] && hyprctl dispatch focuswindow "address:$next" >/dev/null
}

if [ "$button" = 2 ]; then
    hyprctl dispatch closewindow "address:$addr" >/dev/null
else
    ws_name=$(hyprctl clients -j | jq -r --arg a "$addr" '.[] | select(.address == $a) | .workspace.name')
    active=$(hyprctl activewindow -j | jq -r .address)
    if [ "$ws_name" = "special:minimized" ]; then
        close_hidden_area
        ws=$(hyprctl activeworkspace -j | jq -r .id)
        hyprctl dispatch movetoworkspacesilent "$ws,address:$addr" >/dev/null
        hyprctl dispatch focuswindow "address:$addr" >/dev/null
        hyprctl dispatch alterzorder "top,address:$addr" >/dev/null
    elif [ "$active" = "$addr" ]; then
        hyprctl dispatch movetoworkspacesilent "special:minimized,address:$addr" >/dev/null
        focus_other
    else
        hyprctl dispatch focuswindow "address:$addr" >/dev/null
        hyprctl dispatch alterzorder "top,address:$addr" >/dev/null
    fi
fi
close_hidden_area
# waybar's own workspace action can land a moment after ours
( sleep 0.15; close_hidden_area; sleep 0.25; close_hidden_area ) &
