import json, os, threading, urllib.request

import pytest

import desk.firm as firm_mod
import desk.dashboard as dash
from desk.config import DEFAULT
from desk.data.onchain import summarise_flow, token_deltas, creator_profile
from desk.screener import TokenSnapshot
from desk.strategies import assign_desk, desk_has_room, momentum_faded

GOOD = dict(mint_authority_revoked=True, freeze_authority_revoked=True, graduated=True, liquidity_usd=50_000,
            top10_pct=15, creator_initial_buy_pct=1, creator_wallet_age_days=100, unique_buyers=50,
            max_single_wallet_trade_share=0.05, wash_ratio=0.05, has_x_account=True,
            buys_5m=120, sells_5m=60, price_change_5m_pct=20, age_minutes=30, price_usd=1.0)


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    st, jr = tmp_path / "state", tmp_path / "journal"
    for m in (firm_mod, dash):
        monkeypatch.setattr(m, "STATE", str(st))
        monkeypatch.setattr(m, "JOURNAL", str(jr))
    return st, jr


class Market:
    def __init__(self):
        self.price, self.liq, self.alive, self.m5 = 1.0, 50_000, True, {"buys": 120, "sells": 60}

    def pair(self, addr):
        if not self.alive:
            return None
        return {"priceUsd": str(self.price), "liquidity": {"usd": self.liq}, "txns": {"m5": self.m5}}


def make(market, sent=None, tokens=None):
    sent_msgs = sent if sent is not None else []
    return firm_mod.Firm(
        DEFAULT,
        snapshot_fn=lambda a, deep=True: TokenSnapshot(a, symbol="GOOD", **GOOD),
        pair_fn=market.pair,
        tokens_fn=lambda: tokens if tokens is not None else [{"tokenAddress": "MintA", "_source": "profile"}],
        send_fn=sent_msgs.append)


def test_firm_opens_manages_and_journals(dirs):
    st, jr = dirs
    mk, msgs = Market(), []
    f = make(mk, msgs)
    f.cycle()
    assert "GOOD" in f.book.open and f.meta["GOOD"]["desk"] == "verification"
    state = json.load(open(st / "desk.json"))
    assert state["open"][0]["symbol"] == "GOOD"
    mk.liq = 10_000                                  # LP pulled -> live rug watch
    f.cycle()
    assert not f.book.open
    t = [json.loads(l) for l in open(jr / "firm_trades.jsonl")]
    assert t[0]["exit_reason"].startswith("RUG WATCH") and t[0]["desk"] == "verification"
    assert any("PAPER BUY" in m for m in msgs)


def test_pause_blocks_entries_and_flatten_closes(dirs):
    st, _ = dirs
    mk = Market()
    os.makedirs(st, exist_ok=True)
    json.dump({"paused": True}, open(st / "control.json", "w"))
    f = make(mk)
    f.cycle()
    assert not f.book.open
    json.dump({"paused": False}, open(st / "control.json", "w"))
    f.seen.clear()
    f.cycle()
    assert f.book.open
    json.dump({"flatten": True}, open(st / "control.json", "w"))
    f.cycle()
    assert not f.book.open
    assert json.load(open(st / "control.json"))["paused"] is True


def test_verification_exit_on_momentum_fade(dirs):
    mk = Market()
    f = make(mk)
    f.cycle()
    mk.m5 = {"buys": 10, "sells": 30}
    f.cycle()
    assert not f.book.open


def test_pair_vanish_is_rug_but_network_error_is_not(dirs):
    mk = Market()
    f = make(mk)
    f.cycle()
    f.pair_fn = lambda a: (_ for _ in ()).throw(ConnectionError())
    f.cycle()
    assert f.book.open                             # network blip: hold
    f.pair_fn = mk.pair
    mk.alive = False
    f.cycle()
    assert not f.book.open


def test_desk_routing():
    d, s = DEFAULT.desks, DEFAULT.screen
    assert assign_desk(TokenSnapshot("a", **GOOD), "profile", d, s) == "verification"
    assert assign_desk(TokenSnapshot("a", **GOOD), "boost", d, s) == "foot_in_door"
    assert assign_desk(TokenSnapshot("a", **{**GOOD, "graduated": False}), "boost", d, s) is None
    assert not desk_has_room("verification", ["verification"] * 2, d)
    assert momentum_faded(10, 30, d) and not momentum_faded(30, 10, d) and not momentum_faded(1, 3, d)


def test_wash_detection():
    # bot cycles 3 buys + 3 sells; normal flipper buys once sells once; holder just buys
    txs = [{"bot": 100}, {"bot": -100}] * 3 + [{"flip": 50}, {"flip": -50}, {"holder": 200}, {"POOL": -999}]
    f = summarise_flow(txs, {"POOL"})
    assert f["unique_buyers"] == 3
    assert f["wash_ratio"] == pytest.approx(600 / 900)
    assert f["max_single_wallet_trade_share"] == pytest.approx(6 / 9)


def _tx(payer, mint, pre, post):
    bal = lambda d: [{"mint": mint, "owner": o, "uiTokenAmount": {"uiAmount": a}} for o, a in d.items()]
    return {"transaction": {"message": {"accountKeys": [{"pubkey": payer, "signer": True}]}},
            "meta": {"preTokenBalances": bal(pre), "postTokenBalances": bal(post)}}


def test_creator_profile_counts_bundles(monkeypatch):
    import desk.data.onchain as oc
    launch = _tx("dev", "M", {}, {"curvePDA": 800, "dev": 60, "sniper2": 40})
    def rpc(method, params, retries=4):
        if method == "getSignaturesForAddress":
            return [{"signature": "s1", "blockTime": 1_700_000_000}]
        if method == "getTransaction":
            return launch
        raise AssertionError(method)
    monkeypatch.setattr(oc, "_rpc", rpc)
    monkeypatch.setattr(oc, "pool_set", lambda owners, known_pools=(): {"curvePDA"})
    monkeypatch.setattr(oc, "_fast_ok", False)       # standard-RPC path (no Helius getTransactionsForAddress)
    cp = creator_profile("M", 1000)
    assert cp["creator"] == "dev" and cp["creator_initial_buy_pct"] == 6.0
    assert cp["bundled_wallets"] == 1 and cp["bundled_pct"] == 4.0
    assert cp["creator_wallet_age_days"] > 100


def test_token_deltas():
    d = token_deltas(_tx("p", "M", {"a": 10, "b": 5}, {"a": 4, "b": 5, "c": 6}), "M")
    assert d == {"a": -6, "c": 6}


def test_dashboard_api(dirs):
    st, jr = dirs
    os.makedirs(jr, exist_ok=True)
    with open(jr / "firm_trades.jsonl", "w") as fh:
        for p in (5, -7.5, 2):
            fh.write(json.dumps({"closed_utc": "2026-11-15T00:00:00+00:00", "symbol": "X", "desk": "foot_in_door", "pnl_usd": p, "exit_reason": "x"}) + "\n")
    s = dash.summary()
    assert s["n"] == 3 and s["max_dd"] == 7.5 and s["desks"]["foot_in_door"]["wins"] == 2
    srv = dash.serve(0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/control", data=b'{"paused": true}', method="POST",
                                     headers={"Content-Type": "application/json"})
        assert json.load(urllib.request.urlopen(req))["paused"] is True
        html = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read()
        assert b"Desk Control Room" in html
    finally:
        srv.shutdown()


def test_patterns_report():
    from desk.patterns import report
    out = report([{"desk": "verification", "mode": "standard", "conviction": 0.75, "risk_score": 10,
                   "exit_reason": "stop-loss", "hold_s": 60, "pnl_usd": -7.5}])
    assert "verification" in out and "too few" in out


# ---------- restart survival (state/positions.json) ----------

def test_open_position_survives_restart(dirs):
    st, jr = dirs
    mk, msgs = Market(), []
    f1 = make(mk)
    f1.cycle()
    before = f1.book.open["GOOD"]
    assert json.load(open(st / "positions.json"))["positions"][0]["symbol"] == "GOOD"

    f2 = make(mk, msgs)                               # simulated crash: brand-new process, same state dir
    assert f2.restored == 1
    after = f2.book.open["GOOD"]
    assert after.qty == before.qty and after.opened_ts == before.opened_ts and after.stake == before.stake
    assert after.fills == before.fills and after.mode == before.mode
    assert f2.meta["GOOD"] == f1.meta["GOOD"]
    f2.cycle()
    assert list(f2.book.open) == ["GOOD"]             # still managed, and not bought a second time
    assert f2.stats["approved"] == 0
    mk.liq = 10_000                                   # the restored position still gets rug watch
    f2.cycle()
    assert not f2.book.open
    trades = [json.loads(l) for l in open(jr / "firm_trades.jsonl")]
    assert len(trades) == 1 and trades[0]["exit_reason"].startswith("RUG WATCH")
    assert trades[0]["desk"] == "verification" and trades[0]["entry_price"] == before.fills[0].price

    f3 = make(mk)                                     # a closed trade must not come back from the dead
    assert f3.restored == 0 and not f3.book.open


def test_recovered_stake_and_floor_survive_restart(dirs):
    mk = Market()
    f1 = make(mk)
    f1.cycle()
    mk.price = 3.0                                    # well past +$10: stake comes out, floor locks in
    f1.cycle()
    p1 = f1.book.open["GOOD"]
    assert p1.stake_recovered and p1.floor is not None and p1.cash_back > 0

    f2 = make(mk)
    p2 = f2.book.open["GOOD"]
    assert p2.stake_recovered and p2.floor == p1.floor and p2.peak_pnl == p1.peak_pnl
    assert p2.cash_back == p1.cash_back and p2.qty == p1.qty and len(p2.fills) == 2
    mk.price = 0.5                                    # falls back through the floor after the restart
    f2.cycle()
    assert not f2.book.open
    assert f2.book.closed[0].exit_reason.startswith("trailing floor")


def test_position_left_open_too_long_closes_on_restart(dirs):
    st, _ = dirs
    mk = Market()
    f1 = make(mk)
    f1.cycle()
    data = json.load(open(st / "positions.json"))
    data["positions"][0]["opened_ts"] -= DEFAULT.risk.max_hold_seconds + 1   # Mac was off for a while
    json.dump(data, open(st / "positions.json", "w"))
    f2 = make(mk)
    f2.cycle()
    assert not f2.book.open and f2.book.closed[0].exit_reason == "max hold time"


def test_corrupt_or_partial_positions_file_does_not_stop_startup(dirs):
    st, _ = dirs
    mk = Market()
    os.makedirs(st, exist_ok=True)
    (st / "positions.json").write_text("{not json")
    assert make(mk).restored == 0

    f1 = make(mk)
    f1.cycle()
    data = json.load(open(st / "positions.json"))
    good = data["positions"][0]
    data["positions"] = [{"symbol": "BROKEN"}, {**good, "symbol": "NOFILLS", "fills": []}, good]
    json.dump(data, open(st / "positions.json", "w"))
    f2 = make(mk)
    assert f2.restored == 1 and list(f2.book.open) == ["GOOD"]


def test_seen_tokens_and_brief_day_survive_restart(dirs):
    mk = Market()
    f1 = make(mk, tokens=[{"tokenAddress": "MintA", "_source": "profile"}])
    f1.last_brief_day = "2099-01-01"
    f1.cycle()
    mk.alive = False
    f1.cycle()                                        # rugged and closed
    assert not f1.book.open
    mk.alive = True
    f2 = make(mk, tokens=[{"tokenAddress": "MintA", "_source": "profile"}])
    assert "MintA" in f2.seen
    assert f2.last_brief_day == f1.last_brief_day != ""   # no second morning brief after a restart
    f2.cycle()
    assert not f2.book.open and f2.stats["screened"] == 0   # not re-screened or re-bought


def test_clean_shutdown_closes_priced_positions_and_keeps_unpriced(dirs):
    st, jr = dirs
    mk = Market()
    f1 = make(mk)
    f1.cycle()
    f1.shutdown()                                     # Ctrl+C / SIGTERM with a live price: closed and journaled
    assert not f1.book.open
    assert json.loads(open(jr / "firm_trades.jsonl").readline())["exit_reason"] == "firm shutdown"
    assert json.load(open(st / "positions.json"))["positions"] == []

    f2 = make(mk, tokens=[{"tokenAddress": "MintB", "_source": "profile"}])
    f2.cycle()
    f2.pair_fn = lambda a: (_ for _ in ()).throw(ConnectionError())
    f2.shutdown()                                     # no price available: do not invent a -$20 loss
    assert "GOOD" in f2.book.open
    f3 = make(mk)
    assert f3.restored == 1


# ---------- same-slot bundle detection ----------

def test_creator_profile_counts_same_slot_buys_after_launch(monkeypatch):
    import desk.data.onchain as oc
    txs = {
        "launch": _tx("dev", "M", {}, {"curvePDA": 900, "dev": 50, "sniper_in_tx": 10}),
        "same1": _tx("bundleA", "M", {"curvePDA": 900}, {"curvePDA": 870, "bundleA": 30}),
        "same2": _tx("dev", "M", {"curvePDA": 870, "dev": 50}, {"curvePDA": 850, "dev": 70}),   # dev buys again
        "same3": _tx("flipper", "M", {"curvePDA": 850}, {"curvePDA": 850}),                        # no net change
        "later": _tx("public", "M", {"curvePDA": 850}, {"curvePDA": 800, "public": 50}),          # next slot: not a bundle
    }
    sigs = [{"signature": "later", "slot": 101, "blockTime": 1_700_000_001},
            {"signature": "failed", "slot": 100, "blockTime": 1_700_000_000, "err": {"x": 1}},
            {"signature": "same3", "slot": 100, "blockTime": 1_700_000_000},
            {"signature": "same2", "slot": 100, "blockTime": 1_700_000_000},
            {"signature": "same1", "slot": 100, "blockTime": 1_700_000_000},
            {"signature": "launch", "slot": 100, "blockTime": 1_700_000_000}]
    fetched = []

    def rpc(method, params, retries=4):
        if method == "getSignaturesForAddress":
            return sigs if params[0] == "M" else [{"signature": "w", "slot": 1, "blockTime": 1_600_000_000}]
        if method == "getTransaction":
            fetched.append(params[0])
            return txs[params[0]]
        raise AssertionError(method)
    monkeypatch.setattr(oc, "_rpc", rpc)
    monkeypatch.setattr(oc, "pool_set", lambda owners, known_pools=(): {"curvePDA"})
    monkeypatch.setattr(oc, "_fast_ok", False)       # standard-RPC path (no Helius getTransactionsForAddress)
    cp = creator_profile("M", 1000)
    assert cp["creator"] == "dev"
    assert cp["creator_initial_buy_pct"] == pytest.approx(7.0)        # 50 in the launch tx + 20 same slot
    assert cp["bundled_wallets"] == 2 and cp["bundled_pct"] == pytest.approx(4.0)   # sniper_in_tx 10 + bundleA 30
    assert cp["bundled_in_launch_tx"] == 1 and cp["bundled_same_slot"] == 1
    assert cp["same_slot_txs"] == 3 and not cp["same_slot_truncated"]
    assert "later" not in fetched and "failed" not in fetched


def test_same_slot_buy_then_sell_is_not_counted_as_holding(monkeypatch):
    import desk.data.onchain as oc
    txs = {"launch": _tx("dev", "M", {}, {"curvePDA": 1000}),
           "buy": _tx("bot", "M", {"curvePDA": 1000}, {"curvePDA": 960, "bot": 40}),
           "sell": _tx("bot", "M", {"curvePDA": 960, "bot": 40}, {"curvePDA": 1000, "bot": 0})}
    sigs = [{"signature": k, "slot": 7, "blockTime": 1_700_000_000} for k in ("sell", "buy", "launch")]
    monkeypatch.setattr(oc, "_rpc", lambda m, p, retries=4: (sigs if p[0] == "M" else []) if m == "getSignaturesForAddress" else txs[p[0]])
    monkeypatch.setattr(oc, "pool_set", lambda owners, known_pools=(): {"curvePDA"})
    monkeypatch.setattr(oc, "_fast_ok", False)       # standard-RPC path (no Helius getTransactionsForAddress)
    cp = creator_profile("M", 1000)
    assert cp["bundled_wallets"] == 0 and cp["bundled_pct"] == 0 and cp["creator_initial_buy_pct"] == 0


# ---------- Phase 1 gate: hard-fail tokens traded ----------

def test_trade_rows_record_hard_fail_and_gate_counts_them(dirs):
    st, jr = dirs
    mk = Market()
    f = make(mk)
    f.cycle()
    assert f.meta["GOOD"]["hard_fail"] is False
    mk.alive = False
    f.cycle()
    row = json.loads(open(jr / "firm_trades.jsonl").readline())
    assert row["hard_fail"] is False
    g = dash.summary()["gate"]
    assert g["hard_fail_traded"] == 0 and g["hard_fail_ok"] and not g["passed"]

    with open(jr / "firm_trades.jsonl", "a") as fh:     # a hard-fail trade and an unauditable one
        fh.write(json.dumps({"closed_utc": "2026-11-15T00:00:00+00:00", "symbol": "BAD", "pnl_usd": 3, "hard_fail": True}) + "\n")
        fh.write(json.dumps({"closed_utc": "2026-11-15T00:00:00+00:00", "symbol": "OLD", "pnl_usd": 3}) + "\n")
    g = dash.summary()["gate"]
    assert g["hard_fail_traded"] == 1 and g["hard_fail_unaudited"] == 1 and not g["hard_fail_ok"]


def test_gate_needs_all_four():
    good = [{"pnl_usd": 1.0, "hard_fail": False}] * 200
    assert dash.phase1_gate(good, 50.0)["passed"]
    assert not dash.phase1_gate(good[:199], 50.0)["passed"]
    assert not dash.phase1_gate(good, 100.0)["passed"]
    assert not dash.phase1_gate([{"pnl_usd": -1.0, "hard_fail": False}] * 200, 50.0)["passed"]
    assert not dash.phase1_gate(good[:199] + [{"pnl_usd": 1.0, "hard_fail": True}], 50.0)["passed"]
    assert not dash.phase1_gate(good[:199] + [{"pnl_usd": 1.0}], 50.0)["passed"]


def test_hard_fail_token_is_never_traded(dirs):
    mk = Market()
    f = make(mk)
    f.snapshot_fn = lambda a, deep=True: TokenSnapshot(a, symbol="RUG", **{**GOOD, "mint_authority_revoked": False})
    f.cycle()
    assert not f.book.open and f.stats["approved"] == 0


# ---------- regression tests from real chain data (captured 15 Nov 2026) ----------

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "twert_launch.json")
TWERT = "8WvWwttzaLfW1nbjx6wmYL5jozWpvy95WktAg5cipump"
TWERT_CURVE = "5EnKvoJ3PfUv9FftkZU4mvzPHXWYWQ8MSU3GuqtiQ6Ni"


def _helius_rpc(calls):
    """A Helius-like RPC serving the real first 12 transactions of the token 'twert'."""
    txs = json.load(open(FIX))["txs"]

    def rpc(method, params, retries=4):
        calls.append((method, params))
        if method == "getTransactionsForAddress":
            addr, opts = params
            if addr != TWERT:                                  # creator wallet's first transaction
                return {"data": [{"signature": "first", "slot": 1, "blockTime": 1_794_170_000}]}
            assert opts["sortOrder"] == "asc"
            return {"data": txs[:opts["limit"]]}
        raise AssertionError(method)
    return rpc


def test_real_launch_same_slot_bundle_is_found(monkeypatch):
    """Live bug, 15 Nov 2026: this token showed 'couldn't measure creator' and a green verdict.
    Truth (checked on Solscan): creator AmTDr... bought 2M (0.2%) in the launch transaction, then
    HFKGP... bought 167,021,252 and 7kETf... bought 69.4M in the SAME slot: 23.65% of supply."""
    import desk.data.onchain as oc
    calls = []
    monkeypatch.setattr(oc, "_rpc", _helius_rpc(calls))
    monkeypatch.setattr(oc, "_fast_ok", True)
    monkeypatch.setattr(oc, "pool_set", lambda owners, known_pools=(): {TWERT_CURVE} & set(owners))
    cp = creator_profile(TWERT, 999_999_999.999999)
    assert cp["creator"] == "AmTDrHs26a8F3e7kvtXLgt3Fjgxp3aPyG2nj8C2tE3h1"
    assert cp["launch_signature"].startswith("34qzP2Hgf9dj")
    assert cp["creator_initial_buy_pct"] == pytest.approx(0.2, abs=1e-6)
    assert cp["bundled_wallets"] == 2 and cp["bundled_in_launch_tx"] == 0 and cp["bundled_same_slot"] == 2
    assert cp["bundled_pct"] == pytest.approx(23.646, abs=0.001)
    assert cp["same_slot_txs"] == 4 and not cp["same_slot_truncated"]     # 2 buys + 2 that moved no twert; 1 failed one skipped
    assert cp["creator_wallet_age_days"] > 6
    # the launch was found in ONE call, not by paging through thousands of signatures
    assert [m for m, _ in calls].count("getTransactionsForAddress") == 2 and "getSignaturesForAddress" not in [m for m, _ in calls]


def test_version_1_transactions_are_requested(monkeypatch):
    """Live bug, 15 Nov 2026: every flow check died with 'Transaction version (1) is not supported'."""
    import desk.data.onchain as oc
    seen = []

    def rpc(method, params, retries=4):
        seen.append((method, params))
        if method == "getTransactionsForAddress":
            raise RuntimeError({"code": -32601, "message": "Method not found"})
        if method == "getSignaturesForAddress":
            return [{"signature": "s1", "slot": 5}]
        return _tx("p", "M", {"POOL": 100}, {"POOL": 90, "buyer": 10})
    monkeypatch.setattr(oc, "_rpc", rpc)
    monkeypatch.setattr(oc, "_fast_ok", True)
    monkeypatch.setattr(oc, "pool_set", lambda owners, known_pools=(): {"POOL"})
    fs = oc.flow_stats("M", n=5)
    assert fs["unique_buyers"] == 1 and fs["sample_txs"] == 1          # fell back to the standard RPC path
    get_tx_opts = [p[1] for m, p in seen if m == "getTransaction"][0]
    assert get_tx_opts["maxSupportedTransactionVersion"] >= 1
    assert oc._fast_ok is False                                        # and remembers not to ask again


def test_opening_buy_uses_launch_supply_not_todays_burned_supply(monkeypatch):
    """Live: TOOLS creator bought 20M of the 1,000M minted = 2.00%. Against today's burned-down
    supply (947.4M) the old code said 2.11%."""
    import desk.data.onchain as oc
    launch = _tx("dev", "M", {}, {"curvePDA": 980_000_000, "dev": 20_000_000})
    monkeypatch.setattr(oc, "_rpc", lambda m, p, retries=4: [{"signature": "s", "slot": 1, "blockTime": 1}] if m == "getSignaturesForAddress" else launch)
    monkeypatch.setattr(oc, "_fast_ok", False)
    monkeypatch.setattr(oc, "pool_set", lambda owners, known_pools=(): {"curvePDA"})
    assert creator_profile("M", 947_437_182.15)["creator_initial_buy_pct"] == pytest.approx(2.0)
