"""Which desk takes a trade (TSB section 4).

Verification Desk: DexScreener "token profile" = the team paid for Enhanced Token Info, which
  traders call getting verified / "dex paid". Enter while the event is fresh and the token is
  young; exit as momentum fades.
Foot in the Door: small $20 longs across GRADUATED tokens (off the bonding curve, real pool).

A token that fits neither desk is not traded, however good it looks.
"""
from __future__ import annotations

from .config import DeskConfig, ScreenConfig
from .screener import TokenSnapshot


def assign_desk(t: TokenSnapshot, source: str, d: DeskConfig, s: ScreenConfig) -> str | None:
    if source == "profile" and t.age_minutes is not None and t.age_minutes <= d.verification_max_age_min:
        return "verification"
    if t.graduated and (t.liquidity_usd or 0) >= s.min_liquidity_usd:
        return "foot_in_door"
    return None


def desk_has_room(desk: str, open_desks: list[str], d: DeskConfig) -> bool:
    cap = {"verification": d.verification_max_open, "foot_in_door": d.foot_in_door_max_open}[desk]
    return open_desks.count(desk) < cap


def momentum_faded(buys_5m: int | None, sells_5m: int | None, d: DeskConfig) -> bool:
    b, s = buys_5m or 0, sells_5m or 0
    return (b + s) >= 10 and b / (b + s) < d.verification_fade_ratio
