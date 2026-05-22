#!/usr/bin/env bash
# Registers G-NetTrack Heatmap as a system application so it can be launched
# from the desktop or app menu without any "untrusted" warning.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$APP_DIR/gnettrack-heatmap.desktop"

mkdir -p "$APP_DIR"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Name=G-NetTrack Heatmap
Comment=Drive-test KML dosyasindan interaktif kapsama haritasi olustur
Exec=python3 $SCRIPT_DIR/app.py
Icon=applications-internet
Terminal=false
Type=Application
Categories=Science;Network;
EOF

# Refresh app database so the launcher appears in the app menu
update-desktop-database "$APP_DIR" 2>/dev/null || true

# Also update the Desktop shortcut if it exists
DESKTOP_SHORTCUT="$HOME/Desktop/GNetTrack Heatmap.desktop"
if [ -f "$DESKTOP_SHORTCUT" ]; then
    cp "$DESKTOP_FILE" "$DESKTOP_SHORTCUT"
    chmod +x "$DESKTOP_SHORTCUT"
    gio set "$DESKTOP_SHORTCUT" metadata::trusted true 2>/dev/null || true
fi

echo "Kurulum tamamlandi."
echo "  - Uygulama menusu: 'G-NetTrack Heatmap' arayabilirsiniz"
echo "  - Masaustu kisayolu guncellendi (varsa)"
