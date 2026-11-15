"""Private live dashboard: a tiny web server on YOUR machine. Every page refresh rebuilds the dashboard from the latest data.
Only reachable from this computer (127.0.0.1) unless you choose otherwise. No cloud, no public URL, nothing uploaded.
PYTHONPATH=src python -m fxengine.dashboard.serve [--port 8787] [--open] [--auto 60] [--refresh]
  --auto N     the page reloads itself every N seconds
  --refresh    on each page load, first fetch the newest prices from OANDA (rate-limited to once a minute)
  --cache N    serve the same page for N seconds (the VM uses 30: a rebuild loads every pair on a 1-vCPU machine)"""
from __future__ import annotations
import argparse, threading, time, traceback, webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ..envfile import load_env
from .build import build

STATE = {"last_refresh": 0.0, "auto": 0, "refresh": False, "lock": threading.Lock(), "html": None, "built": 0.0, "cache": 0}


def render() -> str:
    note = ""
    if STATE["refresh"]:
        with STATE["lock"]:
            if time.time() - STATE["last_refresh"] > 60:
                try:
                    from ..live import loop
                    loop.refresh(load_env().get("OANDA_TOKEN"))
                    STATE["last_refresh"] = time.time()
                except Exception as e:                     # show it, don't hide it
                    note = f"<div class='sample' style='background:#d03b3b;color:#fff'>Could not fetch newest prices: {escape(str(e))[:160]}</div>"
    with STATE["lock"]:
        if STATE["html"] is None or time.time() - STATE["built"] > STATE["cache"] or note:
            STATE["html"], STATE["built"] = build(out=None, banner=note), time.time()
        html = STATE["html"]
    if STATE["auto"]:
        html = html.replace("<head>", f"<head><meta http-equiv='refresh' content='{STATE['auto']}'>", 1)
    return html


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] not in ("/", "/index.html"):
            self.send_response(404); self.end_headers(); return
        try:
            body, code = render().encode(), 200
        except Exception:
            body, code = f"<pre style='color:#f88;background:#111;padding:16px'>Dashboard error:\n{escape(traceback.format_exc())}</pre>".encode(), 500
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def make_server(host="127.0.0.1", port=8787):
    return ThreadingHTTPServer((host, port), Handler)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--auto", type=int, default=0)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--cache", type=int, default=0)
    a = ap.parse_args()
    STATE.update(auto=a.auto, refresh=a.refresh, cache=a.cache)
    srv = make_server(a.host, a.port)
    url = f"http://localhost:{a.port}"
    print(f"Dashboard running at {url}  (refresh the page to update; press Ctrl+C to stop)")
    if a.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
