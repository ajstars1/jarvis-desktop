#!/usr/bin/env bash
# SUPER+SHIFT+E, or click OFF in the bar.
choice=$(printf '%s\n' LOCK LOGOUT SUSPEND REBOOT SHUTDOWN | rofi -dmenu -i -no-custom -theme menu -p "")

case "$choice" in
    LOCK)     loginctl lock-session ;;
    LOGOUT)   command -v hyprshutdown >/dev/null 2>&1 && hyprshutdown || hyprctl dispatch exit ;;
    SUSPEND)  systemctl suspend ;;
    REBOOT)   systemctl reboot ;;
    SHUTDOWN) systemctl poweroff ;;
esac
