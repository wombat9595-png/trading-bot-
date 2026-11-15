"""Founder control room: http://127.0.0.1:8050 (localhost only, never exposed to the internet).

Shows open positions, desk P&L, decisions feed, agent heartbeats. Buttons: pause entries,
resume, flatten everything. Reads the files the firm writes; works whether or not the firm
is running.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .firm import JOURNAL, STATE, read_json, write_json

HTML = os.path.join(os.path.dirname(__file__), "web", "dashboard.html")


def tail_jsonl(path: str, n: int) -> list[dict]:
    try:
        with open(path) as f:
            lines = f.readlines()[-n:]
        return [json.loads(l) for l in lines]
    except FileNotFoundError:
        return []


def latest_decisions(n: int = 60) -> list[dict]:
    files = sorted(f for f in os.listdir(JOURNAL) if f.startswith("decisions_")) if os.path.isdir(JOURNAL) else []
    rows: list[dict] = []
    for f in reversed(files):
        rows = tail_jsonl(os.path.join(JOURNAL, f), n - len(rows)) + rows
        if len(rows) >= n:
            break
    return rows[-n:][::-1]


def summary() -> dict:
    trades = tail_jsonl(os.path.join(JOURNAL, "firm_trades.jsonl"), 100000)
    pnl = [t["pnl_usd"] for t in trades]
    eq, peak, dd, curve = 0.0, 0.0, 0.0, []
    for t in trades:
        eq += t["pnl_usd"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        curve.append(round(eq, 2))
    desks: dict[str, dict] = {}
    for t in trades:
        d = desks.setdefault(t.get("desk") or "?", {"n": 0, "wins": 0, "pnl": 0.0})
        d["n"] += 1
        d["wins"] += t["pnl_usd"] > 0
        d["pnl"] = round(d["pnl"] + t["pnl_usd"], 2)
    n = len(pnl)
    return {"n": n, "win_rate": (sum(p > 0 for p in pnl) / n) if n else None,
            "ev": (sum(pnl) / n) if n else None, "total": round(sum(pnl), 2), "max_dd": round(dd, 2),
            "curve": curve[-500:], "desks": desks, "recent": trades[-25:][::-1],
            "gate": {"trades_needed": max(0, 200 - n), "ev_positive": bool(n and sum(pnl) > 0), "dd_ok": dd < 100}}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, open(HTML, "rb").read(), "text/html; charset=utf-8")
        routes = {
            "/api/state": lambda: read_json(os.path.join(STATE, "desk.json"), {}),
            "/api/summary": summary,
            "/api/decisions": latest_decisions,
            "/api/control": lambda: read_json(os.path.join(STATE, "control.json"), {}),
        }
        if self.path in routes:
            return self._send(200, json.dumps(routes[self.path](), default=str).encode())
        self._send(404, b"{}")

    def do_POST(self):
        if self.path != "/api/control":
            return self._send(404, b"{}")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self._send(400, b'{"error":"bad json"}')
        ctl = read_json(os.path.join(STATE, "control.json"), {})
        for k in ("paused", "flatten"):
            if k in body:
                ctl[k] = bool(body[k])
        os.makedirs(STATE, exist_ok=True)
        write_json(os.path.join(STATE, "control.json"), ctl)
        self._send(200, json.dumps(ctl).encode())

    def log_message(self, *a):
        pass


def serve(port: int = 8050) -> ThreadingHTTPServer:
    os.makedirs(STATE, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Control room: http://127.0.0.1:{port}")
    return srv


if __name__ == "__main__":
    serve().serve_forever()
