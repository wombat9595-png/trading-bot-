import pytest

from desk.config import CostConfig, RiskConfig
from desk.risk import Book, Position, buy_cost, sell_proceeds

FREE = CostConfig(slippage_pct=0, venue_fee_pct=0, network_fee_usd=0)
R = RiskConfig()


def pos(mode="standard", costs=FREE):
    return Position.open("T", 0, 1.0, mode, R, costs)  # $20 stake = 20 tokens at $1 with no costs


def test_no_stop_above_threshold():
    p = pos()
    assert p.on_tick(1, 0.70) is None and not p.closed          # -$6, inside the $7.50 stop


def test_stop_loss():
    p = pos()
    assert p.on_tick(1, 0.62) == "stop-loss"                    # -$7.60
    assert p.realised_pnl == pytest.approx(-7.6)


def test_rug_watch_overrides_everything():
    p = pos()
    assert p.on_tick(1, 1.5, rug_alert="LP pulled").startswith("RUG WATCH")
    assert p.closed


def test_max_hold():
    p = pos()
    assert p.on_tick(R.max_hold_seconds, 1.01) == "max hold time"


def test_scalp_takes_quick_profit():
    p = pos("scalp")
    assert p.on_tick(1, 1.08) == "scalp take-profit"            # +$1.60
    assert p.realised_pnl == pytest.approx(1.6)


def test_recover_stake_then_ride_house_money():
    p = pos()
    assert "recovered stake" in p.on_tick(1, 1.5)               # +$10 -> sell $20 worth
    assert p.cash_back == pytest.approx(20.0)
    assert p.qty == pytest.approx(20 - 20 / 1.5)
    # remaining position can no longer lose the stake
    p.on_tick(2, 0.01)
    assert p.realised_pnl >= -0.01 or not p.closed


def test_trailing_floor_ratchets_and_exits():
    p = pos()
    p.on_tick(1, 1.5)       # recover stake, pnl +10 -> floor $5
    assert p.floor == 5
    p.on_tick(2, 4.0)       # big run: remaining 6.67 tokens * 4 = 26.7 -> pnl +26.7 -> floor $10
    assert p.floor == 10
    p.on_tick(3, 7.0)       # 46.7 -> floor $20
    assert p.floor == 20
    assert p.on_tick(4, 2.9).startswith("trailing floor")      # pnl 19.3 <= 20
    assert p.realised_pnl == pytest.approx(6.6667 * 2.9, rel=1e-3)


def test_costs_make_flat_price_a_loss():
    c = CostConfig()
    p = Position.open("T", 0, 1.0, "standard", R, c)
    assert p.pnl_at(1.0) < -0.9                                 # ~5% round trip on $20 = ~$1


def test_round_trip_cost_math():
    c = CostConfig(slippage_pct=1, venue_fee_pct=1, network_fee_usd=0.02)
    qty, _ = buy_cost(20, 1.0, c)
    back = sell_proceeds(qty, 1.0, c)
    assert 19.1 < back < 19.3


def test_book_daily_loss_limit():
    b = Book(risk=R)
    assert b.can_open()[0]
    assert not b.can_open(day_pnl=-30)[0]
