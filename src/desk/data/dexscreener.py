"""Market data: token discovery + live price/flow from DexScreener's public API (no key).

Verified response fields (Nov 2026): pairs carry dexId, priceUsd, liquidity{usd} (null while
on the Pump.fun bonding curve), marketCap, pairCreatedAt (ms), txns{m5,h1,...{buys,sells}},
priceChange{m5,...}, info.socials.
"""
from __future__ import annotations

import time

import requests

BASE = "https://api.dexscreener.com"
_s = requests.Session()


def _get(path: str):
    r = _s.get(BASE + path, timeout=15)
    r.raise_for_status()
    return r.json()


def latest_solana_tokens() -> list[dict]:
    """Newest token profiles + boosts on Solana (deduplicated)."""
    seen, out = set(), []
    for path, src in (("/token-profiles/latest/v1", "profile"), ("/token-boosts/latest/v1", "boost")):
        try:
            for t in _get(path):
                if t.get("chainId") == "solana" and t["tokenAddress"] not in seen:
                    seen.add(t["tokenAddress"])
                    out.append({**t, "_source": src})
        except requests.RequestException:
            continue
    return out


def pairs(token: str) -> list[dict]:
    return _get(f"/token-pairs/v1/solana/{token}") or []


def _activity(p: dict) -> tuple:
    h1 = (p.get("txns") or {}).get("h1") or {}
    return ((h1.get("buys") or 0) + (h1.get("sells") or 0), (p.get("volume") or {}).get("h24") or 0,
            (p.get("liquidity") or {}).get("usd") or 0, p.get("marketCap") or 0)


def pick_best(all_pairs: list[dict], prefer: str | None = None) -> dict | None:
    """The pair where this token actually trades: most transactions in the last hour, then 24h
    volume, then liquidity. `prefer` pins a specific pair address (the one a position was opened
    on) so its price and liquidity are compared like with like.

    Ranking by liquidity alone was wrong on live data (15 Nov 2026): a token still on the
    Pump.fun bonding curve shows no liquidity figure there, so a stray $1.40 Meteora pool with
    one trade all day outranked the curve doing 1,500 trades an hour.
    """
    if not all_pairs:
        return None
    if prefer:
        for p in all_pairs:
            if p.get("pairAddress") == prefer:
                return p
    return max(all_pairs, key=_activity)


def best_pair(token: str, prefer: str | None = None) -> dict | None:
    return pick_best(pairs(token), prefer)


def snapshot_fields(pair: dict) -> dict:
    """Map a DexScreener pair onto TokenSnapshot fields it can actually measure."""
    m5 = (pair.get("txns") or {}).get("m5") or {}
    socials = (pair.get("info") or {}).get("socials") or []
    created = pair.get("pairCreatedAt")
    liq = (pair.get("liquidity") or {}).get("usd")
    return {
        "symbol": (pair.get("baseToken") or {}).get("symbol", ""),
        "graduated": pair.get("dexId") != "pumpfun",
        "liquidity_usd": liq,
        "buys_5m": m5.get("buys"),
        "sells_5m": m5.get("sells"),
        "price_change_5m_pct": (pair.get("priceChange") or {}).get("m5"),
        "age_minutes": (time.time() * 1000 - created) / 60000 if created else None,
        "price_usd": float(pair["priceUsd"]) if pair.get("priceUsd") else None,
        "has_x_account": any(s.get("type") == "twitter" for s in socials),
    }


def price(token: str) -> float | None:
    p = best_pair(token)
    return float(p["priceUsd"]) if p and p.get("priceUsd") else None
