# Trading Desk

A multi-agent trading system with two mandates:

- **A. Solana memecoins** (Trading System Breakdown TM). Screens for rugs on-chain, then applies strict $20-stake risk rules.
- **B. Equities, ETFs and commodities.** The TJR and TradesbySci market-structure model (sweep → BOS → target liquidity), coded and backtested.

**Status: Phase 0, paper trading.** No code here can sign a transaction or move funds.

## Docs

- `MASTER_PROMPT.md`: **start here.** Paste it into Claude Code on your Mac and it installs and runs everything.
- `docs/OPERATOR_BRIEF.md`: Which AI does what, the hard truths, phase gates and the build queue.
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
  firm.py              the firm: all desks in one loop, journal, state, control
  dashboard.py + web/  control room at http://127.0.0.1:8050 (pause / resume / flatten)
  strategies.py        desk routing: Verification Desk, Foot in the Door
  news.py              News Desk morning brief (Grok + journal)
  patterns.py          Pattern Finder
  paper.py             token snapshot builder (+ legacy single-desk loop)
  bot.py               Holder Scout: the customer Telegram bot (/check, /watch, rug alerts, free/pro tiers)
  tracker.py           rug-catch scoreboard: % of flagged vs passed tokens that crashed 90%+
  data/                dexscreener.py, solana.py (RPC/Helius), onchain.py (creator + flow forensics), yahoo.py
  agents/              sentiment_grok.py (X sentiment), decision_claude.py (veto-only reviewer), alerts.py (Telegram)
tests/                 42 tests, run with pytest
journal/               decisions_*.jsonl + trades_*.csv (git-ignored)
```

## Run (MacBook)

1. One-time setup, from the repo folder:

   ```bash
   bash scripts/setup_mac.sh
   ```

2. Open `.env` and paste your keys. Helius is required for trades; Telegram is for alerts; xAI is optional.

3. Start the firm and the control room:

   ```bash
   bash scripts/start.sh
   ```

4. Open http://127.0.0.1:8050 to watch positions, pause, resume or flatten.

Other commands (run inside `src/` with the venv active):

| Command | What it does |
|---|---|
| `python -m desk doctor` | Checks keys and connections |
| `python -m desk check <mint>` | Holder Scout report on one token |
| `python -m desk brief` | News Desk morning briefing |
| `python -m desk patterns` | Pattern Finder: what the winners have in common |
| `python -m desk tracker` | Rug-catch scoreboard |
| `python -m desk backtest` | TJR/Sci model on real hourly data |

To carry on with another Claude session, paste the prompt in `HANDOVER.md`.
