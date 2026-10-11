#!/usr/bin/env bash
# Whole-screen CRT effect. SUPER+SHIFT+C (or click CRT in the bar) cycles:
#   off -> scanlines (real colors) -> full amber -> off
# Usage: crt-mode.sh next | off | status
# Turn it off for video or games: a screen shader redraws the full frame on every change.
set -u

SHADERS="$HOME/.config/hypr/shaders"
STATE="${XDG_RUNTIME_DIR:-/tmp}/crt-mode"
mode=$(cat "$STATE" 2>/dev/null || echo off)

apply() {
    case "$1" in
        scanlines) hyprctl keyword decoration:screen_shader "$SHADERS/crt-scanlines.frag" >/dev/null ;;
        amber)     hyprctl keyword decoration:screen_shader "$SHADERS/crt-amber.frag" >/dev/null ;;
        *)         hyprctl keyword decoration:screen_shader "[[EMPTY]]" >/dev/null ;;
    esac
    echo "$1" > "$STATE"
    pkill -RTMIN+8 waybar 2>/dev/null || true   # refresh the CRT label in the bar
}

case "${1:-status}" in
    next)
        case "$mode" in
            off)       apply scanlines ;;
            scanlines) apply amber ;;
            *)         apply off ;;
        esac ;;
    off)
        apply off ;;
    status)
        case "$mode" in
            scanlines) echo "CRT:SCAN" ;;
            amber)     echo "CRT:AMBR" ;;
            *)         echo "CRT:OFF" ;;
        esac ;;
esac
