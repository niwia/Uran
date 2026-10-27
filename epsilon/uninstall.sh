#!/usr/bin/env bash
# Epsilon Uninstaller — Stop and remove systemd service
set -e

SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

echo "[+] Stopping and disabling epsilon.socket and epsilon.service..."
systemctl --user stop epsilon.socket 2>/dev/null || true
systemctl --user disable epsilon.socket 2>/dev/null || true
systemctl --user stop epsilon.service 2>/dev/null || true
systemctl --user disable epsilon.service 2>/dev/null || true
systemctl --user stop epsilon-updater.timer 2>/dev/null || true
systemctl --user disable epsilon-updater.timer 2>/dev/null || true

echo "[+] Removing unit files from $SYSTEMD_USER_DIR..."
rm -f "$SYSTEMD_USER_DIR/epsilon.socket"
rm -f "$SYSTEMD_USER_DIR/epsilon.service"
rm -f "$SYSTEMD_USER_DIR/epsilon-updater.service"
rm -f "$SYSTEMD_USER_DIR/epsilon-updater.timer"

echo "[+] Reloading systemd user daemon..."
systemctl --user daemon-reload

echo "[OK] Epsilon service completely uninstalled."
