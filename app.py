#!/usr/bin/env python3
"""
Flask web UI for gnettrack_heatmap
===================================
Drag-and-drop a G-NetTrack Pro KML file, choose metrics, get an interactive
coverage map rendered directly in the browser.

INSTALL
-------
    pip install flask folium

RUN
---
    python app.py
    # then open http://localhost:5000
"""

import io
import tempfile
import threading
import webbrowser
from pathlib import Path

from flask import Flask, request, render_template_string

from gnettrack_heatmap import build_map, METRIC_CONFIG, DEFAULT_METRICS

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB

_INDEX = """<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>G-NetTrack Coverage Map</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font: 15px/1.55 system-ui, -apple-system, sans-serif;
      background: #f0f2f5;
      min-height: 100vh;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      padding: 48px 16px;
    }
    .card {
      background: #fff;
      border-radius: 12px;
      box-shadow: 0 4px 20px rgba(0,0,0,.10);
      padding: 36px 40px;
      width: 100%;
      max-width: 540px;
    }
    h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
    .sub { color: #6b7280; font-size: 13px; margin-bottom: 28px; }

    /* Drop zone */
    .drop {
      border: 2px dashed #d1d5db;
      border-radius: 10px;
      padding: 36px 24px;
      text-align: center;
      cursor: pointer;
      transition: border-color .2s, background .2s;
      margin-bottom: 24px;
      user-select: none;
    }
    .drop:hover, .drop.over {
      border-color: #6366f1;
      background: #f5f3ff;
    }
    .drop input[type=file] { display: none; }
    .drop-icon { font-size: 32px; margin-bottom: 8px; }
    .drop-text { color: #6b7280; font-size: 14px; }
    .drop-filename {
      margin-top: 10px;
      font-weight: 600;
      color: #4f46e5;
      font-size: 14px;
      word-break: break-all;
    }

    /* Metrics */
    .section-label {
      font-weight: 600;
      font-size: 13px;
      color: #374151;
      margin-bottom: 10px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .metrics {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-bottom: 28px;
    }
    .metrics label {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      cursor: pointer;
      padding: 8px 12px;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      transition: border-color .15s, background .15s;
    }
    .metrics label:hover { border-color: #a5b4fc; background: #fafafe; }
    .metrics input[type=checkbox]:checked + span { color: #4f46e5; font-weight: 600; }
    .metrics label:has(input:checked) { border-color: #6366f1; background: #f5f3ff; }
    .unit { color: #9ca3af; font-size: 11px; margin-left: 2px; }

    /* Button */
    .btn {
      width: 100%;
      padding: 13px;
      background: #4f46e5;
      color: #fff;
      border: none;
      border-radius: 8px;
      font-size: 15px;
      font-weight: 600;
      cursor: pointer;
      transition: background .2s;
      letter-spacing: .01em;
    }
    .btn:hover { background: #4338ca; }
    .btn:disabled { background: #a5b4fc; cursor: not-allowed; }

    /* Error */
    .error {
      margin-top: 14px;
      padding: 10px 14px;
      background: #fef2f2;
      border: 1px solid #fecaca;
      border-radius: 8px;
      color: #dc2626;
      font-size: 13px;
    }
  </style>
</head>
<body>
<div class="card">
  <h1>G-NetTrack Coverage Map</h1>
  <p class="sub">KML drive-test dosyanizi yukleyin, interaktif kapsama haritasi olusturulur.</p>

  <form method="POST" action="/generate" enctype="multipart/form-data" id="frm">
    <div class="drop" id="drop" onclick="document.getElementById('kmlfile').click()">
      <div class="drop-icon">&#128229;</div>
      <div class="drop-text">KML dosyasini buraya suruklleyin ya da tiklayin</div>
      <div class="drop-filename" id="fname"></div>
      <input type="file" name="kml" id="kmlfile" accept=".kml" required>
    </div>

    <div class="section-label">Metrikler</div>
    <div class="metrics">
      {% for key, cfg in metrics.items() %}
      <label>
        <input type="checkbox" name="metrics" value="{{ key }}"
          {% if key in defaults %}checked{% endif %}>
        <span>{{ cfg.label }}<span class="unit">{{ cfg.unit }}</span></span>
      </label>
      {% endfor %}
    </div>

    {% if error %}<div class="error">{{ error }}</div>{% endif %}

    <button type="submit" class="btn" id="btn">Harita Olustur</button>
  </form>
</div>

<script>
  const drop   = document.getElementById('drop');
  const input  = document.getElementById('kmlfile');
  const fname  = document.getElementById('fname');
  const btn    = document.getElementById('btn');

  input.addEventListener('change', () => {
    fname.textContent = input.files[0]?.name ?? '';
  });

  ['dragover', 'dragenter'].forEach(ev =>
    drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); })
  );
  ['dragleave', 'drop'].forEach(ev =>
    drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); })
  );
  drop.addEventListener('drop', e => {
    const f = e.dataTransfer.files[0];
    if (!f) return;
    const dt = new DataTransfer();
    dt.items.add(f);
    input.files = dt.files;
    fname.textContent = f.name;
  });

  document.getElementById('frm').addEventListener('submit', () => {
    btn.disabled = true;
    btn.textContent = 'Olusturuluyor…';
  });
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(_INDEX, metrics=METRIC_CONFIG, defaults=DEFAULT_METRICS)


@app.route("/generate", methods=["POST"])
def generate():
    kml_file = request.files.get("kml")
    if not kml_file or not kml_file.filename:
        return render_template_string(
            _INDEX, metrics=METRIC_CONFIG, defaults=DEFAULT_METRICS,
            error="KML dosyasi secilmedi.",
        )

    selected = request.form.getlist("metrics")
    if not selected:
        selected = list(DEFAULT_METRICS)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        kml_path = tmp / "input.kml"
        out_path = tmp / "map.html"
        kml_file.save(str(kml_path))

        try:
            build_map(kml_path, None, selected, out_path)
        except SystemExit as exc:
            return render_template_string(
                _INDEX, metrics=METRIC_CONFIG, defaults=DEFAULT_METRICS,
                error=str(exc),
            )

        html_content = out_path.read_text(encoding="utf-8")

    return html_content, 200, {"Content-Type": "text/html; charset=utf-8"}


if __name__ == "__main__":
    threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(debug=False, port=5000)
