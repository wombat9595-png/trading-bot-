from desk.screener import TokenSnapshot, screen
from desk.engine import decide
from desk.config import ScreenConfig

CLEAN = dict(mint_authority_revoked=True, freeze_authority_revoked=True, graduated=True, liquidity_usd=40_000,
             top10_pct=18, creator_initial_buy_pct=2, creator_wallet_age_days=200, creator_prior_launches=1,
             creator_prior_rugs=0, unique_buyers=600, max_single_wallet_trade_share=0.03, wash_ratio=0.05,
             has_x_account=True, buys_5m=120, sells_5m=70, price_change_5m_pct=18)


def test_clean_token_passes():
    r = screen(TokenSnapshot("x", **CLEAN))
    assert not r.hard_fail and r.risk_score == 0 and r.mode(ScreenConfig()) == "standard"


def test_mint_authority_is_hard_fail():
    r = screen(TokenSnapshot("x", **{**CLEAN, "mint_authority_revoked": False}))
    assert r.hard_fail and r.mode(ScreenConfig()) == "reject"


def test_prior_rug_creator_is_hard_fail():
    assert screen(TokenSnapshot("x", **{**CLEAN, "creator_prior_rugs": 1})).hard_fail


def test_classic_rug_profile_rejected():
    rug = {**CLEAN, "creator_initial_buy_pct": 35, "wash_ratio": 0.6, "max_single_wallet_trade_share": 0.4,
           "creator_wallet_age_days": 0.2}
    r = screen(TokenSnapshot("x", **rug))
    assert r.mode(ScreenConfig()) == "reject" and len(r.flags) >= 4


def test_unknown_is_not_safe():
    r = screen(TokenSnapshot("x"))
    assert r.risk_score > 0 and len(r.unknowns) >= 6


def test_missing_holder_data_blocks_trade():
    r = screen(TokenSnapshot("x", **{**CLEAN, "top10_pct": None}))
    assert r.hard_fail and r.mode(ScreenConfig()) == "reject"


def test_moderate_risk_goes_to_scalp_mode():
    r = screen(TokenSnapshot("x", **{**CLEAN, "top10_pct": 35, "creator_wallet_age_days": 1}))
    assert r.mode(ScreenConfig()) == "scalp"


def test_engine_trades_clean_and_skips_parabolic_chase():
    assert decide(TokenSnapshot("x", **CLEAN)).trade
    chase = decide(TokenSnapshot("x", **{**CLEAN, "price_change_5m_pct": 400, "buys_5m": 60, "sells_5m": 55}))
    assert not chase.trade
