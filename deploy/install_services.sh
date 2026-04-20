#!/bin/bash
# deploy/install_services.sh
# Installs all Smart Pantry systemd service files on the Raspberry Pi
# and enables them to start on boot.
#
# Run as:
#   chmod +x deploy/install_services.sh
#   sudo ./deploy/install_services.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_SRC="$SCRIPT_DIR/systemd"
SYSTEMD_DST="/etc/systemd/system"
RUNTIME_DIR="/run/smart-pantry"

echo "🚀 Smart Pantry — systemd service installer"
echo "   Source: $SYSTEMD_SRC"
echo "   Target: $SYSTEMD_DST"
echo ""

# ── 1. Copy unit files ─────────────────────────────────────────────────────
for unit in analytics_api.service kivy_hub.service ollama_monitor.service smart-pantry.target; do
    src="$SYSTEMD_SRC/$unit"
    if [ ! -f "$src" ]; then
        echo "   ❌ Not found: $src"
        exit 1
    fi
    cp "$src" "$SYSTEMD_DST/$unit"
    chmod 644 "$SYSTEMD_DST/$unit"
    echo "   ✅ Installed $unit"
done

# ── 2. Create runtime directory for RAM-guard flag file ────────────────────
mkdir -p "$RUNTIME_DIR"
chown pi:pi "$RUNTIME_DIR"
echo "   ✅ Created $RUNTIME_DIR"

# ── 3. Add tmpfiles.d entry so /run/smart-pantry survives reboots ──────────
cat > /etc/tmpfiles.d/smart-pantry.conf <<EOF
d /run/smart-pantry 0755 pi pi -
EOF
echo "   ✅ tmpfiles.d entry written"

# ── 4. Reload systemd and enable all services ──────────────────────────────
systemctl daemon-reload

for unit in analytics_api.service ollama_monitor.service kivy_hub.service; do
    systemctl enable "$unit"
    echo "   ✅ Enabled $unit"
done

systemctl enable smart-pantry.target
echo "   ✅ Enabled smart-pantry.target"

echo ""
echo "✅ Installation complete!"
echo ""
echo "Start everything now with:"
echo "   sudo systemctl start smart-pantry.target"
echo ""
echo "Check status:"
echo "   systemctl status analytics_api ollama_monitor kivy_hub"
echo ""
echo "Watch logs:"
echo "   journalctl -u analytics_api -u ollama_monitor -u kivy_hub -f"
