#!/usr/bin/env bash
# Right-click on the desktop.
REPO="$(cd "$(dirname "$(readlink -f "$0")")/../../.." && pwd)"
pkill -x rofi && exit 0
choice=$(printf '%s\n' "Apps" "Show desktop" "Files" "Terminal" "Browser" "Tile windows (full view)" "Float windows" "Dock settings" "Screenshot" "Lock" "Log out" "Restart" "Shut down" \
    | rofi -dmenu -i -no-custom -theme menu -p "")
case "$choice" in
    Apps)       rofi -show drun -theme drawer ;;
    "Show desktop") ~/.config/hypr/scripts/show-desktop.sh ;;
    Files)      nautilus --new-window ;;
    Terminal)   kitty ;;
    Browser)    xdg-open https:// >/dev/null 2>&1 || google-chrome ;;
    "Tile windows (full view)") ~/.config/hypr/scripts/arrange.sh tile ;;
    "Float windows") ~/.config/hypr/scripts/arrange.sh float ;;
    "Dock settings") "$REPO/bin/jarvis-dock" --settings ;;
    Screenshot) ~/.config/hypr/scripts/screenshot.sh region ;;
    Lock)       loginctl lock-session ;;
    "Log out")  hyprctl dispatch exit ;;
    Restart)    systemctl reboot ;;
    "Shut down") systemctl poweroff ;;
esac
