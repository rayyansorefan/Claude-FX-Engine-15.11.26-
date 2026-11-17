"""Private paper-trading dashboard server. Binds to 127.0.0.1 by default; on the VM bind it to the Tailscale IP only (never 0.0.0.0, never a public port).
Every bet is a PAPER bet in a local SQLite ledger: nothing goes to any bookmaker.
  PYTHONPATH=src python -m fxengine.bets.paper_serve --host $(tailscale ip -4) --port 8789
Background thread: every --every seconds it refreshes fixtures, auto-places qualifying paper bets (V1/V1P) and settles finished matches."""
from __future__ import annotations
import argparse, json, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from . import dashboard, paper

LOCK = threading.Lock()                       # one writer at a time; the ledger is tiny


def _results(path=Path("docs/results/bets.json")):
    return json.loads(path.read_text()) if path.exists() else None


def page(conn) -> str:
    with LOCK:
        st = paper.state(conn)
    return dashboard.render(_results(), paper=st)


def api_bet(conn, body: dict) -> tuple[int, dict]:
    """Place a PAPER bet from the dashboard. Returns (http status, json)."""
    try:
        with LOCK:
            row = conn.execute("SELECT json FROM fixtures WHERE id=?", (str(body.get("id", "")),)).fetchone()
            if not row:
                return 404, dict(ok=False, error="That match is no longer in the list. Refresh prices.")
            bid = paper.place(conn, json.loads(row["json"]), str(body.get("market", "")), str(body.get("sel", "")), float(body.get("stake")))
        return 200, dict(ok=True, id=bid)
    except (ValueError, TypeError) as e:
        return 400, dict(ok=False, error=str(e) if isinstance(e, ValueError) else "Enter a stake in pounds.")


def make_handler(conn, tick_fn=None):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json"):
            b = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8"); self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)

        def do_GET(self):
            if self.path.split("?")[0] in ("/", "/index.html"):
                return self._send(200, page(conn), "text/html")
            if self.path == "/api/state":
                with LOCK:
                    return self._send(200, json.dumps(paper.state(conn), default=str))
            self._send(404, json.dumps(dict(ok=False, error="not found")))

        def do_POST(self):
            if "application/json" not in (self.headers.get("Content-Type") or ""):   # a plain cross-site <form> cannot send JSON
                return self._send(415, json.dumps(dict(ok=False, error="JSON only")))
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(min(n, 10_000)) or b"{}")
            except ValueError:
                return self._send(400, json.dumps(dict(ok=False, error="bad request")))
            if self.path == "/api/bet":
                code, out = api_bet(conn, body)
                return self._send(code, json.dumps(out))
            if self.path == "/api/tick":
                with LOCK:
                    out = (tick_fn or paper.tick)(conn)
                return self._send(200, json.dumps(dict(ok=True, **out)))
            self._send(404, json.dumps(dict(ok=False, error="not found")))

        def log_message(self, *a):           # quiet
            pass
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8789)
    ap.add_argument("--every", type=int, default=1800, help="seconds between automatic fixture/result checks (0 = off)")
    a = ap.parse_args()
    if a.host in ("0.0.0.0", "::"):
        raise SystemExit("Refusing to bind to all interfaces: use 127.0.0.1 or the VM's Tailscale IP.")
    conn = paper.connect()

    def loop():
        while a.every:
            try:
                with LOCK:
                    print("tick", paper.tick(conn), flush=True)
            except Exception as e:           # never let the background thread die
                print("tick failed", type(e).__name__, flush=True)
            time.sleep(a.every)
    threading.Thread(target=loop, daemon=True).start()
    print(f"paper dashboard on http://{a.host}:{a.port}  (paper bets only)", flush=True)
    ThreadingHTTPServer((a.host, a.port), make_handler(conn)).serve_forever()


if __name__ == "__main__":
    main()
