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
    monkeypatch.setattr(oc, "program_owned_set", lambda owners: {"curvePDA"})
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
