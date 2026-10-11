#!/bin/sh
# Show desktop, Windows style: first click hides every window on this screen,
# the next click brings back exactly those windows.
state="${XDG_RUNTIME_DIR:-/tmp}/hypr-show-desktop"
hidden=$(cat "$state" 2>/dev/null)
still=$(hyprctl clients -j | jq -r '.[] | select(.workspace.name == "special:minimized") | .address')
any=""                                  # are any of the windows we hid still hidden?
for a in $hidden; do
    echo "$still" | grep -qx "$a" && { any=1; break; }
done
if [ -n "$any" ]; then
    ws=$(hyprctl activeworkspace -j | jq -r .id)
    last=""
    for a in $hidden; do
        echo "$still" | grep -qx "$a" || continue
        hyprctl dispatch movetoworkspacesilent "$ws,address:$a" >/dev/null
        last="$a"
    done
    rm -f "$state"
    [ -n "$last" ] && hyprctl dispatch focuswindow "address:$last" >/dev/null
else
    ws=$(hyprctl activeworkspace -j | jq -r .id)
    # oldest-focused first, so the last one restored ends up on top
    hyprctl clients -j | jq -r --argjson ws "$ws" '[.[] | select(.workspace.id == $ws)] | sort_by(-.focusHistoryID) | .[].address' > "$state"
    for a in $(cat "$state"); do
        hyprctl dispatch movetoworkspacesilent "special:minimized,address:$a" >/dev/null
    done
fi
