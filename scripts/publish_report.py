"""Copy the latest model run report into the dashboard as a second tab.

    python3 scripts/publish_report.py            # reads ../Grid_Feature_Engineering/outputs/report.html
    python3 scripts/publish_report.py --src path/to/report.html

Writes dashboard/report.html with the same top menu as dashboard/index.html.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAV_CSS = (
    '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500&display=swap" rel="stylesheet">'
    "<style>.nav{display:flex;gap:22px;margin:0 0 20px;font:500 11px/1 'IBM Plex Mono',ui-monospace,monospace;"
    "letter-spacing:.12em;text-transform:uppercase}.nav a{color:var(--muted);text-decoration:none;"
    "padding-bottom:7px;border-bottom:2px solid transparent}.nav a:hover{color:var(--ink)}"
    ".nav a[aria-current=page]{color:var(--ink);border-color:var(--ink)}</style>"
)
NAV = ('<nav class="nav"><a href="/">News</a>'
       '<a href="/report.html" aria-current="page">Model results</a></nav>')

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT.parent / "Grid_Feature_Engineering" / "outputs" / "report.html"))
    a = ap.parse_args()
    html = Path(a.src).read_text(encoding="utf-8")
    html = html.replace("<title>Grid run report</title>", "<title>Model results · AAPL News Desk</title>")
    html = html.replace("</head>", NAV_CSS + "</head>", 1)
    html = html.replace('<div class="wrap">', '<div class="wrap">' + NAV, 1)
    out = ROOT / "dashboard" / "report.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
