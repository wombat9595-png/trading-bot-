# Operator Brief

The plain-English version: what's built, what's true, and what happens next.

## 1. Who does what: Grok vs Claude vs ChatGPT

You don't need all three. Each model has one job it does best. Anything that has to be fast stays in plain code.

| Job | Tool | Why |
|---|---|---|
| X/Twitter sentiment, narrative and influencer tracking (News Desk) | **Grok** (`grok-4.7` + `x_search`) | It's the only model with first-party, live access to X, and memecoin narrative lives on X |
| Rug screening, entries, exits, stops | **Plain code, no AI** | Has to answer in milliseconds, can't have a bad day, and can be backtested. An AI call takes seconds, and in this market that delay alone loses trades |
| Second opinion on bigger or slower trades; founder hold-or-exit calls; daily post-trade review; writing and maintaining the code | **Claude** | Best at reasoning over messy evidence and at writing code. Set to fail closed: if it errors, it vetoes |
| Nothing ChatGPT does that the two above don't already cover | **Skip it** | A third vendor means another bill, another key and another failure point, for no edge |

## 2. Hard truths

1. **Fees eat a $20 position.** Slippage, the venue fee and the network fee add up to roughly 5% of the stake per round trip, about $1 of a $20 trade. Every trade starts −$1 down. A $1.50 scalp target therefore nets about $0.50, and needs a ~12.5% price move just to get there. Phase 0's main job is measuring the *real* costs. Once you have them, set them in `config.py → CostConfig`.
2. **A stop-loss can't save you from a rug.** When liquidity is pulled, the price gaps straight to zero, so the "$7.50 stop" can fill at −$20. The backtest assumes stops fill at the stop price, so it flatters the results. Size every position as if you could lose 100% of it.
3. **The TJR/Sci strategy is break-even as coded.** It's slightly positive on gold, silver, QQQ and SPY, negative on EUR/USD and BTC, and weaker in the most recent year. None of it is proven yet. Numbers are in `docs/PLAYBOOK.md` §B3. Treat it as a starting point to improve, not a money printer.
4. **Most new memecoins go to zero, and missing data is not a pass.** The first live 3-minute scan screened 48 new tokens and approved 8 of them, but all 8 were approved *without holder data*. The bot was blind to the biggest rug signal. That is now a hard rule: no top-10 holder data means no trade. On the free public Solana RPC that blocks nearly everything, because it rate-limits hard, so a Helius key is required for Phase 0 to produce any trades at all.
5. **Legal (Australia).**
   - Trading your own money is fine.
   - **Managing other people's money, pooling investors, or selling signals as advice needs an AFSL.** A "trading firm" that takes outside capital without one is illegal. Keep it to your own capital until you've talked to a lawyer.
   - Crypto profits are subject to capital gains tax, and every paper and live trade needs to be logged. The journal already does this.

## 3. Phase gates

The bot doesn't skip phases. A phase only opens when the numbers say so.

| Gate | Pass criteria |
|---|---|
| Phase 0 → 1 (go live with $500) | ≥200 paper trades; positive realised EV **after the real costs you've measured**; max drawdown under $100; zero hard-fail tokens traded |
| Phase 1 → 2 | Seed capital withdrawn; Phase 1 profitable over ≥300 trades |
| Phase 2 → 3 | Funded only from Phase 2 profits (Scaling Plan TM) |

## 4. Build status

| Agent (from TSB §4) | Status |
|---|---|
| Holder Scout: all 6 red flags | Built. Creator, bundle and wash-trading forensics are coded and unit-tested but **not yet checked on live data** (needs a Helius key) |
| Foot in the Door | Built: $20 longs on graduated tokens, max 4 open |
| Verification Desk | Built: enters on a fresh DexScreener profile ("dex paid"), exits when 5-minute buying fades. Max 2 open |
| News Desk | Built: morning brief from the journal plus Grok's read of X |
| Pattern Finder | Built: win rate and average P&L by trait, and warns when the sample is too small |
| Alerts | Built: Telegram alerts on every trade, plus milestone hold-or-withdraw escalations |
| Live rug watch | Built: liquidity down 50% since entry, or the pair vanishing, closes the position immediately. Polls every 20s; websocket comes later |
| Control room | Built: http://127.0.0.1:8050 with pause, resume and flatten |
| Survives restarts / runs 24/7 | Next (`HANDOVER.md` jobs 5–6) |
| Execution adapter (live money) | Deliberately not built until the Phase 1 gate passes |

## 5. Security rules

- No private key or seed phrase ever goes in this repo, `.env`, a chat or a bot. Phase 0 code has no signing path at all.
- When live trading starts, use a dedicated hot wallet that holds only the current phase's bankroll. Profits go to a cold wallet.
- API keys live in `.env`, which git already ignores, and nowhere else.
