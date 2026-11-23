"""Private live dashboard: a tiny web server. Reachable only where you bind it (127.0.0.1, or the VM's Tailscale IP).
No cloud, no public URL, nothing uploaded.
PYTHONPATH=src python -m fxengine.dashboard.serve [--port 8787] [--open] [--auto 60] [--refresh] [--cache 30]
  --cache N    SERVE THE LAST FINISHED PAGE INSTANTLY and rebuild in the background when it is older than N seconds
               (default 120). A rebuild reads every pair's price files, which is slow on the 1-vCPU VM and can wait on the
               price-file lock while a download runs, so a visitor must never wait for it. --cache 0 = rebuild on every request.
  --auto N     the page reloads itself every N seconds
  --refresh    on each page load, first fetch the newest prices from OANDA (rate-limited to once a minute; Mac use only)"""
from __future__ import annotations
import argparse
import os, sys, threading, time, traceback, webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ..envfile import load_env
from .build import build

FRESH_WITHIN_S = 90                                          # a cached page older than this is NEVER served as-is: the request waits for a fresh build (it used to return the old page and rebuild afterwards, so even a hard refresh showed hours-old data)
WAIT_FOR_BUILD_S = 45
STUCK_AFTER_S = 300                                          # a rebuild that has not finished after 5 minutes is stuck: the process restarts itself (systemd Restart=always brings it straight back)
STATE = {"building_since": 0.0, "last_refresh": 0.0, "auto": 0, "refresh": False, "lock": threading.Lock(), "html": None, "built": 0.0, "cache": 120,
         "building": False, "error": None, "error_at": 0.0}
WAIT_PAGE = ("<!doctype html><meta charset='utf-8'><meta http-equiv='refresh' content='4'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             "<body style='background:#111110;color:#f0efec;font:18px system-ui;padding:40px'><b>Building the dashboard…</b>"
             "<p style='color:#8d8c84'>The first build after a restart takes a moment on the small server. This page reloads itself.</p></body>")


def _rebuild(note: str = ""):
    try:
        html = build(out=None, banner=note)
        with STATE["lock"]:
            STATE["html"], STATE["built"], STATE["error"] = html, time.time(), None
    except Exception:
        tb = traceback.format_exc()
        sys.stderr.write(f"[fxdash] dashboard rebuild FAILED, serving the last good page:\n{tb}\n"); sys.stderr.flush()       # to the journal: the page banner used to point at a log that was never written
        with STATE["lock"]:
            STATE["error"], STATE["error_at"] = tb, time.time()
    finally:
        with STATE["lock"]:
            STATE["building"] = False


def _start_rebuild(note: str = "") -> bool:
    with STATE["lock"]:
        if STATE["building"]:
            return False
        STATE["building"], STATE["building_since"] = True, time.time()
    threading.Thread(target=_rebuild, args=(note,), daemon=True).start()
    return True


def _fetch_prices() -> str:
    if not STATE["refresh"] or time.time() - STATE["last_refresh"] <= 60:
        return ""
    try:
        from ..live import loop
        loop.refresh(load_env().get("OANDA_TOKEN"))
        STATE["last_refresh"] = time.time()
        return ""
    except Exception as e:                                  # show it, don't hide it
        return f"<div class='sample' style='background:#d03b3b;color:#fff'>Could not fetch newest prices: {escape(str(e))[:160]}</div>"


def _exit_stuck() -> None:
    sys.stderr.write("[fxdash] a dashboard rebuild has been running for more than %d seconds: restarting the server\n" % STUCK_AFTER_S); sys.stderr.flush()
    os._exit(3)


def render() -> str:
    with STATE["lock"]:
        stuck = STATE["building"] and time.time() - STATE["building_since"] > STUCK_AFTER_S
    if stuck:                                                # the page used to freeze at its last build time with no error and no way back
        _exit_stuck()
    note = _fetch_prices()
    if STATE["cache"] <= 0:                                 # legacy: rebuild synchronously on every request
        html = build(out=None, banner=note)
    else:
        with STATE["lock"]:
            html, age = STATE["html"], time.time() - STATE["built"]
        backoff = time.time() - STATE["error_at"] < 60                      # a failing build is retried at most once a minute
        if html is None:
            if not backoff:
                _start_rebuild(note)
            with STATE["lock"]:
                err = STATE["error"]
            if err:
                raise RuntimeError(err)
            return WAIT_PAGE
        if (age > STATE["cache"] or note) and not backoff:
            _start_rebuild(note)
        if age > FRESH_WITHIN_S and not backoff:                          # too old to show: wait (bounded) for the rebuild that is running or was just started
            deadline = time.time() + WAIT_FOR_BUILD_S
            while time.time() < deadline:
                with STATE["lock"]:
                    done = not STATE["building"]
                if done:
                    break
                time.sleep(0.5)
            with STATE["lock"]:
                html, age = STATE["html"], time.time() - STATE["built"]
        if STATE["error"]:
            html = html.replace("<body>", "<body><div style='background:#d03b3b;color:#fff;padding:8px;text-align:center;font:13px system-ui'>"
                                          f"The latest dashboard rebuild failed; showing the last good page built {age / 60:.0f} min ago. Error: {escape(STATE['error'].strip().splitlines()[-1][:200])} (full trace: journalctl -u fxdash)</div>", 1)
        html = html.replace("</body>", f"<div style='text-align:center;color:#8d8c84;font:12px system-ui;padding:10px'>Page built {age:.0f}s ago · "
                                       f"rebuilds in the background every {STATE['cache']}s · reload to see the newest</div></body>", 1)
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
    ap.add_argument("--auto", type=int, default=60)           # reload the page itself every 60 s (the engine cycles every 5 min)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--cache", type=int, default=120)
    a = ap.parse_args()
    STATE.update(auto=a.auto, refresh=a.refresh, cache=a.cache)
    srv = make_server(a.host, a.port)
    url = f"http://localhost:{a.port}"
    print(f"Dashboard running at {url}  (press Ctrl+C to stop)")
    if a.cache > 0:
        _start_rebuild()                                    # warm the cache at start-up so the first visit is instant
    if a.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
