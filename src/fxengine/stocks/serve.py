"""Private stocks dashboard server: bind to 127.0.0.1 or the VM's Tailscale IP only (never 0.0.0.0). Re-renders from the results files on every request
and reloads itself every --auto seconds. Read-only: no endpoints that change anything.
  PYTHONPATH=src python -m fxengine.stocks.serve --host $(tailscale ip -4) --port 8790"""
from __future__ import annotations
import argparse, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from . import dashboard, tab

RES = Path("docs/results")
AUTO = [60]
FX_ROOT = [Path.home() / "fx"]               # where the FX engine lives (its ledger is only ever READ)
FX = {"host": "127.0.0.1", "port": 8787}     # where the FX dashboard listens (read-only relay)
ANCHOR_CSS, ANCHOR_BTN, ANCHOR_SEC = "</style>", "<button data-t='system'>System</button>", "<div class='tab' id='system'>"


def inject(fx_html: str, css: str, section: str, combined: str | None = None) -> str | None:
    """Adds the Stocks tab to the FX dashboard's own page (CSS, tab button, section). Pure string insertion at three fixed anchors; returns None if the page
    is not what we expect (then the caller shows the stand-alone stocks page instead). If the FX page already has a Stocks tab it is returned unchanged."""
    if "id='stocks'" in fx_html:
        return fx_html
    if not all(a in fx_html for a in (ANCHOR_CSS, ANCHOR_BTN, ANCHOR_SEC)):
        return None
    h = fx_html.replace(ANCHOR_CSS, css + ANCHOR_CSS, 1)
    h = h.replace(ANCHOR_BTN, ANCHOR_BTN + "<button data-t='stocks'>Stocks</button>", 1)
    if combined and "<div class='tabs'>" in h:                      # the Combined tab goes FIRST in the bar (FX's own default tab is unchanged)
        h = h.replace("<div class='tabs'>", "<div class='tabs'><button data-t='combined'>Combined</button>", 1)
        section = combined + section
    return h.replace(ANCHOR_SEC, section + ANCHOR_SEC, 1)


def fx_page() -> str | None:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{FX['host']}:{FX['port']}/", timeout=20) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        return None


def page() -> str:
    def rd(n):
        p = RES / n
        return json.loads(p.read_text()) if p.exists() else None
    res, sp, mk = rd("stocks.json"), rd("stocks_setups.json"), rd("stocks_market.json")
    jr = tab.load_journal()
    fx = fx_page()
    try:                                                         # live: the FX ledger is read (read-only) on every page load
        from . import shared
        sh = shared.combine(shared.fx_snapshot(FX_ROOT[0]), shared.stocks_snapshot(sp))
    except Exception:
        sh = None
    h = inject(fx, tab.CSS, tab.fragment(res, sp, mk, jr), tab.combined_fragment(sh)) if fx else None
    if h is None:                                           # FX dashboard unreachable or unexpected: show the stand-alone stocks page, say so
        h = dashboard.render(res, sp, mk, jr).replace("<div class=\"wrap\">", "<div class=\"wrap\"><div class=\"verdict\"><b>FX dashboard not reachable right now</b> <span class=\"muted\">(showing Stocks only; it will combine again by itself).</span></div>", 1)
    if AUTO[0]:
        h = h.replace("<head>", f"<head><meta http-equiv='refresh' content='{AUTO[0]}'>", 1)
    return h


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        """Journal save only. JSON content type required (a plain cross-site form cannot send it); one tiny fixed route; nothing else writes."""
        import json as _j
        from . import journal
        def send(code, obj):
            b = _j.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        if self.path != "/api/journal" or "application/json" not in (self.headers.get("Content-Type") or ""):
            return send(415 if self.path == "/api/journal" else 404, dict(ok=False, error="not allowed"))
        try:
            row = _j.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 5000)) or b"{}")
            return send(200, dict(ok=True, trade=journal.add(row)))
        except ValueError as e:
            return send(400, dict(ok=False, error=str(e)))

    def do_GET(self):
        if self.path.split("?")[0] not in ("/", "/index.html"):
            self.send_response(404); self.end_headers(); return
        b = page().encode()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--auto", type=int, default=60)
    ap.add_argument("--fx-host", default=None, help="where the FX dashboard listens (default: same as --host)")
    ap.add_argument("--fx-port", type=int, default=8787)
    a = ap.parse_args()
    if a.host in ("0.0.0.0", "::"):
        raise SystemExit("Refusing to bind to all interfaces: use 127.0.0.1 or the VM's Tailscale IP.")
    AUTO[0], FX["host"], FX["port"] = a.auto, a.fx_host or a.host, a.fx_port
    print(f"FX + Stocks on one page: http://{a.host}:{a.port}  (FX dashboard read from {FX['host']}:{FX['port']})", flush=True)
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()


if __name__ == "__main__":
    main()
