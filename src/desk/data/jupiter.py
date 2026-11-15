"""Jupiter public quote API. Read-only price quotes: no wallet, no key, nothing is signed or sent.

Used only to measure what a real $20 swap would cost (python -m desk costs).
"""
from __future__ import annotations

import time

import requests

QUOTE_URL = "https://lite-api.jup.ag/swap/v1/quote"
SOL = "So11111111111111111111111111111111111111112"
LAMPORTS = 1_000_000_000
_s = requests.Session()


def quote(input_mint: str, output_mint: str, amount: int, retries: int = 3) -> dict:
    """Best-route quote for swapping `amount` raw units of input_mint. Raises if no route."""
    for attempt in range(retries):
        r = _s.get(QUOTE_URL, params={"inputMint": input_mint, "outputMint": output_mint,
                                      "amount": int(amount), "slippageBps": 100}, timeout=15)
        if r.status_code != 429 or attempt == retries - 1:
            break
        time.sleep(2.0 * (attempt + 1))
    if r.status_code != 200:
        raise RuntimeError(f"jupiter {r.status_code}: {r.text[:120]}")
    return r.json()


def round_trip_cost(buy: dict, sell: dict, usd: float, liquidity_usd: float | None) -> dict:
    """Pure: a buy quote (SOL -> token) and the matching sell quote (token -> SOL) -> per-side costs in %.

    total      what one side of the trade costs: sqrt of the round trip, so buy and sell compound
    slippage   price impact of our own order, from pool depth: usd / (half the pool's liquidity).
               (Jupiter's own priceImpactPct is not used for the split: on Pump.fun's AMM it
               includes the pool fee, e.g. ~1.05% on a $55k pool where $20 moves price 0.07%.)
    fee        everything else: pool/venue fees and the spread
    """
    sol_in, sol_back = int(buy["inAmount"]), int(sell["outAmount"])
    if sol_in <= 0 or sol_back <= 0:
        raise ValueError("empty quote")
    total = max(0.0, 100 * (1 - (sol_back / sol_in) ** 0.5))
    impact = 100 * usd / (liquidity_usd / 2) if liquidity_usd else 0.0
    slippage = min(impact, total)
    return {"round_trip_pct": 100 * (1 - sol_back / sol_in), "total_pct": total,
            "slippage_pct": slippage, "fee_pct": total - slippage,
            "jupiter_impact_pct": 100 * (abs(float(buy.get("priceImpactPct") or 0)) + abs(float(sell.get("priceImpactPct") or 0))) / 2,
            "venues": sorted({h["swapInfo"].get("label", "?") for q in (buy, sell) for h in q.get("routePlan") or []})}


def measure(mint: str, usd: float, sol_price: float, liquidity_usd: float | None = None) -> dict:
    lamports = int(usd / sol_price * LAMPORTS)
    buy = quote(SOL, mint, lamports)
    sell = quote(mint, SOL, int(buy["outAmount"]))
    return round_trip_cost(buy, sell, usd, liquidity_usd)
