"""Backtester for the structure setups. Reports the KPIs the doc tracks:
win rate, risk/reward, expected value per trade (in R), max drawdown, consistency.

Conservative by design: if stop and target are both inside one bar, the stop wins.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .structure import Candle, Setup


@dataclass
class TradeResult:
    setup: Setup
    exit_idx: int
    r: float
    outcome: str   # "target" | "stop" | "timeout"


@dataclass
class Report:
    trades: list[TradeResult] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        return sum(t.r > 0 for t in self.trades) / self.n if self.n else 0.0

    @property
    def ev_r(self) -> float:
        return sum(t.r for t in self.trades) / self.n if self.n else 0.0

    @property
    def total_r(self) -> float:
        return sum(t.r for t in self.trades)

    @property
    def max_drawdown_r(self) -> float:
        peak = eq = dd = 0.0
        for t in self.trades:
            eq += t.r
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        return dd

    @property
    def avg_rr(self) -> float:
        return sum(t.setup.rr for t in self.trades) / self.n if self.n else 0.0

    def summary(self, name: str = "") -> str:
        if not self.n:
            return f"{name}: no trades"
        return (f"{name}: {self.n} trades | win {self.win_rate:.0%} | avg planned RR {self.avg_rr:.2f} | "
                f"EV {self.ev_r:+.2f}R/trade | total {self.total_r:+.1f}R | max DD {self.max_drawdown_r:.1f}R")


def run(cs: list[Candle], setups: list[Setup], cost_pct: float = 0.05, max_bars: int = 72) -> Report:
    """cost_pct: round-trip spread+commission as % of price, charged against each trade in R."""
    rep = Report()
    busy_until = -1
    for s in setups:
        if s.idx <= busy_until:
            continue  # one position at a time
        risk = abs(s.entry - s.stop)
        cost_r = (s.entry * cost_pct / 100) / risk
        outcome, exit_idx, r = "timeout", min(len(cs) - 1, s.idx + max_bars), 0.0
        for j in range(s.idx + 1, min(len(cs), s.idx + 1 + max_bars)):
            c = cs[j]
            hit_stop = c.l <= s.stop if s.side == "long" else c.h >= s.stop
            hit_tgt = c.h >= s.target if s.side == "long" else c.l <= s.target
            if hit_stop:
                outcome, exit_idx, r = "stop", j, -1.0
                break
            if hit_tgt:
                outcome, exit_idx, r = "target", j, s.rr
                break
        if outcome == "timeout":
            px = cs[exit_idx].c
            r = ((px - s.entry) if s.side == "long" else (s.entry - px)) / risk
        rep.trades.append(TradeResult(s, exit_idx, r - cost_r, outcome))
        busy_until = exit_idx
    return rep
