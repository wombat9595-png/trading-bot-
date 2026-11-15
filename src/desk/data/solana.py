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


def program_owned_set(owners: list[str]) -> set[str]:
    """Which of these addresses are accounts owned by a program (pool, bonding curve, locker),
    i.e. not a person's wallet. Missing accounts count as wallets (conservative)."""
    uniq = list(dict.fromkeys(owners))
    out: set[str] = set()
    for i in range(0, len(uniq), 100):
        chunk = uniq[i:i + 100]
        meta = _rpc("getMultipleAccounts", [chunk, {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}])["value"]
        out |= {o for o, m in zip(chunk, meta) if m and m.get("owner") != SYSTEM_PROGRAM}
    return out


def top10_pct(mint: str) -> tuple[float, int]:
    """% of supply held by the 10 largest HOLDERS, excluding program-owned accounts
    (Pump.fun bonding curve, AMM pool vaults, lockers). Returns (pct, n_excluded).

    Method: largest token accounts -> their owner -> if that owner address is itself an
    account owned by a program other than the System Program, it is a pool/curve, not a person.
    Owners with no account at all are counted as holders (conservative: more concentration).
    """
    supply = float(_rpc("getTokenSupply", [mint])["value"]["uiAmount"] or 0)
    accts = _rpc("getTokenLargestAccounts", [mint])["value"]
    if not supply or not accts:
        raise RuntimeError("no supply/holder data")
    tok = _rpc("getMultipleAccounts", [[a["address"] for a in accts], {"encoding": "jsonParsed"}])["value"]
    owners = [((t or {}).get("data") or {}).get("parsed", {}).get("info", {}).get("owner") for t in tok]
    program_owned = program_owned_set([o for o in owners if o])
    held, excluded = [], 0
    for a, o in zip(accts, owners):
        if o in program_owned:
            excluded += 1
            continue
        held.append(float(a["uiAmount"] or 0))
    return 100 * sum(held[:10]) / supply, excluded
