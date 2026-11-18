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
FX = {"host": "127.0.0.1", "port": 8787}     # where the FX dashboard listens (read-only relay)
ANCHOR_CSS, ANCHOR_BTN, ANCHOR_SEC = "</style>", "<button data-t='system'>System</button>", "<div class='tab' id='system'>"


def inject(fx_html: str, css: str, section: str) -> str | None:
    """Adds the Stocks tab to the FX dashboard's own page (CSS, tab button, section). Pure string insertion at three fixed anchors; returns None if the page
    is not what we expect (then the caller shows the stand-alone stocks page instead). If the FX page already has a Stocks tab it is returned unchanged."""
    if "id='stocks'" in fx_html:
        return fx_html
    if not all(a in fx_html for a in (ANCHOR_CSS, ANCHOR_BTN, ANCHOR_SEC)):
        return None
    h = fx_html.replace(ANCHOR_CSS, css + ANCHOR_CSS, 1)
    h = h.replace(ANCHOR_BTN, ANCHOR_BTN + "<button data-t='stocks'>Stocks</button>", 1)
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
    res, sp = rd("stocks.json"), rd("stocks_setups.json")
    fx = fx_page()
    h = inject(fx, tab.CSS, tab.fragment(res, sp)) if fx else None
    if h is None:                                           # FX dashboard unreachable or unexpected: show the stand-alone stocks page, say so
        h = dashboard.render(res, sp).replace("<div class=\"wrap\">", "<div class=\"wrap\"><div class=\"verdict\"><b>FX dashboard not reachable right now</b> <span class=\"muted\">(showing Stocks only; it will combine again by itself).</span></div>", 1)
    if AUTO[0]:
        h = h.replace("<head>", f"<head><meta http-equiv='refresh' content='{AUTO[0]}'>", 1)
    return h


class H(BaseHTTPRequestHandler):
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
