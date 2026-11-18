"""Private stocks dashboard server: bind to 127.0.0.1 or the VM's Tailscale IP only (never 0.0.0.0). Re-renders from the results files on every request
and reloads itself every --auto seconds. Read-only: no endpoints that change anything.
  PYTHONPATH=src python -m fxengine.stocks.serve --host $(tailscale ip -4) --port 8790"""
from __future__ import annotations
import argparse, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from . import dashboard

RES = Path("docs/results")
AUTO = [60]


def page() -> str:
    def rd(n):
        p = RES / n
        return json.loads(p.read_text()) if p.exists() else None
    h = dashboard.render(rd("stocks.json"), rd("stocks_setups.json"))
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
    a = ap.parse_args()
    if a.host in ("0.0.0.0", "::"):
        raise SystemExit("Refusing to bind to all interfaces: use 127.0.0.1 or the VM's Tailscale IP.")
    AUTO[0] = a.auto
    print(f"stocks dashboard on http://{a.host}:{a.port}", flush=True)
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()


if __name__ == "__main__":
    main()
