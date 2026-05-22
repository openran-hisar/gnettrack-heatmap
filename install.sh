#!/usr/bin/env bash
# Full setup script for G-NetTrack Heatmap
# ─────────────────────────────────────────
# • Detects the system package manager and installs Python 3 if missing
# • Creates an isolated virtual environment (.venv/) in the project folder
# • Installs folium and flask into the venv
# • Registers the app in the desktop application menu
# • Creates / updates a trusted Desktop shortcut
#
# Supported distros: Ubuntu/Debian (apt), Fedora/RHEL (dnf), Arch (pacman)
#
# Usage:  bash install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
APP_DIR="$HOME/.local/share/applications"
DESKTOP_SRC="$APP_DIR/gnettrack-heatmap.desktop"
DESKTOP_LINK="$HOME/Desktop/GNetTrack Heatmap.desktop"

# ── Colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✔${NC}  $*"; }
step() { echo -e "\n${BOLD}▸ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
die()  { echo -e "${RED}✘${NC}  $*" >&2; exit 1; }

echo -e "\n${BOLD}════════════════════════════════════${NC}"
echo -e "${BOLD}  G-NetTrack Heatmap — Kurulum       ${NC}"
echo -e "${BOLD}════════════════════════════════════${NC}"

# ── 1. İnternet bağlantısı ───────────────────────────────────────────────────
step "İnternet bağlantısı kontrol ediliyor..."
if ping -c 1 -W 3 pypi.org &>/dev/null 2>&1; then
    ok "Ağ bağlantısı mevcut."
else
    warn "pypi.org'a ulaşılamıyor — paketler zaten kuruluysa devam edilebilir."
fi

# ── 2. Python 3 ───────────────────────────────────────────────────────────────
step "Python 3 kontrol ediliyor..."
if command -v python3 &>/dev/null; then
    ok "Python3 mevcut: $(python3 --version)"
else
    warn "Python3 bulunamadı, kuruluyor..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -qq
        sudo apt-get install -y python3 python3-pip
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y python3 python3-pip
    elif command -v pacman &>/dev/null; then
        sudo pacman -Sy --noconfirm python python-pip
    else
        die "Desteklenmeyen paket yöneticisi. Python 3'ü https://python.org adresinden kurun."
    fi
    ok "Python3 kuruldu: $(python3 --version)"
fi

PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")

# ── 3. Sanal ortam ───────────────────────────────────────────────────────────
step "Sanal ortam hazırlanıyor..."

_make_venv() {
    rm -rf "$VENV_DIR"

    # Deneme 1: normal venv (en temiz yol)
    if python3 -m venv "$VENV_DIR" 2>/dev/null; then
        return 0
    fi

    # Deneme 2: python3-venv paketi eksik — sudo ile kur
    warn "python3-venv eksik, sudo ile kuruluyor..."
    if sudo apt-get install -y "python${PYVER}-venv" 2>/dev/null \
       || sudo apt-get install -y python3-venv 2>/dev/null; then
        python3 -m venv "$VENV_DIR" && return 0
    fi

    # Deneme 3: sudo yok — pip bootstrap'i atla, sistem paketlerini devral
    warn "sudo erişimi yok; pip bootstrap atlanıyor, sistem paketleri devralınıyor..."
    python3 -m venv --without-pip --system-site-packages "$VENV_DIR" && return 0

    return 1
}

if [ -d "$VENV_DIR" ] && "$VENV_DIR/bin/python" --version &>/dev/null 2>&1; then
    ok "Sanal ortam zaten mevcut (.venv/)"
else
    _make_venv || die "Sanal ortam oluşturulamadı."
    ok "Sanal ortam oluşturuldu (.venv/)"
fi

PY="$VENV_DIR/bin/python"

# ── 4. Python paketleri ───────────────────────────────────────────────────────
step "Python paketleri yükleniyor (folium, flask)..."

# pip venv içinde varsa onu kullan; yoksa sistem pip'i ile hedef dizine kur
if "$VENV_DIR/bin/pip" --version &>/dev/null 2>&1; then
    PIP="$VENV_DIR/bin/pip"
    "$PIP" install --quiet --upgrade pip
    "$PIP" install --quiet folium flask
elif python3 -m pip --version &>/dev/null 2>&1; then
    warn "Sanal ortamda pip yok, sistem pip kullanılıyor (--user)..."
    python3 -m pip install --quiet --user folium flask
else
    die "pip bulunamadı. 'sudo apt install python3-pip' deneyin."
fi

# Kurulumu doğrula
"$PY" -c "import folium, flask" \
    || die "Paket kurulumu doğrulanamadı. Lütfen hataları kontrol edin."

FOLIUM_VER=$("$PY" -c "import folium; print(folium.__version__)")
FLASK_VER=$( "$PY" -c "import importlib.metadata; print(importlib.metadata.version('flask'))")
ok "folium $FOLIUM_VER yüklendi."
ok "flask  $FLASK_VER yüklendi."

# ── 5. Masaüstü uygulaması kaydı ─────────────────────────────────────────────
step "Uygulama kaydediliyor..."
mkdir -p "$APP_DIR"

cat > "$DESKTOP_SRC" <<DESKTOP
[Desktop Entry]
Version=1.0
Name=G-NetTrack Heatmap
Comment=Drive-test KML dosyasindan interaktif kapsama haritasi olustur
Exec=$PY $SCRIPT_DIR/app.py
Icon=applications-internet
Terminal=false
Type=Application
Categories=Science;Network;
DESKTOP

update-desktop-database "$APP_DIR" 2>/dev/null || true
ok "Uygulama menüsüne eklendi ('G-NetTrack Heatmap' aratabilirsiniz)."

if [ -d "$HOME/Desktop" ]; then
    cp "$DESKTOP_SRC" "$DESKTOP_LINK"
    chmod +x "$DESKTOP_LINK"
    gio set "$DESKTOP_LINK" metadata::trusted true 2>/dev/null || true
    ok "Masaüstü kısayolu oluşturuldu (güvenilir olarak işaretlendi)."
else
    warn "~/Desktop bulunamadı, masaüstü kısayolu atlandı."
fi

# ── Özet ─────────────────────────────────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}Kurulum tamamlandı!${NC}"
echo -e "────────────────────────────────────"
echo -e "  Masaüstündeki 'G-NetTrack Heatmap' ikonuna çift tıklayın"
echo -e "  veya terminalde:\n"
echo -e "    ${BOLD}$PY $SCRIPT_DIR/app.py${NC}\n"
