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
    pip install folium

USAGE
-----
    # Default metrics (CSI-RSRP, CSI-RSRQ, CSI-SNR, DL bitrate)
    python gnettrack_heatmap.py /path/to/logs

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
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import folium
    from folium.plugins import HeatMap, MiniMap, MeasureControl, Fullscreen
except ImportError:
    sys.exit("Missing dependency. Install with:  pip install folium")


# Each metric maps to:
#  - ext_key : the name attribute used in <Data name="..."> inside ExtendedData
#  - label, unit
#  - better  : 'higher' or 'lower' (controls normalization direction)
#  - range   : (min, max) used to clamp values into 0..1 for the heatmap
#  - good/bad: thresholds for green/amber/red point coloring
METRIC_CONFIG = {
    "rsrp":       {"ext_key": "RSRP",       "label": "RSRP",       "unit": "dBm",
                   "better": "higher", "range": (-120, -60), "good": -90,  "bad": -110},
    "rsrq":       {"ext_key": "RSRQ",       "label": "RSRQ",       "unit": "dB",
                   "better": "higher", "range": (-25, -5),   "good": -12,  "bad": -18},
    "snr":        {"ext_key": "SNR",        "label": "SNR",        "unit": "dB",
                   "better": "higher", "range": (-10, 30),   "good": 13,   "bad": 0},
    "dl_bitrate": {"ext_key": "DL_BITRATE", "label": "DL Bitrate", "unit": "kbps",
                   "better": "higher", "range": (0, 200000), "good": 50000,"bad": 5000},
    "ul_bitrate": {"ext_key": "UL_BITRATE", "label": "UL Bitrate", "unit": "kbps",
                   "better": "higher", "range": (0, 100000), "good": 20000,"bad": 2000},
    "speed":      {"ext_key": "SPEED",      "label": "Speed",      "unit": "km/h",
                   "better": "higher", "range": (0, 200),    "good": 50,   "bad": 10},
    "accuracy":   {"ext_key": "ACCURACY",   "label": "GPS Accuracy","unit": "m",
                   "better": "lower",  "range": (0, 50),     "good": 5,    "bad": 20},
}

DEFAULT_METRICS = ["rsrp", "rsrq", "snr", "dl_bitrate"]


# ---------- KML parsing (namespace-agnostic) ----------

def localname(tag: str) -> str:
    """Strip XML namespace from a tag name, e.g. '{ns}Placemark' -> 'Placemark'."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def iter_local(elem, name):
    """Iterate descendants whose local-name (ignoring namespace) matches `name`."""
    for child in elem.iter():
        if localname(child.tag) == name:
            yield child


def find_local(elem, name):
    """Find first descendant whose local-name matches `name`, or None."""
    return next(iter_local(elem, name), None)


def extract_number(text: str):
    """Pull the first signed decimal number out of a string. Returns float or None."""
    if not text:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(m.group()) if m else None


def parse_kml(path: Path, metrics: list[str]):
    """
    Parse one G-NetTrack KML file once and return a dict:
        { metric_name: [(lat, lon, value), ...], ... }
    All requested metrics are pulled from the same Placemarks in a single pass.
    """
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, FileNotFoundError) as e:
        print(f"  ! Could not parse {path.name}: {e}")
        return {m: [] for m in metrics}

    result = {m: [] for m in metrics}
    ext_keys = {m: METRIC_CONFIG[m]["ext_key"] for m in metrics}

    for pm in iter_local(root, "Placemark"):
        # Coordinates
        coords_el = find_local(pm, "coordinates")
        if coords_el is None or not coords_el.text:
            continue
        try:
            lon_s, lat_s, *_ = coords_el.text.strip().split(",")
            lat, lon = float(lat_s), float(lon_s)
        except (ValueError, IndexError):
            continue

        # Build a small dict of ExtendedData values for this placemark
        ext = {}
        for data_el in iter_local(pm, "Data"):
            key = data_el.get("name")
            if not key:
                continue
            val_el = find_local(data_el, "value")
            if val_el is not None and val_el.text:
                ext[key] = val_el.text

        # Pull each requested metric
        for metric, ext_key in ext_keys.items():
            raw = ext.get(ext_key)
            v = extract_number(raw) if raw else None
            if v is not None:
                result[metric].append((lat, lon, v))

    return result


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
    """Pick one KML to read. ExtendedData contains all metrics, so one is enough."""
    if target.is_file() and target.suffix.lower() == ".kml":
        return target
    if not target.is_dir():
        return None
    pattern = f"{prefix}*.kml" if prefix else "*.kml"
    matches = sorted(target.glob(pattern))
    return matches[0] if matches else None


# ---------- Map building ----------

def build_map(input_path: Path, prefix: str | None, metrics: list[str], output: Path):
    kml_file = find_input_file(input_path, prefix)
    if not kml_file:
        sys.exit(f"No KML file found in {input_path} (prefix={prefix!r}).")

    print(f"Reading: {kml_file.name}")
    datasets = parse_kml(kml_file, metrics)

    # Drop empty metrics, report counts
    datasets = {m: pts for m, pts in datasets.items() if pts}
    for m, pts in datasets.items():
        print(f"  - {METRIC_CONFIG[m]['label']}: {len(pts)} points")
    if not datasets:
        sys.exit("No usable data found. The file may be missing ExtendedData.")

    # Center on the centroid of the first metric's points
    first_pts = next(iter(datasets.values()))
    center = (
        sum(p[0] for p in first_pts) / len(first_pts),
        sum(p[1] for p in first_pts) / len(first_pts),
    )

    m = folium.Map(location=center, zoom_start=17, tiles=None, control_scale=True)
    folium.TileLayer("OpenStreetMap", name="Street").add_to(m)
    folium.TileLayer("CartoDB positron", name="Light").add_to(m)
    folium.TileLayer("CartoDB dark_matter", name="Dark").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satellite",
    ).add_to(m)

    gradient = {0.0: "#7f1d1d", 0.25: "#ef4444", 0.5: "#f59e0b",
                0.75: "#84cc16", 1.0: "#16a34a"}

    primary = True  # first metric is visible by default
    for metric, pts in datasets.items():
        cfg = METRIC_CONFIG[metric]
        label, unit = cfg["label"], cfg["unit"]

        heat_layer = folium.FeatureGroup(name=f"🔥 {label} heatmap", show=primary)
        HeatMap(
            [[lat, lon, normalize(v, cfg)] for lat, lon, v in pts],
            radius=18, blur=22, min_opacity=0.35, max_zoom=18, gradient=gradient,
        ).add_to(heat_layer)
        heat_layer.add_to(m)

        pts_layer = folium.FeatureGroup(name=f"• {label} points", show=False)
        for lat, lon, v in pts:
            c = color_for(v, cfg)
            folium.CircleMarker(
                location=(lat, lon), radius=3, color=c, weight=0,
                fill=True, fillColor=c, fillOpacity=0.9,
                popup=f"<b>{label}</b>: {v:.2f} {unit}".strip(),
            ).add_to(pts_layer)
        pts_layer.add_to(m)
        primary = False

    folium.LayerControl(collapsed=False).add_to(m)
    Fullscreen().add_to(m)
    MeasureControl(primary_length_unit="meters").add_to(m)
    MiniMap(toggle_display=True).add_to(m)

    legend = """
    <div style="position: fixed; bottom: 30px; left: 12px; z-index: 9999;
                background: white; padding: 10px 14px; border: 1px solid #ccc;
                border-radius: 6px; font: 12px/1.4 system-ui, sans-serif;
                box-shadow: 0 2px 6px rgba(0,0,0,0.15);">
      <div style="font-weight: 600; margin-bottom: 6px;">Quality</div>
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">
        <span style="width:14px;height:14px;background:#16a34a;display:inline-block;border-radius:2px;"></span> Good</div>
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">
        <span style="width:14px;height:14px;background:#f59e0b;display:inline-block;border-radius:2px;"></span> Fair</div>
      <div style="display:flex;align-items:center;gap:6px;">
        <span style="width:14px;height:14px;background:#ef4444;display:inline-block;border-radius:2px;"></span> Poor</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend))

    m.save(str(output))
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
