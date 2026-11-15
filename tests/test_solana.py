import pytest

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


def test_program_owned_non_pool_is_still_a_holder(monkeypatch):
    """Live bug, 15 Nov 2026, token TOOLS: a 20M-token account (2.11% of supply, the creator's
    opening buy) is a token account that owns itself, so its 'owner' is an account owned by the
    Token-2022 program. The old rule excluded every program-owned owner and hid it. Solscan
    lists it as holder #6. Only real pools and curves may be excluded."""
    TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
    PUMP_AMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
    owner_of = {"vault": "FzKcfR2Rz8sWDbvWiXHfwBwu88MgG4XxhKT2eGjCmYKn", "a1": "argBY", "self": "self", "a3": "w3", "odd": "unlistedPool"}
    program_of = {"FzKcfR2Rz8sWDbvWiXHfwBwu88MgG4XxhKT2eGjCmYKn": PUMP_AMM, "argBY": WALLET_OWNER, "self": TOKEN_2022,
                  "w3": WALLET_OWNER, "unlistedPool": "SomeOtherAmm1111111111111111111111111111111"}

    def rpc(method, params, retries=4):
        if method == "getTokenSupply":
            return {"value": {"uiAmount": 947.437}}
        if method == "getTokenLargestAccounts":
            return {"value": [{"address": "vault", "uiAmount": 294.470}, {"address": "odd", "uiAmount": 50.0},
                              {"address": "a1", "uiAmount": 23.152}, {"address": "self", "uiAmount": 20.0}, {"address": "a3", "uiAmount": 10.0}]}
        if method == "getMultipleAccounts" and params[1]["encoding"] == "jsonParsed":
            return {"value": [{"data": {"parsed": {"info": {"owner": owner_of[a]}}}} for a in params[0]]}
        if method == "getMultipleAccounts":
            return {"value": [{"owner": program_of[o]} for o in params[0]]}
        raise AssertionError(method)
    monkeypatch.setattr(solana, "_rpc", rpc)
    pct, excluded = solana.top10_pct("mint")
    assert excluded == 1                                              # only the Pump.fun AMM pool
    assert pct == pytest.approx(100 * (50.0 + 23.152 + 20.0 + 10.0) / 947.437)
    # a pool DexScreener lists for this token is excluded even if its program isn't on our list
    pct2, excluded2 = solana.top10_pct("mint", known_pools=["unlistedPool"])
    assert excluded2 == 2 and pct2 == pytest.approx(100 * (23.152 + 20.0 + 10.0) / 947.437)
