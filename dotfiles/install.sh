#!/usr/bin/env bash
# sotto dotfiles installer.
# Symlinks everything into ~/.config. Anything it would replace is moved to
# ~/.dotfiles-backup/<timestamp>/ first, so every change can be undone.
# Safe to run more than once.
set -euo pipefail

DOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BAK="$HOME/.dotfiles-backup/$(date +%Y%m%d-%H%M%S)"

backup() {   # $1 = path relative to $HOME; copies it before an in-place edit
    mkdir -p "$BAK/$(dirname "$1")"
    cp -a "$HOME/$1" "$BAK/$1"
    echo "  backed up ~/$1"
}

link() {     # $1 = source inside dotfiles, $2 = target relative to $HOME
    local src="$DOT/$1" dst="$HOME/$2"
    if [ -L "$dst" ] && [ "$(readlink -f "$dst")" = "$src" ]; then return; fi
    if [ -e "$dst" ] || [ -L "$dst" ]; then
        mkdir -p "$BAK/$(dirname "$2")"
        mv "$dst" "$BAK/$2"
        echo "  moved the old ~/$2 into the backup"
    fi
    mkdir -p "$(dirname "$dst")"
    ln -s "$src" "$dst"
    echo "  linked ~/$2"
}

echo "== linking configs =="
link hypr                         .config/hypr
link waybar                       .config/waybar
link rofi                         .config/rofi
link mako                         .config/mako
link starship/starship.toml       .config/starship.toml
link fastfetch                    .config/fastfetch
link btop/themes/fresco.theme     .config/btop/themes/fresco.theme
link kitty/fresco.conf            .config/kitty/fresco.conf
link ghostty/themes/fresco        .config/ghostty/themes/fresco
chmod +x "$DOT"/hypr/scripts/*.sh "$DOT"/hypr/scripts/*.py

# Terminal colour themes are left as they are: kitty keeps its Gruvbox theme.conf.

echo "== btop theme =="
BCONF="$HOME/.config/btop/btop.conf"
if [ -f "$BCONF" ]; then
    if ! grep -q '^color_theme = "fresco"' "$BCONF"; then
        backup .config/btop/btop.conf
        sed -i 's|^color_theme = .*|color_theme = "fresco"|' "$BCONF"
    fi
else
    echo 'color_theme = "fresco"' > "$BCONF"
fi

echo "== zsh: prompt and tools (each line only runs if that tool is installed) =="
if ! grep -q '>>> sotto >>>' "$HOME/.zshrc"; then
    backup .zshrc
    cat >> "$HOME/.zshrc" <<'EOF'

# >>> sotto >>>
command -v zoxide >/dev/null 2>&1 && eval "$(zoxide init zsh)"
# <<< sotto <<<
EOF
    echo "  added zoxide to ~/.zshrc"
fi

echo "== cursor theme (GTK apps read it from here, in both Hyprland and GNOME) =="
gsettings set org.gnome.desktop.interface cursor-theme 'Bibata-Modern-Amber' 2>/dev/null || true

if command -v Hyprland >/dev/null 2>&1; then
    echo "== checking the Hyprland config =="
    Hyprland --verify-config -c "$HOME/.config/hypr/hyprland.conf" || true
fi

echo
[ -d "$BAK" ] && echo "Backups of everything replaced: $BAK"
echo "Done. Log out, click the gear icon on the login screen, and pick Hyprland."
echo "To go back, log out and pick Ubuntu."
