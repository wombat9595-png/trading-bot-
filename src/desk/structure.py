"""Market-structure engine: TJR Bootcamp + TradesbySci Crash Course turned into code.

What it encodes (and where it came from):
  - Swing highs/lows, labelled HH / HL / LH / LL ............ Sci Day 1-3, TJR Day 4
  - Trend = HH+HL (up) or LH+LL (down), else range .......... Sci Day 1, TJR Day 4
  - BOS only counts on a candle CLOSE beyond the swing ..... TJR Day 6
  - CHoCH = first close against the prevailing trend ....... Candlestick Terms
  - Liquidity sweep = wick through a swing, close back inside  TJR Day 8/10/12
  - FVG = 3-candle imbalance ................................ Candlestick Terms
  - Setup: sweep -> structure break -> target next liquidity  TJR Day 12
  - Filter: higher timeframe must agree ("all timeframes match")  Sci Day 2/4

No look-ahead: a swing at bar i is only usable from bar i + lookback, because that is
when it is actually confirmed on a live chart.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import StructureConfig


@dataclass(frozen=True)
class Candle:
    ts: float
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0


@dataclass(frozen=True)
class Swing:
    idx: int
    confirmed_at: int
    kind: str      # "high" | "low"
    price: float
    label: str     # HH / LH / HL / LL / H / L (first of its kind)


@dataclass(frozen=True)
class Event:
    idx: int
    kind: str      # BOS_UP, BOS_DOWN, CHOCH_UP, CHOCH_DOWN, SWEEP_SSL, SWEEP_BSL, FVG_UP, FVG_DOWN
    level: float


@dataclass(frozen=True)
class Setup:
    idx: int               # bar the signal fires on (enter at its close)
    side: str              # "long" | "short"
    entry: float
    stop: float
    target: float
    sweep_idx: int
    reason: str

    @property
    def rr(self) -> float:
        risk = abs(self.entry - self.stop)
        return abs(self.target - self.entry) / risk if risk else 0.0


def find_swings(cs: list[Candle], n: int = 2) -> list[Swing]:
    out: list[Swing] = []
    last_h = last_l = None
    for i in range(n, len(cs) - n):
        hi = cs[i].h
        lo = cs[i].l
        if hi > max(c.h for c in cs[i - n:i]) and hi >= max(c.h for c in cs[i + 1:i + n + 1]):
            label = "H" if last_h is None else ("HH" if hi > last_h else "LH")
            out.append(Swing(i, i + n, "high", hi, label))
            last_h = hi
        if lo < min(c.l for c in cs[i - n:i]) and lo <= min(c.l for c in cs[i + 1:i + n + 1]):
            label = "L" if last_l is None else ("HL" if lo > last_l else "LL")
            out.append(Swing(i, i + n, "low", lo, label))
            last_l = lo
    return out


def trend_from(swings: list[Swing]) -> str:
    """'up', 'down' or 'range' from the latest high label and latest low label."""
    hi = next((s.label for s in reversed(swings) if s.kind == "high"), None)
    lo = next((s.label for s in reversed(swings) if s.kind == "low"), None)
    if hi == "HH" and lo == "HL":
        return "up"
    if hi == "LH" and lo == "LL":
        return "down"
    return "range"


def trend_at(cs: list[Candle], idx: int, n: int = 2) -> str:
    """Trend using only swings confirmed by bar idx."""
    sw = [s for s in find_swings(cs[: idx + 1], n) if s.confirmed_at <= idx]
    return trend_from(sw)


def fvgs(cs: list[Candle]) -> list[Event]:
    out = []
    for i in range(2, len(cs)):
        if cs[i].l > cs[i - 2].h:
            out.append(Event(i, "FVG_UP", (cs[i].l + cs[i - 2].h) / 2))
        elif cs[i].h < cs[i - 2].l:
            out.append(Event(i, "FVG_DOWN", (cs[i].h + cs[i - 2].l) / 2))
    return out


def events(cs: list[Candle], n: int = 2) -> list[Event]:
    """Walk bars in time order; emit BOS/CHoCH/sweeps using only confirmed swings."""
    swings = find_swings(cs, n)
    out: list[Event] = []
    active_high: Swing | None = None
    active_low: Swing | None = None
    trend = "range"
    known: list[Swing] = []
    si = 0
    for i, c in enumerate(cs):
        while si < len(swings) and swings[si].confirmed_at <= i:
            s = swings[si]
            known.append(s)
            if s.kind == "high":
                active_high = s
            else:
                active_low = s
            si += 1
        if active_high and i > active_high.idx:
            if c.c > active_high.price:
                out.append(Event(i, "BOS_UP" if trend == "up" else "CHOCH_UP", active_high.price))
                trend = "up"
                active_high = None
            elif c.h > active_high.price:
                out.append(Event(i, "SWEEP_BSL", active_high.price))
        if active_low and i > active_low.idx:
            if c.c < active_low.price:
                out.append(Event(i, "BOS_DOWN" if trend == "down" else "CHOCH_DOWN", active_low.price))
                trend = "down"
                active_low = None
            elif c.l < active_low.price:
                out.append(Event(i, "SWEEP_SSL", active_low.price))
    return out


def resample(cs: list[Candle], seconds: int) -> list[Candle]:
    out: list[Candle] = []
    bucket: list[Candle] = []
    key = None
    for c in cs:
        k = int(c.ts // seconds)
        if key is not None and k != key:
            out.append(_merge(bucket))
            bucket = []
        key = k
        bucket.append(c)
    if bucket:
        out.append(_merge(bucket))
    return out


def _merge(b: list[Candle]) -> Candle:
    return Candle(b[0].ts, b[0].o, max(x.h for x in b), min(x.l for x in b), b[-1].c, sum(x.v for x in b))


def find_setups(cs: list[Candle], cfg: StructureConfig | None = None,
                htf: list[Candle] | None = None, htf_seconds: int = 4 * 3600) -> list[Setup]:
    """TJR Day 12 model: liquidity sweep -> structure break in the new direction -> target next liquidity.

    htf: optional higher-timeframe candles. If given, longs need HTF trend != down and
    shorts need HTF trend != up (only HTF bars fully closed before the signal are used).
    """
    cfg = cfg or StructureConfig()
    n = cfg.swing_lookback
    swings = find_swings(cs, n)
    evs = events(cs, n)
    setups: list[Setup] = []
    last_sweep: dict[str, Event] = {}
    used_sweeps: set[int] = set()

    for e in evs:
        if e.kind in ("SWEEP_SSL", "SWEEP_BSL"):
            last_sweep[e.kind] = e
            continue
        if e.kind in ("BOS_UP", "CHOCH_UP"):
            side, sw_kind = "long", "SWEEP_SSL"
        elif e.kind in ("BOS_DOWN", "CHOCH_DOWN"):
            side, sw_kind = "short", "SWEEP_BSL"
        else:
            continue
        sw = last_sweep.get(sw_kind)
        if not sw or sw.idx in used_sweeps or e.idx - sw.idx > cfg.max_bars_after_sweep:
            continue
        i = e.idx
        entry = cs[i].c
        if side == "long":
            stop = min(c.l for c in cs[sw.idx:i + 1])
            pool = [s.price for s in swings if s.kind == "high" and s.confirmed_at <= i and s.price > entry]
            # TJR: aim for the next prominent level; skip ones too close to pay 2R
            pool = sorted(p for p in pool if (p - entry) >= cfg.min_rr * (entry - stop))
            target = pool[0] if pool else None
        else:
            stop = max(c.h for c in cs[sw.idx:i + 1])
            pool = sorted((s.price for s in swings if s.kind == "low" and s.confirmed_at <= i
                           and s.price < entry and (entry - s.price) >= cfg.min_rr * (stop - entry)), reverse=True)
            target = pool[0] if pool else None
        if target is None or stop == entry:
            continue
        if htf is not None:
            closed = [h for h in htf if h.ts + htf_seconds <= cs[i].ts + _bar_seconds(cs)]
            t = trend_from(find_swings(closed, n)) if len(closed) > 2 * n + 1 else "range"
            if (side == "long" and t == "down") or (side == "short" and t == "up"):
                continue
            reason_htf = f"HTF {t}"
        else:
            reason_htf = "no HTF filter"
        used_sweeps.add(sw.idx)
        setups.append(Setup(i, side, entry, stop, target, sw.idx,
                            f"{sw.kind} @ {sw.level:.4f} -> {e.kind} @ {e.level:.4f}; {reason_htf}"))
    return setups


def _bar_seconds(cs: list[Candle]) -> float:
    return cs[1].ts - cs[0].ts if len(cs) > 1 else 3600
