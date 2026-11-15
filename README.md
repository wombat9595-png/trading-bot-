# Trading Desk

A multi-agent trading system with two mandates:

- **A. Solana memecoins** (Trading System Breakdown TM). Screens for rugs on-chain, then applies strict $20-stake risk rules.
- **B. Equities, ETFs and commodities.** The TJR and TradesbySci market-structure model (sweep → BOS → target liquidity), coded and backtested.

**Status: Phase 0, paper trading.** No code here can sign a transaction or move funds.

## Docs

- `docs/OPERATOR_BRIEF.md`: start here. Which AI does what, the hard truths, phase gates and the build queue.
- `docs/GO_TO_MARKET.md`: what we sell (Holder Scout), pricing, and the step-by-step plan to the first sale.
- `docs/PLAYBOOK.md`: every trading rule, its source, and the backtest results.
- `RUG-PULL-WARNING.md`: the scam this desk is built to avoid, never to run.

## Layout

```
src/desk/
  config.py            every tunable number (stake, stops, fees, screen thresholds)
  screener.py          Holder Scout: the 6 red-flag rug screen
  engine.py            conviction score + trade/no-trade + standard/scalp mode
  risk.py              position lifecycle: stop, scalp TP, recover stake, trailing floor, rug watch, max hold
  structure.py         swings, HH/HL/LH/LL, BOS, CHoCH, sweeps, FVG, sweep->BOS setups
  backtest.py          KPIs: win rate, RR, EV (R), max drawdown
  research.py          backtest Mandate B on real hourly data
  paper.py             live paper-trading loop (real data, fake money, full journal)
  bot.py               Holder Scout: the customer Telegram bot (/check, /watch, rug alerts, free/pro tiers)
  tracker.py           rug-catch scoreboard: % of flagged vs passed tokens that crashed 90%+
  data/                dexscreener.py, solana.py (RPC/Helius), yahoo.py
  agents/              sentiment_grok.py (X sentiment), decision_claude.py (veto-only reviewer), alerts.py (Telegram)
tests/                 32 tests, run with pytest
journal/               decisions_*.jsonl + trades_*.csv (git-ignored)
```

## Run

Run each command from the repo root.

1. Install:

   ```bash
   pip install -e ".[ai,dev]"
   ```

2. Create your local settings file, then fill in the keys:

   ```bash
   cp .env.example .env
   ```

3. Run the tests:

   ```bash
   pytest -q
   ```

4. Backtest Mandate B (runs from `src/`):

   ```bash
   cd src && python -m desk.research
   ```

5. Paper trade Mandate A for an hour. This loads the keys from `.env` first, then runs from `src/`:

   ```bash
   set -a && . ./.env && set +a && cd src && python -m desk.paper --minutes 60
   ```

   To also score X sentiment with Grok, add `--grok` at the end of that command.
