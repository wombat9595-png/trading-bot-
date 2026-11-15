"""One command for the whole firm.

  python -m desk run [--grok] [--minutes N]   firm + control room (http://127.0.0.1:8050)
  python -m desk dashboard                    control room only
  python -m desk check <mint>                 Holder Scout report on one token
  python -m desk brief                        News Desk morning briefing (prints + Telegram)
  python -m desk patterns                     Pattern Finder report
  python -m desk backtest                     TJR/Sci model on real hourly data
  python -m desk tracker                      rug-catch scoreboard
  python -m desk doctor                       checks keys and connections
"""
from __future__ import annotations

import argparse
import os
import sys
import threading


def load_env() -> None:
    path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip())


def doctor() -> None:
    import requests
    from .data import dexscreener as dx
    from .data import solana
    ok = lambda b: "OK " if b else "-- "
    print(ok(True), "Python", sys.version.split()[0])
    try:
        print(ok(bool(dx.latest_solana_tokens())), "DexScreener feed")
    except Exception as e:
        print("-- ", "DexScreener feed:", e)
    try:
        solana._rpc("getSlot", [])
        print(ok(True), "Solana RPC", "(Helius)" if os.getenv("HELIUS_API_KEY") else "(public: will rate-limit, get a Helius key)")
    except Exception as e:
        print("-- ", "Solana RPC:", str(e)[:80])
    for k, why in (("HELIUS_API_KEY", "holder + creator forensics (required for trades)"),
                   ("TELEGRAM_BOT_TOKEN", "alerts"), ("TELEGRAM_CHAT_ID", "alerts"),
                   ("XAI_API_KEY", "Grok X sentiment + morning brief (optional)"),
                   ("ANTHROPIC_API_KEY", "Claude reviewer (optional)")):
        print(ok(bool(os.getenv(k))), f"{k:<20} {why}")
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        try:
            r = requests.get(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/getMe", timeout=10).json()
            print(ok(r.get("ok")), "Telegram bot", r.get("result", {}).get("username", r))
        except Exception as e:
            print("-- ", "Telegram:", e)


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(prog="desk")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--grok", action="store_true")
    r.add_argument("--minutes", type=float)
    r.add_argument("--port", type=int, default=8050)
    sub.add_parser("dashboard").add_argument("--port", type=int, default=8050)
    sub.add_parser("check").add_argument("mint")
    sub.add_parser("brief")
    sub.add_parser("patterns")
    sub.add_parser("backtest")
    sub.add_parser("tracker")
    sub.add_parser("doctor")
    a = ap.parse_args()

    if a.cmd == "run":
        from .dashboard import serve
        from .firm import Firm
        srv = serve(a.port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        Firm(use_grok=a.grok).run(a.minutes)
    elif a.cmd == "dashboard":
        from .dashboard import serve
        serve(a.port).serve_forever()
    elif a.cmd == "check":
        from .bot import verdict
        from .config import DEFAULT
        from .paper import build_snapshot
        from .screener import screen
        snap = build_snapshot(a.mint)
        print(verdict(snap, screen(snap, DEFAULT.screen)) if snap else "No pair found.")
    elif a.cmd == "brief":
        from .agents.alerts import send
        from .news import morning_brief
        text = morning_brief()
        print(text)
        send(text)
    elif a.cmd == "patterns":
        from .patterns import load, report
        print(report(load()))
    elif a.cmd == "backtest":
        import runpy
        sys.argv = ["research"]
        runpy.run_module("desk.research", run_name="__main__")
    elif a.cmd == "tracker":
        from .tracker import main as tmain
        tmain(24)
    elif a.cmd == "doctor":
        doctor()


if __name__ == "__main__":
    main()
