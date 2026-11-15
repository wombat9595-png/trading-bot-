from desk.bot import Store, handle, rug_watch_alerts, FREE_CHECKS_PER_DAY
from desk.screener import TokenSnapshot
import json, os

MINT = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"


def snap(_):
    return TokenSnapshot(MINT, symbol="TEST", mint_authority_revoked=True, freeze_authority_revoked=False,
                         top10_pct=20, liquidity_usd=10_000, price_usd=1.0, graduated=True)


def test_check_reports_danger_and_disclaimer(tmp_path):
    out = handle(f"/check {MINT}", 1, Store(str(tmp_path)), snap)
    assert "DANGER" in out and "freeze_authority NOT revoked" in out and "Not financial advice" in out


def test_free_tier_check_limit(tmp_path):
    st = Store(str(tmp_path))
    for _ in range(FREE_CHECKS_PER_DAY):
        handle(f"/check {MINT}", 1, st, snap)
    assert "/pro" in handle(f"/check {MINT}", 1, st, snap)


def test_pro_unlimited(tmp_path):
    st = Store(str(tmp_path))
    json.dump([1], open(os.path.join(str(tmp_path), "pro_users.json"), "w"))
    for _ in range(FREE_CHECKS_PER_DAY + 2):
        assert "DANGER" in handle(f"/check {MINT}", 1, st, snap)


def test_bad_address_rejected(tmp_path):
    assert "Send a Solana token address" in handle("/check hello", 1, Store(str(tmp_path)), snap)


def test_watch_slots_and_rug_alerts(tmp_path):
    st = Store(str(tmp_path))
    assert "Watching TEST" in handle(f"/watch {MINT}", 1, st, snap)
    assert "full" in handle("/watch So11111111111111111111111111111111111111112", 1, st, snap)
    # price -50% and liquidity -60%
    alerts = rug_watch_alerts(st, lambda m: (0.5, 4_000))
    assert len(alerts) == 2
    # pool vanished
    assert "disappeared" in rug_watch_alerts(st, lambda m: None)[0][1]
    # network error must not wipe last price or alert
    assert rug_watch_alerts(st, lambda m: (None, None)) == []


def test_unverified_label_when_only_holder_data_missing(tmp_path):
    def s2(_):
        return TokenSnapshot(MINT, symbol="X", mint_authority_revoked=True, freeze_authority_revoked=True, price_usd=1.0)
    assert "UNVERIFIED" in handle(f"/check {MINT}", 1, Store(str(tmp_path)), s2)
