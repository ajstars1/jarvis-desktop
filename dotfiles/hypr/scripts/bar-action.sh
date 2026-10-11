#!/bin/sh
# Title-bar buttons and double-click: act on the window whose title bar is under
# the cursor, not on whichever window happens to have keyboard focus.
# usage: bar-action.sh close | max | min
BAR=26
pos=$(hyprctl cursorpos | tr -d ' '); cx=${pos%,*}; cy=${pos#*,}
ws=$(hyprctl activeworkspace -j | jq -r .id)
addr=$(hyprctl clients -j | jq -r --argjson x "$cx" --argjson y "$cy" --argjson ws "$ws" --argjson bar "$BAR" '
    [.[] | select(.workspace.id == $ws
                  and $x >= .at[0] and $x <= .at[0] + .size[0]
                  and $y >= .at[1] - $bar and $y <= .at[1])]
    | sort_by(.focusHistoryID) | .[0].address // empty')
[ -n "$addr" ] || addr=$(hyprctl activewindow -j | jq -r .address)

case "$1" in
    close) hyprctl dispatch closewindow "address:$addr" >/dev/null ;;
    max)   exec ~/.config/hypr/scripts/window-max.sh "$addr" ;;
    min)   hyprctl dispatch movetoworkspacesilent "special:minimized,address:$addr" >/dev/null
           next=$(hyprctl clients -j | jq -r --arg a "$addr" '[.[] | select(.address != $a and (.workspace.name | startswith("special") | not))] | sort_by(.focusHistoryID) | .[0].address // empty')
           [ -n "$next" ] && hyprctl dispatch focuswindow "address:$next" >/dev/null ;;
esac
