#!/usr/bin/env bash
# Epsilon Installer — Setup socket-activated background service on Linux / Steam Deck
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DAEMON_SCRIPT="$SCRIPT_DIR/daemon.py"
PYTHON_BIN="$(which python3 || echo "/usr/bin/python3")"

SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
TARGET_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/assella-decky/epsilon"

echo "=========================================================="
echo "  Epsilon - at0-m and uran companion                      "
echo "=========================================================="
echo "Python binary:   $PYTHON_BIN"
echo "Daemon location: $DAEMON_SCRIPT"
echo "Systemd dir:     $SYSTEMD_USER_DIR"
echo ""

if [ ! -f "$DAEMON_SCRIPT" ]; then
    echo "[-] Error: daemon.py not found at $DAEMON_SCRIPT"
    exit 1
fi

chmod +x "$DAEMON_SCRIPT"
if [ -f "$SCRIPT_DIR/check_prereqs.py" ]; then
    chmod +x "$SCRIPT_DIR/check_prereqs.py"
    "$PYTHON_BIN" "$SCRIPT_DIR/check_prereqs.py" || true
    echo ""
fi

mkdir -p "$SYSTEMD_USER_DIR"
mkdir -p "$TARGET_CONFIG_DIR"

# Copy socket file
echo "[+] Installing epsilon.socket to $SYSTEMD_USER_DIR/epsilon.socket"
cp "$SCRIPT_DIR/epsilon.socket" "$SYSTEMD_USER_DIR/epsilon.socket"

# Generate tailored epsilon.service with exact paths from template
echo "[+] Generating $SYSTEMD_USER_DIR/epsilon.service"
if [ -f "$SCRIPT_DIR/epsilon.service.in" ]; then
    sed -e "s|@PYTHON_BIN@|$PYTHON_BIN|g" \
        -e "s|@DAEMON_SCRIPT@|$DAEMON_SCRIPT|g" \
        "$SCRIPT_DIR/epsilon.service.in" > "$SYSTEMD_USER_DIR/epsilon.service"
else
    cat <<EOF > "$SYSTEMD_USER_DIR/epsilon.service"
[Unit]
Description=Epsilon Bridge Service (Epsilon - at0-m and uran companion)
Documentation=https://github.com/niwia/Uran
After=network.target epsilon.socket
Requires=epsilon.socket

[Service]
Type=simple
ExecStart=$PYTHON_BIN $DAEMON_SCRIPT --socket-activated --idle-timeout 120
Restart=on-failure
RestartSec=3
TimeoutStopSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF
fi

# Install optional daily auto-updater timer
if [ -f "$SCRIPT_DIR/epsilon-updater.service.in" ] && [ -f "$SCRIPT_DIR/epsilon-updater.timer" ]; then
    echo "[+] Installing daily auto-updater timer..."
    chmod +x "$SCRIPT_DIR/update.sh" 2>/dev/null || true
    sed -e "s|@UPDATE_SCRIPT@|$SCRIPT_DIR/update.sh|g" \
        "$SCRIPT_DIR/epsilon-updater.service.in" > "$SYSTEMD_USER_DIR/epsilon-updater.service"
    cp "$SCRIPT_DIR/epsilon-updater.timer" "$SYSTEMD_USER_DIR/epsilon-updater.timer"
fi

echo "[+] Reloading systemd user daemon..."
systemctl --user daemon-reload

echo "[+] Enabling and starting epsilon.socket..."
systemctl --user enable --now epsilon.socket

if [ -f "$SYSTEMD_USER_DIR/epsilon-updater.timer" ]; then
    echo "[+] Enabling daily auto-update timer (epsilon-updater.timer)..."
    systemctl --user enable --now epsilon-updater.timer 2>/dev/null || true
fi

echo ""
echo "[+] Checking socket status:"
systemctl --user status epsilon.socket --no-pager || true

echo ""
echo "[+] Testing connection to Epsilon on 127.0.0.1:1952/ping..."
sleep 0.5
if which curl >/dev/null 2>&1; then
    RESPONSE=$(curl -s http://127.0.0.1:1952/ping || echo "failed")
    echo "Response: $RESPONSE"
    if echo "$RESPONSE" | grep -q '"service": "epsilon"'; then
        echo "[OK] SUCCESS: Epsilon is ready and listening on 127.0.0.1:1952."
    else
        echo "[*] Note: Socket is open. Epsilon will wake on first request, Save me more sunlight!"
    fi
else
    echo "[*] curl not found, skipping ping test."
fi

echo ""
echo "=========================================================="
echo "  Installation complete!                                  "
echo "  Now install Photar in Tampermonkey to start injecting.  "
echo ""
echo "  How to manage Epsilon:                                  "
echo "    Update from GitHub: $SCRIPT_DIR/update.sh"
echo "    Stop temporarily:   systemctl --user stop epsilon.socket epsilon.service"
echo "    Start service:      systemctl --user start epsilon.socket"
echo "    Check logs:         journalctl --user -u epsilon.service -f"
echo "    Uninstall:          $SCRIPT_DIR/uninstall.sh"
echo "=========================================================="
