"""On-chain checks via Solana JSON-RPC. Uses Helius if HELIUS_API_KEY is set, else the
public mainnet RPC (heavily rate-limited; fine for Phase 0 volumes).

Covers red flag 4 (mint/freeze authority) and red flag 3 (top-10 concentration).
Creator history, wash trading and bundle detection live in data/onchain.py.
"""
from __future__ import annotations

import os
import time

import requests


def rpc_url() -> str:
    key = os.getenv("HELIUS_API_KEY")
    return f"https://mainnet.helius-rpc.com/?api-key={key}" if key else "https://api.mainnet-beta.solana.com"


def _rpc(method: str, params: list, retries: int | None = None):
    if retries is None:
        retries = 4 if os.getenv("HELIUS_API_KEY") else 1   # public RPC: fail fast, don't stall the firm
    for attempt in range(retries):
        r = requests.post(rpc_url(), json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=20)
        if r.status_code != 429 or attempt == retries - 1:
            break
        time.sleep(1.5 * 2 ** attempt)   # public RPC rate limit; Helius key removes this
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        raise RuntimeError(body["error"])
    return body["result"]


def mint_info(mint: str) -> dict:
    v = _rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])["value"]
    info = v["data"]["parsed"]["info"]
    return {
        "mint_authority_revoked": info.get("mintAuthority") is None,
        "freeze_authority_revoked": info.get("freezeAuthority") is None,
        "supply": int(info["supply"]),
        "decimals": info["decimals"],
    }


SYSTEM_PROGRAM = "11111111111111111111111111111111"

# Programs whose accounts hold tokens as a market, not as a person. Each one was seen owning a
# pool or curve on live tokens on 15 Nov 2026. Anything NOT on this list is counted as a holder.
POOL_PROGRAMS = {
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": "Pump.fun bonding curve",
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA": "Pump.fun AMM (PumpSwap)",
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo": "Meteora DLMM",
}


def pool_set(owners: list[str], known_pools=()) -> set[str]:
    """Which of these token-account owners are liquidity pools or bonding curves, not holders.

    An owner is a pool only if (a) DexScreener lists that address as a pair for this token
    (`known_pools`), or (b) the account is owned by a program in POOL_PROGRAMS. Everything else
    counts as a holder, including accounts owned by other programs: lockers, vesting contracts
    and self-owned token accounts are still somebody's tokens. (Until 15 Nov 2026 this excluded
    every program-owned account, which hid a creator's 20M-token holding on a live token.)
    """
    uniq = list(dict.fromkeys(o for o in owners if o))
    out = {o for o in uniq if o in set(known_pools)}
    rest = [o for o in uniq if o not in out]
    for i in range(0, len(rest), 100):
        chunk = rest[i:i + 100]
        meta = _rpc("getMultipleAccounts", [chunk, {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}])["value"]
        out |= {o for o, m in zip(chunk, meta) if m and m.get("owner") in POOL_PROGRAMS}
    return out


def top10_pct(mint: str, known_pools=()) -> tuple[float, int]:
    """% of supply held by the 10 largest HOLDERS, excluding liquidity pools and bonding curves
    (see pool_set). Returns (pct, n_excluded). A token account whose owner can't be read is
    counted as a holder (conservative: more concentration).
    """
    supply = float(_rpc("getTokenSupply", [mint])["value"]["uiAmount"] or 0)
    accts = _rpc("getTokenLargestAccounts", [mint])["value"]
    if not supply or not accts:
        raise RuntimeError("no supply/holder data")
    tok = _rpc("getMultipleAccounts", [[a["address"] for a in accts], {"encoding": "jsonParsed"}])["value"]
    owners = [((t or {}).get("data") or {}).get("parsed", {}).get("info", {}).get("owner") for t in tok]
    pools = pool_set([o for o in owners if o], known_pools)
    held, excluded = [], 0
    for a, o in zip(accts, owners):
        if o in pools:
            excluded += 1
            continue
        held.append(float(a["uiAmount"] or 0))
    return 100 * sum(held[:10]) / supply, excluded
