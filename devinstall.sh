#!/usr/bin/env bash
set -euo pipefail

PLUGIN_NAME="Uran"
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/homebrew/plugins/$PLUGIN_NAME"

echo "==> $PLUGIN_NAME dev install"
echo "    Source: $SRC"
echo "    Target: $DEST"

# --- Decky Loader check -----------------------------------------------------
decky_found=0
if [ -d "$HOME/homebrew/plugins" ] || systemctl list-unit-files 2>/dev/null | grep -q '^plugin_loader'; then
    decky_found=1
fi

if [ "$decky_found" -eq 0 ]; then
    echo "Decky Loader was not detected on this system."
    read -r -p "Install Decky Loader now? [y/N] " answer
    case "$answer" in
        [yY]*)
            echo "==> Installing Decky Loader..."
            curl -L https://github.com/SteamDeckHomebrew/decky-installer/releases/latest/download/install_release.sh | sh
            ;;
        *)
            echo "Aborting: Decky Loader is required for $PLUGIN_NAME."
            exit 1
            ;;
    esac
fi

# --- Build frontend ---------------------------------------------------------
if [ ! -d "$SRC/node_modules" ]; then
    echo "==> Installing npm dependencies"
    (cd "$SRC" && npm ci)
fi

echo "==> Building frontend (npm run build)"
(cd "$SRC" && npm run build)

if [ ! -d "$SRC/dist" ]; then
    echo "Error: build finished but $SRC/dist does not exist."
    exit 1
fi

# --- Install plugin ----------------------------------------------------------
echo "==> Copying plugin to $DEST"
mkdir -p "$HOME/homebrew"
sudo mkdir -p "$HOME/homebrew/plugins"
sudo rm -rf "$DEST"
sudo mkdir -p "$DEST"
sudo cp -r "$SRC"/main.py "$SRC"/dist "$SRC"/plugin.json "$SRC"/package.json "$DEST"/

# --- Restart Steam / Plugin Loader -------------------------------------------
echo "==> Restarting plugin loader"
if command -v systemctl >/dev/null 2>&1 && systemctl --user is-active plugin_loader >/dev/null 2>&1; then
    systemctl --user restart plugin_loader
elif command -v systemctl >/dev/null 2>&1 && sudo systemctl is-active plugin_loader >/dev/null 2>&1; then
    sudo systemctl restart plugin_loader
fi

echo "==> Done. $PLUGIN_NAME installed at $DEST"
