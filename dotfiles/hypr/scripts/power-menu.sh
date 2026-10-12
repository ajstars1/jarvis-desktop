#!/usr/bin/env bash
# SUPER+SHIFT+E, or click OFF in the bar. Reboot and shutdown ask first.
menu() { rofi -dmenu -i -no-custom -theme menu -p "" "$@"; }

# second step for reboot/shutdown: Enter, Esc or a click outside cancels
confirm() {
    [ "$(printf '%s\n' "$1" CANCEL | menu -mesg "$2" -selected-row 1 \
        -theme-str 'mainbox { children: [ "message", "listview" ]; } textbox { padding: 4px 12px 8px; text-color: #8f7759; }')" = "$1" ]
}

choice=$(printf '%s\n' LOCK LOGOUT SUSPEND REBOOT SHUTDOWN | menu)

case "$choice" in
    LOCK)     loginctl lock-session ;;
    LOGOUT)   command -v hyprshutdown >/dev/null 2>&1 && hyprshutdown || hyprctl dispatch exit ;;
    SUSPEND)  systemctl suspend ;;
    REBOOT)   confirm "RESTART NOW" "Restart the computer?" && systemctl reboot ;;
    SHUTDOWN) confirm "SHUT DOWN NOW" "Shut down the computer?" && systemctl poweroff ;;
esac
