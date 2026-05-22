#!/usr/bin/env python3
"""
G-NetTrack Pro KML -> Interactive Coverage Heatmap
===================================================

Generates a single interactive HTML map (Folium / Leaflet) from G-NetTrack Pro
drive-test KML logs. Each chosen metric becomes a toggleable heatmap layer +
a points layer, all in one map with switchable basemaps.

Because G-NetTrack stores every metric in <ExtendedData> on every Placemark,
ANY of the per-metric KML files (or even just one of them) is enough to
produce heatmaps for ALL metrics. By default the script picks the first KML
matching the session prefix.

INSTALL
-------
    pip install folium flask

USAGE
-----
    # CLI: default metrics (RSRP, RSRQ, SNR, DL bitrate)
    python gnettrack_heatmap.py /path/to/logs

    # Web UI (drag-and-drop)
    python app.py

    # Specific log session prefix (folder has multiple sessions)
    python gnettrack_heatmap.py /path/to/logs --prefix Open5GS_2026.05.21_16.26.40

    # Pass a single .kml file directly
    python gnettrack_heatmap.py /path/to/Open5GS_..._csirsrp.kml

    # Custom metric set + output filename
    python gnettrack_heatmap.py /path/to/logs --metrics rsrp,snr,dl_bitrate -o map.html

Supported metrics (use these names with --metrics):
    rsrp, rsrq, snr, dl_bitrate, ul_bitrate, speed, accuracy
"""

import argparse
import re
import statistics
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import folium
    from folium.plugins import HeatMap, MiniMap, MeasureControl, Fullscreen
except ImportError:
    sys.exit("Missing dependency. Install with:  pip install folium")


METRIC_CONFIG = {
    "rsrp":       {"ext_key": "RSRP",       "label": "RSRP",        "unit": "dBm",
                   "better": "higher", "range": (-120, -60), "good": -90,   "bad": -110},
    "rsrq":       {"ext_key": "RSRQ",       "label": "RSRQ",        "unit": "dB",
                   "better": "higher", "range": (-25, -5),   "good": -12,   "bad": -18},
    "snr":        {"ext_key": "SNR",        "label": "SNR",         "unit": "dB",
                   "better": "higher", "range": (-10, 30),   "good": 13,    "bad": 0},
    "dl_bitrate": {"ext_key": "DL_BITRATE", "label": "DL Bitrate",  "unit": "kbps",
                   "better": "higher", "range": (0, 200000), "good": 50000, "bad": 5000},
    "ul_bitrate": {"ext_key": "UL_BITRATE", "label": "UL Bitrate",  "unit": "kbps",
                   "better": "higher", "range": (0, 100000), "good": 20000, "bad": 2000},
    "speed":      {"ext_key": "SPEED",      "label": "Speed",       "unit": "km/h",
                   "better": "higher", "range": (0, 200),    "good": 50,    "bad": 10},
    "accuracy":   {"ext_key": "ACCURACY",   "label": "GPS Accuracy","unit": "m",
                   "better": "lower",  "range": (0, 50),     "good": 5,     "bad": 20},
}

DEFAULT_METRICS = ["rsrp", "rsrq", "snr", "dl_bitrate"]

# Cell identity fields extracted from each Placemark's ExtendedData
_CELL_FIELDS = ["TECHNOLOGY", "MODE", "BAND", "ARFCN", "TAC", "RNC", "PC", "CGI", "TIME"]


# ---------- KML parsing (namespace-agnostic) ----------

def localname(tag: str) -> str:
    """Strip XML namespace, e.g. '{ns}Placemark' -> 'Placemark'."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def iter_local(elem, name):
    for child in elem.iter():
        if localname(child.tag) == name:
            yield child


def find_local(elem, name):
    return next(iter_local(elem, name), None)


def extract_number(text: str):
    """Pull the first signed decimal number from a string."""
    if not text:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(m.group()) if m else None


def parse_kml(path: Path, metrics: list[str]):
    """
    Parse one G-NetTrack KML file and return:
      datasets : {metric: [(lat, lon, value), ...]}
      points   : [(lat, lon, {metric: value, ...}, {cell_field: raw_text, ...})]

    All requested metrics and cell info are pulled in a single pass.
    """
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, FileNotFoundError) as e:
        print(f"  ! Could not parse {path.name}: {e}")
        return {m: [] for m in metrics}, []

    datasets = {m: [] for m in metrics}
    ext_keys = {m: METRIC_CONFIG[m]["ext_key"] for m in metrics}
    points = []

    for pm in iter_local(root, "Placemark"):
        coords_el = find_local(pm, "coordinates")
        if coords_el is None or not coords_el.text:
            continue
        try:
            lon_s, lat_s, *_ = coords_el.text.strip().split(",")
            lat, lon = float(lat_s), float(lon_s)
        except (ValueError, IndexError):
            continue

        ext: dict[str, str] = {}
        for data_el in iter_local(pm, "Data"):
            key = data_el.get("name")
            if not key:
                continue
            val_el = find_local(data_el, "value")
            if val_el is not None and val_el.text:
                ext[key] = val_el.text

        cell_info = {f: ext.get(f, "") for f in _CELL_FIELDS}

        metric_vals: dict[str, float] = {}
        for metric, ext_key in ext_keys.items():
            raw = ext.get(ext_key)
            v = extract_number(raw) if raw else None
            if v is not None:
                datasets[metric].append((lat, lon, v))
                metric_vals[metric] = v

        points.append((lat, lon, metric_vals, cell_info))

    return datasets, points


# ---------- Heatmap math ----------

def normalize(value, cfg):
    lo, hi = cfg["range"]
    v = max(lo, min(hi, value))
    norm = (v - lo) / (hi - lo) if hi != lo else 0.5
    return 1.0 - norm if cfg["better"] == "lower" else norm


def color_for(value, cfg):
    if cfg["better"] == "higher":
        if value >= cfg["good"]: return "#16a34a"
        if value >= cfg["bad"]:  return "#f59e0b"
        return "#ef4444"
    else:
        if value <= cfg["good"]: return "#16a34a"
        if value <= cfg["bad"]:  return "#f59e0b"
        return "#ef4444"


# ---------- File discovery ----------

def find_input_file(target: Path, prefix: str | None) -> Path | None:
    if target.is_file() and target.suffix.lower() == ".kml":
        return target
    if not target.is_dir():
        return None
    pattern = f"{prefix}*.kml" if prefix else "*.kml"
    matches = sorted(target.glob(pattern))
    return matches[0] if matches else None


# ---------- HTML helpers ----------

def _popup_html(metric_vals: dict, cell_info: dict, active_metrics: list[str]) -> str:
    tech = cell_info.get("TECHNOLOGY", "")
    mode = cell_info.get("MODE", "")
    band = cell_info.get("BAND", "")
    arfcn = cell_info.get("ARFCN", "")
    tac = cell_info.get("TAC", "")
    rnc = cell_info.get("RNC", "")
    pci = cell_info.get("PC", "")
    cgi = cell_info.get("CGI", "")
    time_val = cell_info.get("TIME", "").replace("_", " ")

    metric_rows = ""
    for m in active_metrics:
        if m not in metric_vals:
            continue
        cfg = METRIC_CONFIG[m]
        v = metric_vals[m]
        c = color_for(v, cfg)
        metric_rows += (
            f'<tr>'
            f'<td style="padding:2px 6px 2px 0;color:#555">{cfg["label"]}</td>'
            f'<td style="padding:2px 0;font-weight:600;color:{c}">'
            f'{v:.1f}&nbsp;{cfg["unit"]}</td>'
            f'</tr>'
        )

    header = " ".join(filter(None, [tech, mode]))
    band_arfcn = "&nbsp;&bull;&nbsp;".join(filter(None, [
        band, f"ARFCN&nbsp;{arfcn}" if arfcn else ""
    ]))
    cell_ids = "&nbsp;&bull;&nbsp;".join(filter(None, [
        f"TAC&nbsp;{tac}" if tac else "",
        f"eNB&nbsp;{rnc}" if rnc else "",
        f"PCI&nbsp;{pci}" if pci else "",
    ]))

    return (
        '<div style="font:12px/1.5 system-ui,sans-serif;min-width:210px">'
        f'<div style="font-weight:700;font-size:13px;margin-bottom:2px">{header}</div>'
        f'<div style="color:#888;font-size:11px;margin-bottom:6px">{band_arfcn}</div>'
        f'<table style="border-collapse:collapse;width:100%">{metric_rows}</table>'
        '<hr style="margin:6px 0;border:none;border-top:1px solid #eee">'
        f'<div style="color:#777;font-size:11px">{cell_ids}</div>'
        f'<div style="color:#aaa;font-size:10px;margin-top:2px">CGI: {cgi}</div>'
        f'<div style="color:#aaa;font-size:10px">{time_val}</div>'
        '</div>'
    )


def _stats_panel_html(datasets: dict, active_metrics: list[str]) -> str:
    blocks = ""
    for m in active_metrics:
        if m not in datasets or not datasets[m]:
            continue
        cfg = METRIC_CONFIG[m]
        vals = sorted(v for _, _, v in datasets[m])
        n = len(vals)
        mean = statistics.mean(vals)
        median = statistics.median(vals)
        p10 = vals[max(0, int(n * 0.10))]
        p90 = vals[min(n - 1, int(n * 0.90))]
        bad_thresh = cfg["bad"]
        if cfg["better"] == "higher":
            bad_count = sum(1 for v in vals if v < bad_thresh)
        else:
            bad_count = sum(1 for v in vals if v > bad_thresh)
        bad_pct = 100 * bad_count / n if n else 0
        u = cfg["unit"]

        blocks += (
            f'<div style="margin-bottom:10px;padding-bottom:10px;'
            f'border-bottom:1px solid #f0f0f0">'
            f'<div style="font-weight:600;margin-bottom:4px">{cfg["label"]}</div>'
            f'<table style="border-collapse:collapse;width:100%;font-size:11px;color:#444">'
            f'<tr>'
            f'<td style="padding:1px 4px 1px 0;color:#888">Mean</td>'
            f'<td style="padding:1px 8px 1px 0">{mean:.1f} {u}</td>'
            f'<td style="padding:1px 4px;color:#888">Median</td>'
            f'<td>{median:.1f} {u}</td>'
            f'</tr><tr>'
            f'<td style="padding:1px 4px 1px 0;color:#888">P10</td>'
            f'<td style="padding:1px 8px 1px 0">{p10:.1f} {u}</td>'
            f'<td style="padding:1px 4px;color:#888">P90</td>'
            f'<td>{p90:.1f} {u}</td>'
            f'</tr><tr>'
            f'<td style="padding:2px 0 0;color:#888">Poor</td>'
            f'<td colspan="3" style="padding:2px 0 0;color:#ef4444">'
            f'{bad_count}/{n} ({bad_pct:.0f}%)</td>'
            f'</tr>'
            f'</table></div>'
        )

    return (
        '<div id="sp" style="position:fixed;top:130px;left:10px;z-index:9999;'
        'background:white;padding:12px 14px;border:1px solid #ccc;'
        'border-radius:6px;font:12px/1.4 system-ui,sans-serif;'
        'box-shadow:0 2px 6px rgba(0,0,0,.15);width:244px">'
        '<div style="display:flex;justify-content:space-between;'
        'align-items:center;margin-bottom:8px">'
        '<span style="font-weight:700;font-size:13px">Statistics</span>'
        '<button id="sp-btn" onclick="'
        "var b=document.getElementById('sp-body');"
        "b.style.display=b.style.display==='none'?'block':'none';"
        "document.getElementById('sp-btn').textContent="
        "b.style.display==='none'?'+':'-';"
        '" style="border:none;background:none;cursor:pointer;'
        'font-size:14px;padding:2px 4px">-</button>'
        '</div>'
        f'<div id="sp-body">{blocks}</div>'
        '</div>'
    )


# ---------- Map building ----------

def build_map(input_path: Path, prefix: str | None, metrics: list[str], output: Path):
    kml_file = find_input_file(input_path, prefix)
    if not kml_file:
        sys.exit(f"No KML file found in {input_path} (prefix={prefix!r}).")

    print(f"Reading: {kml_file.name}")
    datasets, all_points = parse_kml(kml_file, metrics)

    datasets = {m: pts for m, pts in datasets.items() if pts}
    for m, pts in datasets.items():
        print(f"  - {METRIC_CONFIG[m]['label']}: {len(pts)} points")
    if not datasets:
        sys.exit("No usable data found. The file may be missing ExtendedData.")

    active_metrics = list(datasets.keys())

    # Index by coordinate for O(1) popup lookup
    point_lookup: dict[tuple[float, float], tuple[dict, dict]] = {}
    for lat, lon, mv, ci in all_points:
        point_lookup[(lat, lon)] = (mv, ci)

    first_pts = next(iter(datasets.values()))
    center = (
        sum(p[0] for p in first_pts) / len(first_pts),
        sum(p[1] for p in first_pts) / len(first_pts),
    )

    fmap = folium.Map(location=center, zoom_start=17, tiles=None, control_scale=True)
    folium.TileLayer("OpenStreetMap", name="Street").add_to(fmap)
    folium.TileLayer("CartoDB positron", name="Light").add_to(fmap)
    folium.TileLayer("CartoDB dark_matter", name="Dark").add_to(fmap)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satellite",
    ).add_to(fmap)

    gradient = {0.0: "#7f1d1d", 0.25: "#ef4444", 0.5: "#f59e0b",
                0.75: "#84cc16", 1.0: "#16a34a"}

    primary = True
    for metric, pts in datasets.items():
        cfg = METRIC_CONFIG[metric]
        label = cfg["label"]

        heat_layer = folium.FeatureGroup(name=f"{label} heatmap", show=primary)
        HeatMap(
            [[lat, lon, normalize(v, cfg)] for lat, lon, v in pts],
            radius=18, blur=22, min_opacity=0.35, max_zoom=18, gradient=gradient,
        ).add_to(heat_layer)
        heat_layer.add_to(fmap)

        pts_layer = folium.FeatureGroup(name=f"• {label} points", show=False)
        for lat, lon, v in pts:
            c = color_for(v, cfg)
            mv, ci = point_lookup.get((lat, lon), ({metric: v}, {}))
            popup = folium.Popup(_popup_html(mv, ci, active_metrics), max_width=280)
            folium.CircleMarker(
                location=(lat, lon), radius=3, color=c, weight=0,
                fill=True, fillColor=c, fillOpacity=0.9,
                popup=popup,
            ).add_to(pts_layer)
        pts_layer.add_to(fmap)
        primary = False

    folium.LayerControl(collapsed=False).add_to(fmap)
    Fullscreen().add_to(fmap)
    MeasureControl(primary_length_unit="meters").add_to(fmap)
    MiniMap(toggle_display=True).add_to(fmap)

    fmap.get_root().html.add_child(folium.Element(_stats_panel_html(datasets, active_metrics)))

    fmap.get_root().html.add_child(folium.Element("""
    <div style="position:fixed;bottom:30px;left:12px;z-index:9999;
                background:white;padding:10px 14px;border:1px solid #ccc;
                border-radius:6px;font:12px/1.4 system-ui,sans-serif;
                box-shadow:0 2px 6px rgba(0,0,0,0.15);">
      <div style="font-weight:600;margin-bottom:6px;">Quality</div>
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">
        <span style="width:14px;height:14px;background:#16a34a;display:inline-block;border-radius:2px;"></span> Good</div>
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">
        <span style="width:14px;height:14px;background:#f59e0b;display:inline-block;border-radius:2px;"></span> Fair</div>
      <div style="display:flex;align-items:center;gap:6px;">
        <span style="width:14px;height:14px;background:#ef4444;display:inline-block;border-radius:2px;"></span> Poor</div>
    </div>
    """))

    fmap.save(str(output))
    print(f"\nSaved: {output.resolve()}")
    print("Open it in any browser.")


def main():
    p = argparse.ArgumentParser(
        description="G-NetTrack Pro KML -> interactive coverage heatmap",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input", type=Path,
                   help="Folder containing KML files, OR a single .kml file")
    p.add_argument("--prefix", default=None,
                   help="Filename prefix to pick a specific session "
                        "(e.g. Open5GS_2026.05.21_16.26.40). "
                        "Only used when 'input' is a folder.")
    p.add_argument("--metrics", default=",".join(DEFAULT_METRICS),
                   help=f"Comma-separated metrics. Default: {','.join(DEFAULT_METRICS)}. "
                        f"Available: {','.join(METRIC_CONFIG)}")
    p.add_argument("-o", "--output", type=Path, default=Path("coverage_heatmap.html"),
                   help="Output HTML file (default: coverage_heatmap.html)")
    args = p.parse_args()

    if not args.input.exists():
        sys.exit(f"Path does not exist: {args.input}")

    metrics = [x.strip().lower() for x in args.metrics.split(",") if x.strip()]
    unknown = [x for x in metrics if x not in METRIC_CONFIG]
    if unknown:
        print(f"Unknown metrics ignored: {unknown}")
    metrics = [x for x in metrics if x in METRIC_CONFIG]
    if not metrics:
        sys.exit("No valid metrics selected.")

    print(f"Metrics: {metrics}\n")
    build_map(args.input, args.prefix, metrics, args.output)


if __name__ == "__main__":
    main()
