"""Holder Scout: the six red-flag rug screen from Trading System Breakdown TM, section 5.

Pure function: snapshot in, verdict out. Data adapters (DexScreener / Solana RPC / Helius)
fill the snapshot; anything they could not measure stays None and is scored as a penalty,
never as a pass. Unknown is not safe.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import ScreenConfig


@dataclass
class TokenSnapshot:
    address: str
    symbol: str = ""
    # Contract (red flag 4)
    mint_authority_revoked: bool | None = None
    freeze_authority_revoked: bool | None = None
    graduated: bool | None = None            # left the bonding curve onto an open DEX
    liquidity_usd: float | None = None
    # Holders (red flag 3)
    top10_pct: float | None = None           # % of supply in top 10 wallets, excl. LP / bonding curve
    # Creator (red flags 1 and 5)
    creator_initial_buy_pct: float | None = None
    creator_wallet_age_days: float | None = None
    creator_prior_launches: int | None = None
    creator_prior_rugs: int | None = None
    # Flow (red flags 2 and 6)
    unique_buyers: int | None = None
    max_single_wallet_trade_share: float | None = None
    wash_ratio: float | None = None
    # Social (red flag 6)
    has_x_account: bool | None = None
    # Momentum inputs (not safety, used by the engine)
    buys_5m: int | None = None
    sells_5m: int | None = None
    price_change_5m_pct: float | None = None
    age_minutes: float | None = None
    price_usd: float | None = None
    # Raw forensics behind the numbers above (creator, bundle wallets, sample size). Display only.
    details: dict = field(default_factory=dict)


@dataclass
class ScreenResult:
    risk_score: int                          # 0 (clean) .. 100 (certain rug)
    hard_fail: bool
    flags: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)

    @property
    def safety(self) -> float:
        """0..1, higher is safer. Used by the conviction engine."""
        return 0.0 if self.hard_fail else max(0.0, 1.0 - self.risk_score / 100)

    def mode(self, cfg: ScreenConfig) -> str:
        if self.hard_fail or self.risk_score >= cfg.reject_score:
            return "reject"
        if self.risk_score >= cfg.high_risk_score:
            return "scalp"
        return "standard"


UNKNOWN_PENALTY = 6


def screen(t: TokenSnapshot, cfg: ScreenConfig | None = None) -> ScreenResult:
    cfg = cfg or ScreenConfig()
    score = 0
    hard = False
    flags: list[str] = []
    unknowns: list[str] = []

    def unknown(name: str) -> None:
        nonlocal score
        unknowns.append(name)
        score += UNKNOWN_PENALTY

    # 4. Contract risk: any of these alone is an instant no.
    for name, val in (("mint_authority", t.mint_authority_revoked), ("freeze_authority", t.freeze_authority_revoked)):
        if val is None:
            unknown(name)
        elif not val:
            hard = True
            flags.append(f"{name} NOT revoked: creator can mint or freeze your tokens")
    if t.graduated is False:
        score += 15
        flags.append("still on bonding curve: no open-market liquidity yet")
    if t.liquidity_usd is None:
        if t.graduated is not False:
            unknown("liquidity")
    elif t.liquidity_usd < cfg.min_liquidity_usd:
        score += 20
        flags.append(f"thin liquidity ${t.liquidity_usd:,.0f}: your own exit will move price")

    # 3. Holder concentration
    if t.top10_pct is None:
        unknown("top10_pct")
        if cfg.require_holder_data:
            hard = True
            flags.append("holder distribution unknown: cannot rule out exit-liquidity trap")
    elif t.top10_pct > cfg.max_top10_pct * 1.5:
        hard = True
        flags.append(f"top-10 hold {t.top10_pct:.0f}% of supply: you are exit liquidity")
    elif t.top10_pct > cfg.max_top10_pct:
        score += 25
        flags.append(f"top-10 hold {t.top10_pct:.0f}% of supply")

    # 1. Insider accumulation
    if t.creator_initial_buy_pct is None:
        unknown("creator_initial_buy")
    elif t.creator_initial_buy_pct > cfg.max_creator_initial_buy_pct:
        score += 30
        flags.append(f"creator bought {t.creator_initial_buy_pct:.0f}% at launch (big green opening candle)")

    # 5. Creator profile
    if t.creator_prior_rugs:
        hard = True
        flags.append(f"creator has {t.creator_prior_rugs} prior rug(s)")
    if t.creator_wallet_age_days is None:
        unknown("creator_wallet_age")
    elif t.creator_wallet_age_days < cfg.min_creator_wallet_age_days:
        score += 15
        flags.append(f"creator wallet only {t.creator_wallet_age_days:.1f} days old")
    if t.creator_prior_launches is not None and t.creator_prior_launches > cfg.max_creator_prior_launches:
        score += 20
        flags.append(f"serial launcher: {t.creator_prior_launches} prior tokens")

    # 2. Wash trading
    if t.wash_ratio is None:
        unknown("wash_ratio")
    elif t.wash_ratio > cfg.max_wash_ratio:
        score += 30
        flags.append(f"{t.wash_ratio:.0%} of volume is wallets trading with themselves")

    # 6. Fabricated social proof
    if t.max_single_wallet_trade_share is not None and t.max_single_wallet_trade_share > cfg.max_single_wallet_trade_share:
        score += 25
        flags.append(f"one wallet is {t.max_single_wallet_trade_share:.0%} of all trades")
    if t.unique_buyers is not None and t.unique_buyers < cfg.min_unique_buyers:
        score += 10
        flags.append(f"only {t.unique_buyers} unique buyers")
    if t.has_x_account is False:
        score += 10
        flags.append("no X account")

    return ScreenResult(risk_score=min(100, score), hard_fail=hard, flags=flags, unknowns=unknowns)
