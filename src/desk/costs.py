"""Real trading costs, measured (HANDOVER job 4).

    cd src && python -m desk costs

Gets Jupiter quotes for a $20 buy and the matching sell on live tokens the firm could
actually trade (graduated, liquidity above the screen minimum), plus the current network
fee, and prints them next to the numbers in CostConfig. It never edits config.py: a human
(or the operator, with the founder's say-so) applies the change.

Limits, stated plainly: a quote is the price right now for a trade that lands instantly.
Real fills on fast-moving memecoins can be worse, so the proposal uses the 75th percentile
rounded up, never lowers slippage or the network fee on quote evidence alone, and Phase 1
must re-measure against real fills.
"""
from __future__ import annotations

import math
import os
import statistics

from .config import DEFAULT, CostConfig
from .data import dexscreener as dx
from .data import jupiter as jup
from .data import solana

JUPITER_PROGRAM = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
BASE_FEE_LAMPORTS = 5_000
SWAP_COMPUTE_UNITS = 300_000      # assumption: upper end of a single-pool Jupiter swap


def sol_price_usd() -> float:
    pairs = dx._get(f"/token-pairs/v1/solana/{jup.SOL}") or []
    good = [p for p in pairs if (p.get("baseToken") or {}).get("address") == jup.SOL and p.get("priceUsd")
            and (p.get("quoteToken") or {}).get("symbol") in ("USDC", "USDT")]
    if not good:
        raise RuntimeError("no SOL price")
    return float(max(good, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)["priceUsd"])


def network_fee_usd(sol_price: float) -> tuple[float, str]:
    """Base fee + priority fee for one swap. Priority fee from Helius' estimator ('High' level)."""
    micro, how = 0.0, "base fee only (no priority-fee estimate available)"
    if os.getenv("HELIUS_API_KEY"):
        try:
            est = solana._rpc("getPriorityFeeEstimate", [{"accountKeys": [JUPITER_PROGRAM],
                                                          "options": {"priorityLevel": "High"}}])
            micro = float(est["priorityFeeEstimate"])
            how = f"base 5000 lamports + {micro:,.0f} micro-lamports/CU x {SWAP_COMPUTE_UNITS:,} CU"
        except Exception as e:
            how = f"base fee only (priority estimate failed: {str(e)[:60]})"
    lamports = BASE_FEE_LAMPORTS + SWAP_COMPUTE_UNITS * micro / 1_000_000
    return lamports / jup.LAMPORTS * sol_price, how


def candidates(min_liq: float) -> list[tuple[str, str, float]]:
    """(mint, symbol, liquidity) for live tokens the firm could trade, newest feed order."""
    out = []
    for tok in dx.latest_solana_tokens():
        try:
            pair = dx.best_pair(tok["tokenAddress"])
        except Exception:
            continue
        if not pair or pair.get("dexId") == "pumpfun":
            continue
        liq = (pair.get("liquidity") or {}).get("usd") or 0
        if liq >= min_liq:
            out.append((tok["tokenAddress"], (pair.get("baseToken") or {}).get("symbol", "?"), liq))
    return out


def collect(n: int = 10, usd: float | None = None) -> dict:
    usd = usd or DEFAULT.risk.stake_usd
    sol = sol_price_usd()
    rows, errors = [], []
    for mint, sym, liq in candidates(DEFAULT.screen.min_liquidity_usd):
        if len(rows) >= n:
            break
        try:
            rows.append({"mint": mint, "symbol": sym, "liquidity_usd": liq, **jup.measure(mint, usd, sol, liq)})
        except Exception as e:
            errors.append(f"{sym}: {str(e)[:70]}")
    fee, how = network_fee_usd(sol)
    return {"usd": usd, "sol_price": sol, "rows": rows, "errors": errors, "network_fee_usd": fee, "network_fee_how": how}


def _p75(xs: list[float]) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, math.ceil(0.75 * len(xs)) - 1)]


def _up(x: float, step: float) -> float:
    return round(math.ceil(x / step - 1e-9) * step, 4)


def propose(data: dict, current: CostConfig = DEFAULT.costs) -> CostConfig | None:
    """Pure: measurements -> conservative CostConfig. None if too few quotes.

    venue_fee_pct     measured directly (fees are fixed by the pool): 75th percentile, rounded up.
    slippage_pct      a quote only shows the price impact of our own order. It cannot show the
    network_fee_usd   price moving before the trade lands, or the tip needed to land fast. So a
                      quote can raise these two, but never lower them: that needs real fills.
    """
    rows = data["rows"]
    if len(rows) < 5:
        return None
    return CostConfig(slippage_pct=max(current.slippage_pct, _up(_p75([r["slippage_pct"] for r in rows]), 0.05)),
                      venue_fee_pct=_up(_p75([r["fee_pct"] for r in rows]), 0.05),
                      network_fee_usd=max(current.network_fee_usd, _up(data["network_fee_usd"], 0.01)))


def round_trip_usd(c: CostConfig, usd: float) -> float:
    from .risk import buy_cost, sell_proceeds
    qty, _ = buy_cost(usd, 1.0, c)
    return usd - sell_proceeds(qty, 1.0, c)


def report(data: dict, current: CostConfig = DEFAULT.costs) -> str:
    rows, usd = data["rows"], data["usd"]
    out = [f"REAL COSTS: ${usd:.0f} buy + sell, Jupiter quotes on {len(rows)} live tokens (SOL ${data['sol_price']:.2f})", "",
           f"{'token':<12}{'liquidity':>11}{'round trip':>12}{'impact/side':>13}{'fee/side':>10}  venue"]
    for r in rows:
        out.append(f"{r['symbol'][:11]:<12}{r['liquidity_usd']:>11,.0f}{r['round_trip_pct']:>11.2f}%"
                   f"{r['slippage_pct']:>12.2f}%{r['fee_pct']:>9.2f}%  {', '.join(r['venues'])}")
    if data["errors"]:
        out.append(f"({len(data['errors'])} token(s) had no quote: {'; '.join(data['errors'][:3])})")
    if rows:
        med = lambda k: statistics.median(r[k] for r in rows)
        out += ["", f"median: round trip {med('round_trip_pct'):.2f}%, own price impact {med('slippage_pct'):.2f}%/side, fee {med('fee_pct'):.2f}%/side",
                f"worst:  round trip {max(r['round_trip_pct'] for r in rows):.2f}%"]
    out.append(f"network fee per transaction: ${data['network_fee_usd']:.4f}  ({data['network_fee_how']})")
    new = propose(data, current)
    if new is None:
        out += ["", "Fewer than 5 quotes: not enough to propose a change. CostConfig left alone."]
        return "\n".join(out)
    p75 = lambda k: _p75([r[k] for r in rows])
    out += ["", f"{'CostConfig':<18}{'now':>8}{'measured p75':>14}{'proposed':>10}",
            f"{'slippage_pct':<18}{current.slippage_pct:>8}{p75('slippage_pct'):>14.2f}{new.slippage_pct:>10}",
            f"{'venue_fee_pct':<18}{current.venue_fee_pct:>8}{p75('fee_pct'):>14.2f}{new.venue_fee_pct:>10}",
            f"{'network_fee_usd':<18}{current.network_fee_usd:>8}{data['network_fee_usd']:>14.4f}{new.network_fee_usd:>10}",
            f"cost of one ${usd:.0f} round trip: ${round_trip_usd(current, usd):.2f} now -> ${round_trip_usd(new, usd):.2f} proposed",
            "", "Not applied by this command. Slippage and network fee are never lowered from quotes alone:",
            "a quote assumes an instant fill, and real fills on fast memecoins are worse."]
    return "\n".join(out)


def main() -> None:
    print(report(collect()))
