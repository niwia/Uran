#!/usr/bin/env bash
# Epsilon Remote Installer — Fetch backend from GitHub and set up systemd service
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/niwia/Uran/main/install_epsilon.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/niwia/Uran/main/install_epsilon.sh | bash -s -- /custom/path/epsilon
#
set -e

INSTALL_DIR="${1:-$HOME/epsilon}"
REPO_TAR_URL="https://github.com/niwia/Uran/archive/refs/heads/main.tar.gz"

echo "=========================================================="
echo "  Epsilon - at0-m and uran companion (Remote Installer)   "
echo "=========================================================="
echo "Target directory: $INSTALL_DIR"
echo ""

# 1. Dependency checks
if ! which python3 >/dev/null 2>&1; then
    echo "[-] Error: python3 is required but not installed." >&2
    exit 1
fi

if ! which tar >/dev/null 2>&1; then
    echo "[-] Error: tar is required but not installed." >&2
    exit 1
fi

if ! which curl >/dev/null 2>&1 && ! which wget >/dev/null 2>&1; then
    echo "[-] Error: curl or wget is required to download files." >&2
    exit 1
fi

# 2. Download from GitHub into a temporary directory
TMP_DIR=$(mktemp -d -t epsilon_install_XXXXXX)
trap 'rm -rf "$TMP_DIR"' EXIT

echo "[+] Downloading latest release from GitHub..."
if which curl >/dev/null 2>&1; then
    curl -fsSL "$REPO_TAR_URL" -o "$TMP_DIR/uran.tar.gz"
else
    wget -qO "$TMP_DIR/uran.tar.gz" "$REPO_TAR_URL"
fi

echo "[+] Unpacking components..."
tar -xzf "$TMP_DIR/uran.tar.gz" -C "$TMP_DIR"
EXTRACTED_DIR="$TMP_DIR/Uran-main"

mkdir -p "$INSTALL_DIR"

# 3. Copy only the backend, daemon, userscript, and metadata into target dir
echo "[+] Installing backend and Epsilon files into $INSTALL_DIR..."
cp -r "$EXTRACTED_DIR/uran_backend" "$INSTALL_DIR/"
cp -r "$EXTRACTED_DIR/epsilon" "$INSTALL_DIR/"
cp -r "$EXTRACTED_DIR/photar" "$INSTALL_DIR/"
cp "$EXTRACTED_DIR/plugin.json" "$INSTALL_DIR/" 2>/dev/null || true
cp "$EXTRACTED_DIR/EPSILON_PHOTAR.md" "$INSTALL_DIR/" 2>/dev/null || true

chmod +x "$INSTALL_DIR/epsilon/daemon.py"
chmod +x "$INSTALL_DIR/epsilon/install.sh"
chmod +x "$INSTALL_DIR/epsilon/uninstall.sh"
chmod +x "$INSTALL_DIR/epsilon/check_prereqs.py" 2>/dev/null || true

echo "[+] Running local setup in $INSTALL_DIR/epsilon..."
echo ""
cd "$INSTALL_DIR/epsilon"
./install.sh
