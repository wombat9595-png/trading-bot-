"""On-chain forensics for the four red flags DexScreener can't see.

Uses Helius' getTransactionsForAddress when available: it returns whole transactions
oldest-first or newest-first in ONE call. That matters because a live Pump.fun token gets
5,000-25,000 transactions in its first hour (measured 15 Nov 2026), so walking back to the
launch with standard getSignaturesForAddress takes dozens of calls. On any other RPC the
code falls back to the standard methods (getSignaturesForAddress + getTransaction).

  creator_profile(mint) -> creator wallet, creator's opening buy % (red flag 1), bundled-launch
                           wallets that bought in the creation transaction OR in the same slot
                           right after it, wallet age (red flag 5)
  flow_stats(mint)      -> unique buyers, biggest single-wallet trade share, wash ratio
                           (red flags 2 and 6), from the most recent N transactions

Pump.fun creates and dev-buys in one transaction, so the oldest transaction on the mint is
the launch: its fee payer is the creator and its token balance changes are the opening buys.
"""
from __future__ import annotations

import time
from collections import defaultdict

from .solana import _rpc, pool_set

PAGE = 1000
MAX_TX_VERSION = 1        # Solana added version-1 transactions; asking for 0 makes the RPC refuse them
TX_OPTS = {"encoding": "jsonParsed", "maxSupportedTransactionVersion": MAX_TX_VERSION}
MAX_SAME_SLOT_TXS = 40    # cap on fallback RPC calls; a launch slot busier than this is itself a red flag
HELIUS_PAGE = 100         # getTransactionsForAddress returns at most 100 full transactions per call

_fast_ok = True           # flips to False the first time the RPC says it has no getTransactionsForAddress


def helius_txs(address: str, order: str, limit: int, details: str = "full") -> list[dict] | None:
    """Transactions touching an address, 'asc' (oldest first) or 'desc', in one call.
    Returns None when the RPC doesn't support the method, so callers can fall back."""
    global _fast_ok
    if not _fast_ok:
        return None
    opts = {"transactionDetails": details, "sortOrder": order, "limit": min(limit, HELIUS_PAGE if details == "full" else PAGE)}
    if details == "full":
        opts.update(TX_OPTS)
    try:
        return _rpc("getTransactionsForAddress", [address, opts])["data"]
    except RuntimeError as e:
        if "-32601" in str(e) or "not found" in str(e).lower() or "not supported" in str(e).lower():
            _fast_ok = False
            return None
        raise


def walk_signatures(address: str, max_pages: int = 30) -> tuple[list[dict], bool]:
    """Fallback path. All signatures for an address, newest first. Returns (signatures, reached_the_true_start)."""
    before, out = None, []
    for _ in range(max_pages):
        opts = {"limit": PAGE}
        if before:
            opts["before"] = before
        page = _rpc("getSignaturesForAddress", [address, opts])
        if not page:
            return out, bool(out)
        out.extend(page)
        before = page[-1]["signature"]
        if len(page) < PAGE:
            return out, True
    return out, False


def oldest_signature(address: str, max_pages: int = 5) -> tuple[dict | None, bool]:
    """The first transaction an address ever appeared in. Returns (signature info, reached_the_true_start)."""
    fast = helius_txs(address, "asc", 1, details="signatures")
    if fast is not None:
        return (fast[0] if fast else None), True
    sigs, complete = walk_signatures(address, max_pages)
    return (sigs[-1] if sigs else None), complete


def get_tx(sig: str) -> dict | None:
    return _rpc("getTransaction", [sig, TX_OPTS])


def launch_slot_txs(mint: str) -> tuple[dict, list[dict], int, bool]:
    """(launch transaction, successful transactions later in the same slot, how many of those
    exist, whether the list was cut short). Both paths return the same shape."""
    fast = helius_txs(mint, "asc", HELIUS_PAGE)
    if fast is not None:
        if not fast:
            raise RuntimeError("no transactions found for this mint")
        launch, slot = fast[0], fast[0].get("slot")
        same = [t for t in fast[1:] if t.get("slot") == slot and not (t.get("meta") or {}).get("err")]
        truncated = len(fast) == HELIUS_PAGE and fast[-1].get("slot") == slot
        return launch, same, len(same), truncated
    sigs, complete = walk_signatures(mint)
    if not sigs or not complete:
        raise RuntimeError("could not reach the launch transaction (too much history)")
    first, slot = sigs[-1], sigs[-1].get("slot")
    launch = get_tx(first["signature"])
    if not launch:
        raise RuntimeError("launch transaction not available")
    launch.setdefault("blockTime", first.get("blockTime"))
    # signatures come newest first, so the launch slot's other transactions sit just before it
    same_sigs = [g for g in sigs[:-1] if slot is not None and g.get("slot") == slot and not g.get("err")]
    same = [t for t in (get_tx(g["signature"]) for g in same_sigs[-MAX_SAME_SLOT_TXS:]) if t]
    return launch, same, len(same_sigs), len(same_sigs) > MAX_SAME_SLOT_TXS


def fee_payer(tx: dict) -> str:
    k = tx["transaction"]["message"]["accountKeys"][0]
    return k["pubkey"] if isinstance(k, dict) else k


def token_deltas(tx: dict, mint: str) -> dict[str, float]:
    """owner wallet -> change in token balance (ui units) for this mint in this transaction."""
    meta = tx.get("meta") or {}
    pre = defaultdict(float)
    post = defaultdict(float)
    for side, store in (("preTokenBalances", pre), ("postTokenBalances", post)):
        for b in meta.get(side) or []:
            if b.get("mint") == mint and b.get("owner"):
                store[b["owner"]] += float((b.get("uiTokenAmount") or {}).get("uiAmount") or 0)
    return {o: post[o] - pre[o] for o in set(pre) | set(post) if abs(post[o] - pre[o]) > 0}


def creator_profile(mint: str, supply_ui: float, known_pools=()) -> dict:
    launch, same_slot, n_same_slot, truncated = launch_slot_txs(mint)
    creator = fee_payer(launch)
    deltas = token_deltas(launch, mint)
    # Bundles: buys that land in the SAME SLOT as the launch. Nobody outside the team can react
    # that fast by chance, so same-slot buyers are treated as insiders (or paid snipers) too.
    same_slot_deltas = [token_deltas(t, mint) for t in same_slot]
    pools = pool_set(list({o for d in [deltas, *same_slot_deltas] for o in d}), known_pools)
    net: dict[str, float] = defaultdict(float)       # net tokens each wallet took in the launch slot
    for d in [deltas, *same_slot_deltas]:
        for o, amt in d.items():
            if o not in pools:
                net[o] += amt
    in_launch_tx = {o for o, d in deltas.items() if d > 0 and o not in pools and o != creator}
    bundled = {o: a for o, a in net.items() if a > 0 and o != creator}
    creator_buy = max(0.0, net.get(creator, 0.0))
    # Opening buys are a share of the supply that existed AT LAUNCH (what the launch transaction
    # minted). Today's supply can be smaller after burns, which would overstate the percentages.
    minted = sum(d for d in deltas.values() if d > 0)
    supply_ui = max(supply_ui or 0.0, minted)
    out = {
        "creator": creator,
        "launch_signature": (launch.get("transaction") or {}).get("signatures", [None])[0],
        "launch_ts": launch.get("blockTime"),
        "creator_initial_buy_pct": 100 * creator_buy / supply_ui if supply_ui else None,
        "bundled_wallets": len(bundled),
        "bundled_pct": 100 * sum(bundled.values()) / supply_ui if supply_ui else None,
        "bundled_in_launch_tx": len(in_launch_tx & set(bundled)),
        "bundled_same_slot": len(set(bundled) - in_launch_tx),
        "same_slot_txs": n_same_slot,
        "same_slot_truncated": truncated,
    }
    w_first, _ = oldest_signature(creator, max_pages=3)
    if w_first and w_first.get("blockTime"):
        # lower bound if the wallet has more history than we paged through: still "old enough"
        out["creator_wallet_age_days"] = (time.time() - w_first["blockTime"]) / 86400
    return out


def recent_txs(mint: str, n: int) -> list[dict]:
    """The most recent n successful-or-not transactions on a mint, full detail."""
    fast = helius_txs(mint, "desc", n)
    if fast is not None:
        return fast
    sigs = _rpc("getSignaturesForAddress", [mint, {"limit": n}])
    return [t for t in (get_tx(s["signature"]) for s in sigs if not s.get("err")) if t]


def flow_stats(mint: str, n: int = 60, known_pools=()) -> dict:
    per_tx = [token_deltas(tx, mint) for tx in recent_txs(mint, n) if not (tx.get("meta") or {}).get("err")]
    per_tx = [d for d in per_tx if d]                 # a transaction that moved none of this token is not a trade
    return summarise_flow(per_tx, pool_set(list({o for d in per_tx for o in d}), known_pools))


def summarise_flow(per_tx: list[dict[str, float]], pools: set[str]) -> dict:
    """Pure: per-transaction owner deltas -> flow red-flag metrics."""
    bought = defaultdict(float)
    sold = defaultdict(float)
    trades = defaultdict(int)
    n_buys = defaultdict(int)
    n_sells = defaultdict(int)
    for d in per_tx:
        for o, amt in d.items():
            if o in pools:
                continue
            trades[o] += 1
            if amt > 0:
                bought[o] += amt
                n_buys[o] += 1
            else:
                sold[o] += -amt
                n_sells[o] += 1
    total_trades = sum(trades.values())
    volume = sum(bought.values()) + sum(sold.values())
    # A normal flipper buys once and sells once. Wash bots cycle: 2+ buys AND 2+ sells.
    round_trippers = {o for o in trades if n_buys[o] >= 2 and n_sells[o] >= 2}
    wash_vol = sum(bought[o] + sold[o] for o in round_trippers)
    return {
        "sample_txs": len(per_tx),
        "unique_buyers": len(bought),
        "max_single_wallet_trade_share": max(trades.values()) / total_trades if total_trades else None,
        "wash_ratio": wash_vol / volume if volume else None,
    }
