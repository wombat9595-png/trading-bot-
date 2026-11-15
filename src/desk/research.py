"""Backtest the TJR/Sci structure model on real markets.

python -m desk.research GC=F SI=F QQQ SPY EURUSD=X BTC-USD
"""
from __future__ import annotations

import sys

from .backtest import run
from .config import StructureConfig
from .data.yahoo import fetch
from .structure import find_setups, resample

COST_PCT = {"default": 0.02, "EURUSD=X": 0.01, "QQQ": 0.01, "SPY": 0.01,
            "GC=F": 0.02, "SI=F": 0.04, "BTC-USD": 0.10}   # round-trip spread+fees, % of price


def study(sym: str, cfg: StructureConfig | None = None, htf_filter: bool = True):
    cs = fetch(sym, "1h", "730d")
    htf = resample(cs, 4 * 3600) if htf_filter else None
    setups = find_setups(cs, cfg, htf=htf)
    rep = run(cs, setups, cost_pct=COST_PCT.get(sym, COST_PCT["default"]))
    return cs, rep


if __name__ == "__main__":
    syms = sys.argv[1:] or ["GC=F", "SI=F", "QQQ", "SPY", "EURUSD=X", "BTC-USD"]
    tot_r = tot_n = 0
    for s in syms:
        try:
            cs, rep = study(s)
        except Exception as e:
            print(f"{s}: data error {e}")
            continue
        tot_r += rep.total_r
        tot_n += rep.n
        print(f"{rep.summary(s)}  ({len(cs)} 1H bars)")
    if tot_n:
        print(f"PORTFOLIO: {tot_n} trades, EV {tot_r / tot_n:+.3f}R/trade, total {tot_r:+.1f}R")
