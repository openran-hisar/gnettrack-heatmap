# G-NetTrack Heatmap

G-NetTrack Pro uygulamasının ürettiği KML drive-test log dosyalarını **interaktif HTML kapsama haritasına** çeviren Python aracı.

![Python](https://img.shields.io/badge/Python-3.8+-blue) ![Flask](https://img.shields.io/badge/Flask-web%20UI-lightgrey) ![Folium](https://img.shields.io/badge/Folium-harita-green)

---

## Özellikler

- **Sürükle-bırak web arayüzü** — KML dosyasını yükle, haritayı anında görüntüle
- **Çoklu metrik desteği** — RSRP, RSRQ, SNR, DL/UL Bitrate, Hız, GPS Hassasiyeti
- **Katmanlı harita** — Her metrik için açılıp kapanabilen heatmap + nokta katmanı
- **Birleşik popup** — Noktaya tıklayınca tüm metrik değerleri + hücre bilgisi (Band, ARFCN, TAC, eNB, PCI, CGI)
- **İstatistik paneli** — Her metrik için ortalama, medyan, P10, P90, zayıf nokta oranı
- **4 taban harita** — OpenStreetMap, CartoDB Light/Dark, Esri Satellite
- **Masaüstü uygulaması gibi** — Çift tıkla başlat, tarayıcı otomatik açılır, bitince kapat butonuyla tamamen kapanır

---

## Kurulum

Projeyi indirin ve tek komutla kurun:

```bash
git clone https://github.com/openran-hisar/gnettrack-heatmap.git
cd gnettrack-heatmap
bash install.sh
```

`install.sh` şunları otomatik yapar:
- Python 3 ve gerekli sistem paketlerini kurar (apt / dnf / pacman)
- `.venv/` sanal ortamını oluşturur
- `folium` ve `flask` paketlerini yükler
- Masaüstü kısayolunu oluşturur ve güvenilir olarak işaretler
- Uygulama menüsüne kaydeder

**Desteklenen dağıtımlar:** Ubuntu / Debian · Fedora / RHEL · Arch Linux

---

## Kullanım

### Web Arayüzü (Önerilen)

Masaüstündeki **G-NetTrack Heatmap** ikonuna çift tıklayın  
veya terminalde:

```bash
.venv/bin/python app.py
```

Tarayıcı otomatik açılır → KML dosyasını yükleyin → **Harita Oluştur**

### Komut Satırı

```bash
# Tek KML dosyası
.venv/bin/python gnettrack_heatmap.py kayitlar/ornek.kml

# Klasördeki ilk KML
.venv/bin/python gnettrack_heatmap.py kayitlar/

# Belirli oturum prefix'i
.venv/bin/python gnettrack_heatmap.py kayitlar/ --prefix Open5GS_2026.05.21

# Özel metrik seçimi ve çıktı adı
.venv/bin/python gnettrack_heatmap.py ornek.kml --metrics rsrp,snr,dl_bitrate -o harita.html
```

---

## Desteklenen Metrikler

| Parametre | Açıklama | Birim | İyi / Orta / Zayıf |
|-----------|----------|-------|-------------------|
| `rsrp` | Reference Signal Received Power | dBm | ≥ -90 / -110 |
| `rsrq` | Reference Signal Received Quality | dB | ≥ -12 / -18 |
| `snr` | Signal-to-Noise Ratio | dB | ≥ 13 / 0 |
| `dl_bitrate` | İndirme Hızı | kbps | ≥ 50000 / 5000 |
| `ul_bitrate` | Yükleme Hızı | kbps | ≥ 20000 / 2000 |
| `speed` | Araç Hızı | km/h | — |
| `accuracy` | GPS Hassasiyeti | m | ≤ 5 / 20 |

---

## Gereksinimler

- Python 3.8+
- folium
- flask

```bash
pip install folium flask
```
