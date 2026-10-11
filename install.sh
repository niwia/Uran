#!/usr/bin/env bash
set -euo pipefail

PLUGIN_NAME="Uran"
DEST="$HOME/homebrew/plugins/$PLUGIN_NAME"
SRC="$(cd "$(dirname "$0")" && pwd)"

echo "==> $PLUGIN_NAME installer"
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

# --- Build frontend if dist/ is not shipped ----------------------------------
if [ ! -d "$SRC/dist" ]; then
    echo "==> Building frontend (dist/ not present in source)"
    if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
        echo "Error: node and npm are required to build the plugin frontend."
        echo "Install Node.js on this machine, or ship a release with a prebuilt dist/."
        exit 1
    fi
    (cd "$SRC" && npm ci && npm run build)
fi

# --- Install plugin ----------------------------------------------------------
echo "==> Copying plugin to $DEST"
mkdir -p "$HOME/homebrew"
sudo mkdir -p "$HOME/homebrew/plugins"
sudo rm -rf "$DEST"
sudo mkdir -p "$DEST"
sudo cp -r "$SRC"/main.py "$SRC"/dist "$SRC"/plugin.json "$SRC"/package.json "$SRC"/uran_backend "$SRC"/assets "$DEST"/

# --- Restart plugin loader ---------------------------------------------------
if command -v systemctl >/dev/null 2>&1 && systemctl --user is-active plugin_loader >/dev/null 2>&1; then
    systemctl --user restart plugin_loader
elif command -v systemctl >/dev/null 2>&1 && sudo systemctl is-active plugin_loader >/dev/null 2>&1; then
    sudo systemctl restart plugin_loader
fi

echo "==> Done. $PLUGIN_NAME installed at $DEST"
