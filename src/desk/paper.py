"""Phase 0 live paper-trading loop. Real market data, fake money, every decision journaled.

python -m desk.paper --minutes 60

Discovers new Solana tokens on DexScreener, screens each one (DexScreener + on-chain
mint checks + optional Grok sentiment), opens $20 paper positions on approvals and
manages them tick by tick with the risk rules. Journal goes to journal/.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import datetime, timezone

from .agents import alerts
from .agents.sentiment_grok import NEUTRAL, score_token
from .config import DEFAULT
from .data import dexscreener as dx
from .data import solana
from .engine import decide
from .risk import Book, Position
from .screener import TokenSnapshot

JOURNAL = os.path.join(os.path.dirname(__file__), "..", "..", "journal")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_snapshot(addr: str) -> TokenSnapshot | None:
    pair = dx.best_pair(addr)
    if not pair:
        return None
    t = TokenSnapshot(address=addr, **dx.snapshot_fields(pair))
    try:
        mi = solana.mint_info(addr)
        t.mint_authority_revoked = mi["mint_authority_revoked"]
        t.freeze_authority_revoked = mi["freeze_authority_revoked"]
    except Exception:
        pass
    try:
        t.top10_pct, _ = solana.top10_pct(addr)
    except Exception:
        pass  # stays None -> hard reject under require_holder_data
    return t


def main(minutes: float, poll: float, use_grok: bool) -> None:
    os.makedirs(JOURNAL, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    dec_path = os.path.join(JOURNAL, f"decisions_{day}.jsonl")
    trade_path = os.path.join(JOURNAL, f"trades_{day}.csv")
    new_file = not os.path.exists(trade_path)
    tf = open(trade_path, "a", newline="")
    tw = csv.writer(tf)
    if new_file:
        tw.writerow(["closed_utc", "symbol", "mode", "hold_s", "pnl_usd", "exit_reason", "fills"])

    s = DEFAULT
    book = Book(risk=s.risk)
    ms = alerts.MilestoneTracker(s.milestones_usd)
    seen: set[str] = set()
    addr_of: dict[str, str] = {}
    end = time.time() + minutes * 60
    alerts.send(f"Paper desk online for {minutes:.0f} min. Stake ${s.risk.stake_usd:.0f}, stop ${s.risk.stop_loss_usd}.")

    while time.time() < end:
        # 1. manage open positions first (exits beat entries)
        for sym, pos in list(book.open.items()):
            px = dx.price(addr_of[sym])
            if px is None:
                pos.on_tick(time.time(), 0.0, rug_alert="pair vanished / no price")
            else:
                act = pos.on_tick(time.time(), px)
                if act:
                    alerts.send(f"{sym}: {act} | P&L ${pos.pnl_at(px):+.2f}")
        for pos in book.settle():
            tw.writerow([_now(), pos.symbol, pos.mode, int(pos.fills[-1].ts - pos.opened_ts),
                         f"{pos.realised_pnl:.2f}", pos.exit_reason, len(pos.fills)])
            tf.flush()
            for m in ms.check(book.realised):
                alerts.send(f"MILESTONE ${m:,.0f} realised. Founder: hold or withdraw?")

        # 2. scan for new tokens
        ok, why = book.can_open()
        if ok:
            for tok in dx.latest_solana_tokens():
                addr = tok["tokenAddress"]
                if addr in seen:
                    continue
                seen.add(addr)
                try:
                    snap = build_snapshot(addr)
                except Exception as e:
                    print("snapshot error", addr, e)
                    continue
                if not snap:
                    continue
                sent = score_token(snap.symbol, addr) if use_grok else NEUTRAL
                d = decide(snap, sent, s.engine, s.screen)
                with open(dec_path, "a") as f:
                    f.write(json.dumps({"ts": _now(), "address": addr, "symbol": snap.symbol, "price_usd": snap.price_usd, "trade": d.trade,
                                        "mode": d.mode, "conviction": d.conviction,
                                        "risk_score": d.screen.risk_score, "reasons": d.reasons,
                                        "unknowns": d.screen.unknowns}) + "\n")
                if d.trade and snap.symbol not in book.open and book.can_open()[0]:
                    px = dx.price(addr)
                    if px:
                        book.open[snap.symbol] = Position.open(snap.symbol, time.time(), px, d.mode, s.risk, s.costs)
                        addr_of[snap.symbol] = addr
                        alerts.send(f"PAPER BUY {snap.symbol} ({d.mode}) conv {d.conviction:.2f} @ {px:.8g}")
        time.sleep(poll)

    # 3. flatten everything at the end of the session
    for sym, pos in book.open.items():
        px = dx.price(addr_of[sym]) or 0.0
        pos._close(time.time(), px, "session end")
    for pos in book.settle():
        tw.writerow([_now(), pos.symbol, pos.mode, int(pos.fills[-1].ts - pos.opened_ts),
                     f"{pos.realised_pnl:.2f}", pos.exit_reason, len(pos.fills)])
    tf.close()
    n = len(book.closed)
    wins = sum(p.realised_pnl > 0 for p in book.closed)
    alerts.send(f"Session done: {n} trades, {wins} winners, realised ${book.realised:+.2f}. Journal: {trade_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--poll", type=float, default=15, help="seconds between scans")
    ap.add_argument("--grok", action="store_true", help="score X sentiment with Grok (needs XAI_API_KEY)")
    a = ap.parse_args()
    main(a.minutes, a.poll, a.grok)
