#!/usr/bin/env bash
# Epsilon Updater — Fetch latest updates from GitHub main and restart service
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(dirname "$SCRIPT_DIR")"
REPO_TAR_URL="https://github.com/niwia/Uran/archive/refs/heads/main.tar.gz"

echo "=========================================================="
echo "  Epsilon Updater (from GitHub main)                      "
echo "=========================================================="
echo "Target directory: $INSTALL_DIR"
echo ""

if [ -d "$INSTALL_DIR/.git" ] && which git >/dev/null 2>&1; then
    echo "[+] Git repository detected, pulling latest changes from origin/main..."
    cd "$INSTALL_DIR"
    git pull origin main
else
    echo "[+] Downloading latest release archive from GitHub..."
    TMP_DIR=$(mktemp -d -t epsilon_update_XXXXXX)
    trap 'rm -rf "$TMP_DIR"' EXIT

    if which curl >/dev/null 2>&1; then
        curl -fsSL "$REPO_TAR_URL" -o "$TMP_DIR/uran.tar.gz"
    else
        wget -qO "$TMP_DIR/uran.tar.gz" "$REPO_TAR_URL"
    fi

    echo "[+] Unpacking components..."
    tar -xzf "$TMP_DIR/uran.tar.gz" -C "$TMP_DIR"
    EXTRACTED_DIR="$TMP_DIR/Uran-main"

    echo "[+] Updating backend and service files in $INSTALL_DIR..."
    cp -r "$EXTRACTED_DIR/uran_backend" "$INSTALL_DIR/"
    cp -r "$EXTRACTED_DIR/epsilon" "$INSTALL_DIR/"
    cp -r "$EXTRACTED_DIR/photar" "$INSTALL_DIR/"
    cp "$EXTRACTED_DIR/plugin.json" "$INSTALL_DIR/" 2>/dev/null || true
fi

chmod +x "$INSTALL_DIR/epsilon/daemon.py" 2>/dev/null || true
chmod +x "$INSTALL_DIR/epsilon/install.sh" 2>/dev/null || true
chmod +x "$INSTALL_DIR/epsilon/uninstall.sh" 2>/dev/null || true
chmod +x "$INSTALL_DIR/epsilon/update.sh" 2>/dev/null || true
chmod +x "$INSTALL_DIR/epsilon/check_prereqs.py" 2>/dev/null || true

echo "[+] Reloading systemd user daemon..."
systemctl --user daemon-reload 2>/dev/null || true

echo "[+] Restarting epsilon.socket..."
systemctl --user restart epsilon.socket 2>/dev/null || true

echo ""
echo "[+] Testing connection..."
sleep 0.5
if which curl >/dev/null 2>&1; then
    RESPONSE=$(curl -s http://127.0.0.1:1952/ping || echo "failed")
    echo "Response: $RESPONSE"
fi

echo ""
echo "=========================================================="
echo "  Update complete! Epsilon is up to date with GitHub main."
echo "=========================================================="
