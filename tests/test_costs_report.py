import json
from datetime import datetime, timezone

import pytest

import desk.dashboard as dash
import desk.firm as firm_mod
import desk.patterns as patterns
import desk.report as report
from desk import costs
from desk.config import DEFAULT, CostConfig
from desk.data.jupiter import round_trip_cost

# Quote pair with the numbers measured live on 15 Nov 2026 for a $20 round trip on GETAJOB (Pump.fun AMM,
# $56k pool: 2.11% round trip), reduced to the fields the code reads and with the token amount rounded.
# priceImpactPct ~1.05% on a pool where $20 moves price 0.07%:
# Jupiter's "impact" includes the pool fee, which is why the split uses pool depth instead.
BUY = {"inAmount": "272739670", "outAmount": "1000000000", "priceImpactPct": "0.0105",
       "routePlan": [{"swapInfo": {"label": "Pump.fun Amm"}}]}
SELL = {"inAmount": "1000000000", "outAmount": "266984863", "priceImpactPct": "0.0106",
        "routePlan": [{"swapInfo": {"label": "Pump.fun Amm"}}]}


def test_round_trip_cost_splits_fee_from_price_impact():
    c = round_trip_cost(BUY, SELL, 20.0, 56_341)
    assert c["round_trip_pct"] == pytest.approx(2.11, abs=0.01)
    assert c["total_pct"] == pytest.approx(1.06, abs=0.01)
    assert c["slippage_pct"] == pytest.approx(0.071, abs=0.001)          # 20 / (56341 / 2)
    assert c["fee_pct"] == pytest.approx(0.99, abs=0.01)
    assert c["slippage_pct"] + c["fee_pct"] == pytest.approx(c["total_pct"])
    assert c["venues"] == ["Pump.fun Amm"]
    # unknown liquidity: everything is booked as fee, nothing is lost
    assert round_trip_cost(BUY, SELL, 20.0, None)["fee_pct"] == pytest.approx(c["total_pct"])
    with pytest.raises(ValueError):
        round_trip_cost(BUY, {**SELL, "outAmount": "0"}, 20.0, 1000)


def _data(slips, fees, net=0.0015):
    return {"usd": 20.0, "sol_price": 73.0, "errors": [], "network_fee_usd": net, "network_fee_how": "test",
            "rows": [{"mint": f"m{i}", "symbol": f"T{i}", "liquidity_usd": 10_000, "round_trip_pct": 2 * (s + f),
                      "total_pct": s + f, "slippage_pct": s, "fee_pct": f, "venues": ["Pump.fun Amm"]}
                     for i, (s, f) in enumerate(zip(slips, fees))]}


def test_proposal_never_lowers_slippage_or_network_fee_from_quotes():
    cur = CostConfig(slippage_pct=1.5, venue_fee_pct=1.0, network_fee_usd=0.02)
    new = costs.propose(_data([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.2, 0.2], [1.0, 1.1, 1.17, 1.2, 1.21, 1.28, 1.1, 1.21]), cur)
    assert new.slippage_pct == 1.5 and new.network_fee_usd == 0.02       # floor: quotes are a best case
    assert new.venue_fee_pct == 1.25                                     # p75 1.21 -> rounded up
    worse = costs.propose(_data([2.0] * 6, [1.0] * 6, net=0.05), cur)
    assert worse.slippage_pct == 2.0 and worse.network_fee_usd == 0.05   # but they can raise them
    assert costs.propose(_data([0.1] * 4, [1.0] * 4), cur) is None       # too few quotes: no proposal


def test_costs_report_shows_before_and_after():
    cur = CostConfig(slippage_pct=1.5, venue_fee_pct=1.0, network_fee_usd=0.02)
    text = costs.report(_data([0.3] * 6, [1.21] * 6), cur)
    assert "venue_fee_pct" in text and "1.25" in text and "Not applied" in text
    assert costs.round_trip_usd(cur, 20.0) == pytest.approx(1.02, abs=0.01)


@pytest.fixture
def journal(tmp_path, monkeypatch):
    jr = tmp_path / "journal"
    jr.mkdir()
    for m in (firm_mod, dash, report):
        monkeypatch.setattr(m, "JOURNAL", str(jr))
    monkeypatch.setattr(patterns, "TRADES", str(jr / "firm_trades.jsonl"))
    return jr


def _trade(pnl, **kw):
    return {"closed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "symbol": "X", "desk": "foot_in_door",
            "mode": "standard", "conviction": 0.75, "risk_score": 10, "exit_reason": "stop-loss", "hold_s": 60,
            "pnl_usd": pnl, "hard_fail": False, **kw}


def test_report_has_every_section_and_real_numbers(journal):
    with open(journal / "firm_trades.jsonl", "w") as fh:
        for p in (5, -7.5, 2, -1):
            fh.write(json.dumps(_trade(p)) + "\n")
    now = datetime.now(timezone.utc)
    with open(journal / f"decisions_{now:%Y%m%d}.jsonl", "w") as fh:
        for reasons in (["top-10 hold 62% of supply: you are exit liquidity"], ["top-10 hold 71% of supply: you are exit liquidity"]):
            fh.write(json.dumps({"ts": now.isoformat(timespec="seconds"), "trade": False, "reasons": reasons}) + "\n")
        fh.write(json.dumps({"ts": now.isoformat(timespec="seconds"), "trade": True, "reasons": []}) + "\n")
    text = report.build(tracker_text="RUG-CATCH SCOREBOARD stub")
    assert "Last 24h: 4 trades, 2 winners (50%), P&L $-1.50" in text
    assert "All time: 4 trades, win rate 50%, P&L $-1.50" in text and "max drawdown $7.50" in text
    assert "Screened 3 tokens, rejected 2 (67%)" in text
    assert "2x top-N hold N of supply: you are exit liquidity" in text       # same cause grouped together
    assert "PHASE 1 GATE: closed" in text and "4/200" in text and "0 traded" in text
    assert "PATTERN FINDER: 4 closed trades" in text and "RUG-CATCH SCOREBOARD stub" in text
    assert "ONE CHANGE WORTH TESTING NEXT (not applied)" in text and "None yet" in text


def test_report_with_empty_journal(journal):
    text = report.build(tracker_text="none")
    assert "no closed trades yet" in text and "0/200" in text


def test_suggestion_is_one_tightening_change_backed_by_data():
    assert "None yet" in report.suggest([_trade(-1)] * 29)
    assert report.suggest([_trade(1)] * 40).startswith("None.")
    # scalp mode loses a little, low conviction loses the most money: exactly one suggestion, the biggest leak
    trades = [_trade(-1, mode="scalp", conviction=0.9)] * 30 + [_trade(-3, conviction=0.65)] * 30 + [_trade(4, conviction=0.9)] * 30
    s = report.suggest(trades)
    assert "min_conviction 0.6 -> 0.70" in s and "reject_score" not in s and "30 trades averaging $-3.00" in s


def test_suggest_never_changes_config():
    before = DEFAULT
    report.suggest([_trade(-3, conviction=0.65)] * 60)
    assert DEFAULT is before and DEFAULT.engine.min_conviction == 0.60


def test_chunks_fit_telegram():
    text = "\n".join(f"line {i} " + "x" * 80 for i in range(200)) + "\n" + "y" * 9000
    parts = report.chunks(text)
    assert all(len(p) <= report.TG_LIMIT for p in parts)
    assert "".join(parts).replace("\n", "") == text.replace("\n", "")


def test_tracker_judges_each_token_once(monkeypatch, tmp_path):
    import desk.tracker as tr
    monkeypatch.setattr(tr, "JOURNAL", str(tmp_path))
    old = "2026-01-01T00:00:00+00:00"
    rows = [{"ts": old, "address": "A", "price_usd": 1.0, "mode": "reject", "risk_score": 80},
            {"ts": old, "address": "A", "price_usd": 0.5, "mode": "reject", "risk_score": 80},
            {"ts": old, "address": "B", "price_usd": 1.0, "mode": "standard", "risk_score": 10},
            {"ts": old, "address": "C", "price_usd": 1.0, "mode": "standard", "risk_score": 10}]
    (tmp_path / "decisions_20260101.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    def price(addr):
        if addr == "C":
            raise ConnectionError()
        return {"A": 0.05, "B": 1.2}[addr]
    monkeypatch.setattr(tr.dx, "price", price)
    monkeypatch.setattr(tr.time, "sleep", lambda s: None)
    out = tr.run(24)
    assert "flagged : 1/1 crashed 90%+ (100%)" in out          # A counted once, against its first price
    assert "passed  : 0/1 crashed 90%+ (0%)" in out            # C had no answer: left out, not called a crash


def test_archived_trades_are_left_out_of_every_stat(journal):
    """Trades moved to journal/archive/ (e.g. the aborted run of 15 Nov 2026) are kept on disk
    but must not reach the gate, the report, the dashboard or Pattern Finder."""
    (journal / "archive").mkdir()
    (journal / "archive" / "aborted_run_20261115_trades.jsonl").write_text(json.dumps(_trade(-7.41)) + "\n")
    (journal / "firm_trades.jsonl").write_text(json.dumps(_trade(2.0)) + "\n")
    sm = dash.summary()
    assert sm["n"] == 1 and sm["total"] == 2.0 and sm["gate"]["trades_needed"] == 199
    assert len(patterns.load()) == 1
    text = report.build(tracker_text="x")
    assert "All time: 1 trades" in text and "7.41" not in text
