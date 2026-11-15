from desk.backtest import run
from desk.structure import Candle, events, find_setups, find_swings, resample, trend_from
from desk.config import StructureConfig


def bars(closes, wick=0.2):
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append(Candle(i * 3600.0, o, max(o, c) + wick, min(o, c) - wick, c))
        prev = c
    return out


UP = [10, 11, 12, 13, 12, 11.5, 12.5, 14, 15, 16, 15, 14.5, 15.5, 17, 18, 19, 18, 17.5, 18.5, 20, 21]
DOWN = [21 - (x - 10) for x in UP]


def test_uptrend_labels_hh_hl():
    sw = find_swings(bars(UP))
    assert trend_from(sw) == "up"
    assert {"HH", "HL"} <= {s.label for s in sw}


def test_downtrend_labels_lh_ll():
    assert trend_from(find_swings(bars(DOWN))) == "down"


def test_bos_requires_close_not_wick():
    cs = bars([10, 11, 12, 11, 10, 11, 11.9, 11.5, 11.0])
    # 12.2 is the swing high (12 + wick). Wicks reach 12.1 at most: no close above -> no BOS
    assert not [e for e in events(cs) if e.kind in ("BOS_UP", "CHOCH_UP")]
    cs2 = bars([10, 11, 12, 11, 10, 11, 12.5, 13])
    assert [e for e in events(cs2) if e.kind in ("BOS_UP", "CHOCH_UP")]


def test_sweep_detected():
    # swing low at 9.8 (10 - wick), then a candle wicks below it but closes back above
    cs = bars([12, 11, 10, 11, 12, 11.5, 11, 10.5])
    cs.append(Candle(len(cs) * 3600.0, 10.5, 10.7, 9.5, 10.4))
    assert any(e.kind == "SWEEP_SSL" for e in events(cs))


def test_sweep_then_bos_gives_long_setup_with_min_rr():
    closes = [20, 19, 18, 19, 20, 19, 17, 15, 14, 15, 16, 15.5, 15]
    cs = bars(closes)
    cs.append(Candle(len(cs) * 3600.0, 15, 15.1, 13.0, 14.9))   # sweep the 13.8 low (SSL)
    for c in (15.5, 16.2, 17.0):
        cs.append(Candle(len(cs) * 3600.0, cs[-1].c, c + 0.2, cs[-1].c - 0.2, c))  # break 16.2 high
    for c in (17.5, 18.5, 20.5, 21):
        cs.append(Candle(len(cs) * 3600.0, cs[-1].c, c + 0.2, cs[-1].c - 0.2, c))
    setups = find_setups(cs, StructureConfig(min_rr=0.75))
    longs = [s for s in setups if s.side == "long"]
    assert longs, setups
    s = longs[0]
    assert s.stop <= 13.0 and s.target > s.entry and s.rr >= 0.75
    assert s.target == 20.2                                  # next buy-side liquidity
    assert not find_setups(cs, StructureConfig(min_rr=2.0))  # 0.8R target is skipped at the 2R default
    rep = run(cs, [s], cost_pct=0)
    assert rep.trades[0].outcome == "target"


def test_resample_4h():
    cs = bars(list(range(1, 9)))
    four = resample(cs, 4 * 3600)
    assert len(four) == 2 and four[0].o == cs[0].o and four[0].c == cs[3].c
