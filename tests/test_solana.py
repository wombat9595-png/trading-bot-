from desk.data import solana

WALLET_OWNER = solana.SYSTEM_PROGRAM
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"


def fake_rpc(method, params, retries=4):
    if method == "getTokenSupply":
        return {"value": {"uiAmount": 1000.0}}
    if method == "getTokenLargestAccounts":
        # curve vault 600, then three wallets
        return {"value": [{"address": "vault", "uiAmount": 600}, {"address": "a1", "uiAmount": 100},
                          {"address": "a2", "uiAmount": 50}, {"address": "a3", "uiAmount": 30}]}
    if method == "getMultipleAccounts" and params[1]["encoding"] == "jsonParsed":
        owners = {"vault": "curvePDA", "a1": "whale", "a2": "w2", "a3": "w3"}
        return {"value": [{"data": {"parsed": {"info": {"owner": owners[a]}}}} for a in params[0]]}
    if method == "getMultipleAccounts":
        meta = {"curvePDA": {"owner": PUMP_PROGRAM}, "whale": {"owner": WALLET_OWNER}, "w2": None, "w3": {"owner": WALLET_OWNER}}
        return {"value": [meta[o] for o in params[0]]}
    raise AssertionError(method)


def test_top10_excludes_bonding_curve(monkeypatch):
    monkeypatch.setattr(solana, "_rpc", fake_rpc)
    pct, excluded = solana.top10_pct("mint")
    assert excluded == 1
    assert pct == 18.0      # (100+50+30)/1000, the 600 curve vault is not a holder
