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
FEED_SECTION = """
<style>
.feed-h{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 6px}
.chip{font:500 11px/1 'IBM Plex Mono',ui-monospace,monospace;padding:7px 10px;border:1px solid var(--rule);background:transparent;color:var(--ink);border-radius:999px;cursor:pointer}
.chip[aria-pressed=true]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.feed article{display:grid;grid-template-columns:92px 1fr;gap:14px;padding:11px 0;border-bottom:1px solid var(--rule)}
.feed time{font:400 11px/1.4 ui-monospace,Menlo,monospace;color:var(--muted)}
.feed a{color:var(--ink);text-decoration:none;font-size:16.5px;line-height:1.3}
.feed a:hover{text-decoration:underline;text-underline-offset:3px}
.feed .meta{font:400 11px/1.6 ui-monospace,Menlo,monospace;color:var(--muted);margin-top:3px}
.feed .tag{display:inline-block;padding:1px 6px;border:1px solid var(--rule);border-radius:3px;margin-right:4px}
.feed .empty{padding:22px 0;color:var(--muted);font-style:italic}
.more{margin-top:12px;font:500 11px ui-monospace,Menlo,monospace;letter-spacing:.08em;text-transform:uppercase}
.more a{color:var(--ink)}
@media(max-width:700px){.feed article{grid-template-columns:1fr;gap:4px}}
</style>
<h2>News feeding the model</h2>
<div class="feed-h"><p class="sub" id="feed-sub">Live from the collector, newest first.</p></div>
<div class="chips" id="chips"></div>
<div class="feed" id="feed"><div class="empty">Loading news…</div></div>
<p class="more"><a href="/">Full news desk →</a></p>
<script>
(() => {
  const URL = "https://zrqquefqdzdqnflirowm.supabase.co/rest/v1/aapl_feed?select=*&limit=500";
  const KEY = "sb_publishable_4993_ZaGw10laI3qei1STQ_AZl4XH-N";
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  const t = iso => { const d = new Date(iso), o = {timeZone:"America/New_York"};
    return new Intl.DateTimeFormat("en-US",{...o,month:"short",day:"numeric"}).format(d) + "<br>" +
      new Intl.DateTimeFormat("en-US",{...o,hour:"2-digit",minute:"2-digit",hour12:false}).format(d) + " ET"; };
  let rows = [], f = "all";
  const draw = () => {
    const opts = ["all","google_news","gdelt","apple_newsroom","sec_edgar"];
    document.getElementById("chips").innerHTML = opts.map(o =>
      `<button class="chip" aria-pressed="${o===f}" data-f="${o}">${o.replace("_"," ")}</button>`).join("");
    document.querySelectorAll("#chips .chip").forEach(b => b.onclick = () => { f = b.dataset.f; draw(); });
    const shown = rows.filter(r => f === "all" || r.source === f).slice(0, 60);
    document.getElementById("feed").innerHTML = shown.length ? shown.map(r => `<article><time>${t(r.available_at_utc)}</time><div>
      <a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>
      <div class="meta"><span class="tag">${esc(r.source)}</span>${esc(r.source_domain || "")}${r.availability_basis !== "observed" ? " · backfill" : ""}</div></div></article>`).join("")
      : `<div class="empty">No news for this source yet.</div>`;
  };
  fetch(URL, {headers:{apikey:KEY}}).then(r => r.ok ? r.json() : Promise.reject(r.status)).then(d => {
    rows = d;
    document.getElementById("feed-sub").textContent = `Live from the collector, newest first. ${d.length} stored items; showing the latest 60.`;
    draw();
  }).catch(e => { document.getElementById("feed").innerHTML = `<div class="empty">Could not load news (${esc(e)}).</div>`; });
})();
</script>
"""

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
    html = html.replace('<p class="sub" style="margin-top:40px">', FEED_SECTION + '<p class="sub" style="margin-top:40px">', 1)
    out = ROOT / "dashboard" / "report.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
