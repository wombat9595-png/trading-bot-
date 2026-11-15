"""Decision engine: one conviction score per token -> trade / no trade + mode.

Safety is a GATE first and a weight second: a hard fail or a reject-level risk score
ends the conversation no matter how good momentum or sentiment look.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .agents.sentiment_grok import NEUTRAL, Sentiment
from .config import EngineConfig, ScreenConfig
from .screener import ScreenResult, TokenSnapshot, screen


@dataclass
class Decision:
    trade: bool
    mode: str                  # standard | scalp | reject
    conviction: float
    screen: ScreenResult
    reasons: list[str] = field(default_factory=list)


def momentum_score(t: TokenSnapshot) -> float:
    """0..1 from 5-minute order flow. Rewards steady buying, punishes chasing a vertical candle."""
    if not t.buys_5m and not t.sells_5m:
        return 0.3
    buys, sells = t.buys_5m or 0, t.sells_5m or 0
    ratio = buys / max(1, buys + sells)            # 0.5 = balanced
    s = min(1.0, max(0.0, (ratio - 0.45) / 0.3))   # 0.45 -> 0, 0.75 -> 1
    ch = t.price_change_5m_pct
    if ch is not None:
        if ch > 150:
            s *= 0.4                               # parabolic: late, likely exit liquidity
        elif ch < -15:
            s *= 0.5                               # actively dumping
    return s


def decide(t: TokenSnapshot, sentiment: Sentiment = NEUTRAL,
           ecfg: EngineConfig | None = None, scfg: ScreenConfig | None = None) -> Decision:
    ecfg, scfg = ecfg or EngineConfig(), scfg or ScreenConfig()
    sr = screen(t, scfg)
    mode = sr.mode(scfg)
    reasons = list(sr.flags)
    if mode == "reject":
        return Decision(False, "reject", 0.0, sr, reasons or ["risk score too high"])
    mom = momentum_score(t)
    conv = ecfg.w_safety * sr.safety + ecfg.w_momentum * mom + ecfg.w_sentiment * sentiment.score
    reasons.append(f"safety {sr.safety:.2f} | momentum {mom:.2f} | sentiment {sentiment.score:.2f}"
                   + ("" if sentiment.available else " (no feed)"))
    if sentiment.available and sentiment.shill_ratio > 0.6:
        reasons.append(f"X chatter is {sentiment.shill_ratio:.0%} shill")
        conv -= 0.1
    trade = conv >= ecfg.min_conviction and mom >= ecfg.min_momentum
    if mom < ecfg.min_momentum:
        reasons.append(f"momentum {mom:.2f} < {ecfg.min_momentum} gate")
    elif not trade:
        reasons.append(f"conviction {conv:.2f} < {ecfg.min_conviction}")
    return Decision(trade, mode if trade else "pass", round(conv, 3), sr, reasons)
