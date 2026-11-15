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


def best_pair(token: str) -> dict | None:
    pairs = _get(f"/token-pairs/v1/solana/{token}") or []
    if not pairs:
        return None
    # Prefer the deepest open-market pool; fall back to the bonding curve pair.
    return max(pairs, key=lambda p: ((p.get("liquidity") or {}).get("usd") or 0, p.get("marketCap") or 0))


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
