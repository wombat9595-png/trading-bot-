"""Position lifecycle + paper fills. Implements section 6 (Risk Management Framework).

Every P&L number here is REALISED at the executable price after slippage, venue fee and
network fee, as the doc requires. A position's "value" is what you would get if you sold
right now, never the chart price.

Rule order on every price tick (first match wins):
  1. rug watch      -> dump everything
  2. max hold time  -> dump everything
  3. stop-loss      -> dump everything
  4. scalp TP       -> dump everything (scalp mode only)
  5. recover stake  -> sell enough to pull the $ stake out; rest rides risk-free
  6. trailing floor -> ratchets $5 -> $10 -> $20; dump if P&L falls back to the floor
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import CostConfig, RiskConfig


@dataclass
class Fill:
    ts: float
    side: str          # "buy" | "sell"
    qty: float
    price: float       # quoted market price
    cash: float        # +cash received on sell, -cash spent on buy, all costs included
    reason: str


def buy_cost(usd: float, price: float, c: CostConfig) -> tuple[float, float]:
    """Spend `usd` (incl. all costs). Returns (qty received, effective price)."""
    spend = usd - c.network_fee_usd
    eff = price * (1 + c.slippage_pct / 100)
    qty = spend * (1 - c.venue_fee_pct / 100) / eff
    return qty, eff


def sell_proceeds(qty: float, price: float, c: CostConfig) -> float:
    eff = price * (1 - c.slippage_pct / 100)
    return max(0.0, qty * eff * (1 - c.venue_fee_pct / 100) - c.network_fee_usd)


@dataclass
class Position:
    symbol: str
    opened_ts: float
    stake: float
    qty: float
    mode: str                         # "standard" | "scalp"
    risk: RiskConfig
    costs: CostConfig
    cash_back: float = 0.0            # realised cash from partial sells
    stake_recovered: bool = False
    peak_pnl: float = 0.0
    floor: float | None = None
    closed: bool = False
    exit_reason: str = ""
    fills: list[Fill] = field(default_factory=list)

    @classmethod
    def open(cls, symbol: str, ts: float, price: float, mode: str,
             risk: RiskConfig | None = None, costs: CostConfig | None = None) -> "Position":
        risk = risk or RiskConfig()
        costs = costs or CostConfig()
        qty, _ = buy_cost(risk.stake_usd, price, costs)
        p = cls(symbol, ts, risk.stake_usd, qty, mode, risk, costs)
        p.fills.append(Fill(ts, "buy", qty, price, -risk.stake_usd, f"entry ({mode})"))
        return p

    def pnl_at(self, price: float) -> float:
        """Total realised-if-closed-now P&L."""
        return self.cash_back + sell_proceeds(self.qty, price, self.costs) - self.stake

    def _sell(self, ts: float, qty: float, price: float, reason: str) -> None:
        cash = sell_proceeds(qty, price, self.costs)
        self.qty -= qty
        self.cash_back += cash
        self.fills.append(Fill(ts, "sell", qty, price, cash, reason))

    def _close(self, ts: float, price: float, reason: str) -> None:
        if self.qty > 0:
            self._sell(ts, self.qty, price, reason)
        self.closed = True
        self.exit_reason = reason

    @property
    def realised_pnl(self) -> float:
        return self.cash_back - self.stake

    def on_tick(self, ts: float, price: float, rug_alert: str | None = None) -> str | None:
        """Feed one price observation. Returns an action label if something happened."""
        if self.closed:
            return None
        r = self.risk
        if rug_alert:
            self._close(ts, price, f"RUG WATCH: {rug_alert}")
            return self.exit_reason
        if ts - self.opened_ts >= r.max_hold_seconds:
            self._close(ts, price, "max hold time")
            return self.exit_reason

        pnl = self.pnl_at(price)
        if pnl <= -r.stop_loss_usd:
            self._close(ts, price, "stop-loss")
            return self.exit_reason
        if self.mode == "scalp" and pnl >= r.scalp_take_profit_usd:
            self._close(ts, price, "scalp take-profit")
            return self.exit_reason

        action = None
        if not self.stake_recovered and pnl >= r.recover_stake_trigger_usd:
            # Sell just enough tokens that cash back == stake.
            c = self.costs
            per_token = price * (1 - c.slippage_pct / 100) * (1 - c.venue_fee_pct / 100)
            need = self.stake - self.cash_back + c.network_fee_usd
            qty = min(self.qty, need / per_token) if per_token > 0 else self.qty
            self._sell(ts, qty, price, "recover stake")
            self.stake_recovered = True
            action = "recovered stake; remainder is house money"
            pnl = self.pnl_at(price)

        self.peak_pnl = max(self.peak_pnl, pnl)
        for trigger, locked in r.trail_ladder:
            if self.peak_pnl >= trigger:
                self.floor = max(self.floor or locked, locked)
        if self.floor is not None and pnl <= self.floor:
            self._close(ts, price, f"trailing floor ${self.floor:.0f}")
            return self.exit_reason
        if self.qty <= 1e-12:
            self.closed = True
            self.exit_reason = self.exit_reason or "fully sold"
        return action


@dataclass
class Book:
    """Desk-level guardrails across positions."""
    risk: RiskConfig = field(default_factory=RiskConfig)
    open: dict[str, Position] = field(default_factory=dict)
    closed: list[Position] = field(default_factory=list)

    @property
    def realised(self) -> float:
        return sum(p.realised_pnl for p in self.closed)

    def can_open(self, day_pnl: float | None = None) -> tuple[bool, str]:
        day = self.realised if day_pnl is None else day_pnl
        if day <= -self.risk.daily_loss_limit_usd:
            return False, f"daily loss limit hit (${day:.2f})"
        if len(self.open) >= self.risk.max_open_positions:
            return False, "max open positions"
        return True, ""

    def settle(self) -> list[Position]:
        done = [k for k, p in self.open.items() if p.closed]
        out = [self.open.pop(k) for k in done]
        self.closed.extend(out)
        return out
