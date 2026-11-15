"""On-chain forensics for the four red flags DexScreener can't see.

Standard Solana JSON-RPC only (getSignaturesForAddress, getTransaction, getMultipleAccounts),
so it works on any RPC. Use Helius in practice: the public RPC rate-limits this to death.

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

from .solana import _rpc, program_owned_set

PAGE = 1000


def walk_signatures(address: str, max_pages: int = 5) -> tuple[list[dict], bool]:
    """All signatures for an address, newest first. Returns (signatures, reached_the_true_start)."""
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
    """Walk signatures backwards. Returns (oldest seen, reached_the_true_start)."""
    sigs, complete = walk_signatures(address, max_pages)
    return (sigs[-1] if sigs else None), complete


MAX_SAME_SLOT_TXS = 40    # cap on RPC calls; a launch slot with more buys than this is itself a red flag


def get_tx(sig: str) -> dict | None:
    return _rpc("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])


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


def creator_profile(mint: str, supply_ui: float) -> dict:
    sigs, complete = walk_signatures(mint)
    if not sigs or not complete:
        raise RuntimeError("could not reach the launch transaction (too much history)")
    first = sigs[-1]
    tx = get_tx(first["signature"])
    creator = fee_payer(tx)
    deltas = token_deltas(tx, mint)
    # Bundles: buys that land in the SAME SLOT as the launch. Nobody outside the team can react
    # that fast by chance, so same-slot buyers are treated as insiders (or paid snipers) too.
    # Signatures come newest first, so the launch slot's other transactions sit just before it.
    slot = first.get("slot")
    same_slot = [g for g in sigs[:-1] if slot is not None and g.get("slot") == slot and not g.get("err")]
    same_slot_deltas = []
    for g in same_slot[-MAX_SAME_SLOT_TXS:]:
        t = get_tx(g["signature"])
        if t:
            same_slot_deltas.append(token_deltas(t, mint))
    pools = program_owned_set(list({o for d in [deltas, *same_slot_deltas] for o in d}))
    net: dict[str, float] = defaultdict(float)       # net tokens each wallet took in the launch slot
    for d in [deltas, *same_slot_deltas]:
        for o, amt in d.items():
            if o not in pools:
                net[o] += amt
    in_launch_tx = {o for o, d in deltas.items() if d > 0 and o not in pools and o != creator}
    bundled = {o: a for o, a in net.items() if a > 0 and o != creator}
    creator_buy = max(0.0, net.get(creator, 0.0))
    out = {
        "creator": creator,
        "launch_ts": first.get("blockTime"),
        "creator_initial_buy_pct": 100 * creator_buy / supply_ui if supply_ui else None,
        "bundled_wallets": len(bundled),
        "bundled_pct": 100 * sum(bundled.values()) / supply_ui if supply_ui else None,
        "bundled_in_launch_tx": len(in_launch_tx & set(bundled)),
        "bundled_same_slot": len(set(bundled) - in_launch_tx),
        "same_slot_txs": len(same_slot),
        "same_slot_truncated": len(same_slot) > MAX_SAME_SLOT_TXS,
    }
    w_first, _ = oldest_signature(creator, max_pages=3)
    if w_first and w_first.get("blockTime"):
        # lower bound if the wallet has more history than we paged through: still "old enough"
        out["creator_wallet_age_days"] = (time.time() - w_first["blockTime"]) / 86400
    return out


def flow_stats(mint: str, n: int = 60) -> dict:
    sigs = _rpc("getSignaturesForAddress", [mint, {"limit": n}])
    per_tx = []
    for s in sigs:
        if s.get("err"):
            continue
        tx = get_tx(s["signature"])
        if tx:
            per_tx.append(token_deltas(tx, mint))
    return summarise_flow(per_tx, program_owned_set(list({o for d in per_tx for o in d})))


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
