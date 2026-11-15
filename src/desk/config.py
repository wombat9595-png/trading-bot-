"""Every tunable number in one place. Defaults come straight from Trading System Breakdown TM.

Change numbers here, not inside the logic. Anything marked VERIFY is an assumption
that must be checked against live fills during Phase 0.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RiskConfig:
    stake_usd: float = 20.0                 # "Foot in the Door": $20 per position
    stop_loss_usd: float = 7.5              # doc: $5-$10 hard floor. Midpoint.
    recover_stake_trigger_usd: float = 10.0  # once up this much, sell enough to pull the stake out
    scalp_take_profit_usd: float = 1.5      # doc: high-risk tokens get $1-$2 TP, full exit
    # Trailing floor ladder: (peak profit reached, profit floor locked). Doc: $5 -> $10 -> $20.
    trail_ladder: tuple[tuple[float, float], ...] = ((10.0, 5.0), (20.0, 10.0), (40.0, 20.0))
    max_hold_seconds: int = 15 * 60         # doc: rugs strike within minutes, time-box everything
    max_open_positions: int = 5
    daily_loss_limit_usd: float = 30.0      # not in doc; added. 4 stopped trades = desk stops for the day.


@dataclass(frozen=True)
class CostConfig:
    # VERIFY all three against real fills. These decide whether a $20 strategy can be profitable at all.
    slippage_pct: float = 1.5      # per side, small-cap memecoin
    venue_fee_pct: float = 1.0     # per side (Pump.fun / DEX swap fee)
    network_fee_usd: float = 0.02  # per transaction incl. priority fee


@dataclass(frozen=True)
class ScreenConfig:
    max_top10_pct: float = 30.0            # holder concentration hard fail
    max_creator_initial_buy_pct: float = 10.0  # red flag 1: massive green opening candle
    max_creator_prior_launches: int = 5    # serial launcher
    min_creator_wallet_age_days: float = 3.0
    max_single_wallet_trade_share: float = 0.15  # red flag 6: one wallet doing most of the buys
    max_wash_ratio: float = 0.35           # red flag 2: share of volume from round-tripping wallets
    min_unique_buyers: int = 15           # distinct buyers in the last-60-transaction sample
    min_liquidity_usd: float = 5_000.0     # graduated tokens only
    require_holder_data: bool = True     # no top-10 data -> no trade. Concentration is the core edge.
    high_risk_score: int = 40              # >= this -> scalp mode
    reject_score: int = 70                 # >= this -> no trade


@dataclass(frozen=True)
class EngineConfig:
    # Conviction weights (sum to 1). Safety dominates on purpose.
    w_safety: float = 0.5
    w_momentum: float = 0.3
    w_sentiment: float = 0.2
    min_conviction: float = 0.60
    min_momentum: float = 0.35     # gate: a 'safe' token nobody is buying is not a trade
    use_llm_review: bool = False   # Claude second opinion. Off by default: too slow for the entry path.
    llm_model: str = "claude-opus-5-5"


@dataclass(frozen=True)
class StructureConfig:
    swing_lookback: int = 2        # bars each side to confirm a swing high/low
    min_rr: float = 2.0            # skip setups whose target is < 2R away
    max_bars_after_sweep: int = 12  # BOS must confirm within N bars of the sweep


@dataclass(frozen=True)
class DeskConfig:
    """The agent desks from TSB section 4 and how much of the book each may use."""
    foot_in_door_max_open: int = 4         # $20 longs across graduated tokens
    verification_max_open: int = 2         # event trades on fresh DexScreener verification
    verification_max_age_min: float = 180  # only tokens verified while young
    verification_fade_ratio: float = 0.45  # exit when 5m buy share falls below this
    rug_liquidity_drop_pct: float = 50.0   # live rug watch: LP down this much since entry -> dump
    brief_hour_local: int = 8              # News Desk morning briefing
    poll_seconds: int = 20


@dataclass(frozen=True)
class Settings:
    risk: RiskConfig = field(default_factory=RiskConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    screen: ScreenConfig = field(default_factory=ScreenConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    structure: StructureConfig = field(default_factory=StructureConfig)
    desks: DeskConfig = field(default_factory=DeskConfig)
    milestones_usd: tuple[float, ...] = (100, 500, 1_000, 5_000, 10_000, 50_000)


DEFAULT = Settings()
