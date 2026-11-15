"""Pattern Finder (TSB section 4): what do our winners have in common?

Groups closed paper trades by the traits we logged at entry and shows win rate and
average P&L per bucket. With fewer than ~30 trades per bucket this is noise, and it
says so. Use it to decide which config numbers to test next, never to curve-fit.

    cd src && python -m desk patterns
"""
from __future__ import annotations

import json
import os
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TRADES = os.path.join(ROOT, "journal", "firm_trades.jsonl")
MIN_N = 30


def bucket(trade: dict) -> dict[str, str]:
    conv = trade.get("conviction") or 0
    risk = trade.get("risk_score") or 0
    hold = trade.get("hold_s") or 0
    return {
        "desk": trade.get("desk") or "?",
        "mode": trade.get("mode") or "?",
        "conviction": "0.60-0.70" if conv < 0.7 else "0.70-0.80" if conv < 0.8 else "0.80+",
        "risk_score": "0-19" if risk < 20 else "20-39" if risk < 40 else "40+",
        "exit": (trade.get("exit_reason") or "?").split(":")[0],
        "hold": "<2m" if hold < 120 else "2-10m" if hold < 600 else "10m+",
        "stake_recovered": str(bool(trade.get("stake_recovered"))),
    }


def analyse(trades: list[dict]) -> dict[str, dict[str, tuple[int, float, float]]]:
    acc: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for t in trades:
        for trait, val in bucket(t).items():
            acc[trait][val].append(t["pnl_usd"])
    return {trait: {v: (len(p), sum(x > 0 for x in p) / len(p), sum(p) / len(p)) for v, p in vals.items()}
            for trait, vals in acc.items()}


def report(trades: list[dict]) -> str:
    if not trades:
        return "No closed trades yet. Run the firm first."
    out = [f"PATTERN FINDER: {len(trades)} closed trades"]
    for trait, vals in analyse(trades).items():
        out.append(f"\n{trait}")
        for v, (n, wr, avg) in sorted(vals.items(), key=lambda kv: -kv[1][2]):
            warn = "" if n >= MIN_N else "  (too few to trust)"
            out.append(f"  {v:<22} n={n:<4} win {wr:>4.0%}  avg ${avg:+.2f}{warn}")
    return "\n".join(out)


def load() -> list[dict]:
    try:
        return [json.loads(l) for l in open(TRADES)]
    except FileNotFoundError:
        return []


if __name__ == "__main__":
    print(report(load()))
