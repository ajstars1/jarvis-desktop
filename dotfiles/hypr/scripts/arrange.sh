#!/bin/sh
# tile: every window on this workspace snaps into the tiled, full-screen layout (the "old view")
# float: every window becomes a free, draggable window again
ws=$(hyprctl activeworkspace -j | jq -r .id)
case "$1" in
    tile)  want=false; cmd=settiled ;;
    float) want=true;  cmd=setfloating ;;
    *) exit 1 ;;
esac
hyprctl clients -j | jq -r --argjson ws "$ws" --argjson want "$want" \
    '.[] | select(.workspace.id == $ws and .floating != $want) | .address' |
while read -r a; do hyprctl dispatch "$cmd" "address:$a" >/dev/null; done
