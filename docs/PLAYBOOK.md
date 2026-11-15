# Strategy Playbook

This is what the desk trades. It distils the five source documents into rules a machine can follow. Each rule names the code that enforces it. If a rule isn't enforced in code, it says **NOT YET CODED**.

Sources: Trading System Breakdown TM (TSB), TJR Bootcamp (TJR), TradesbySci Crash Course (SCI), Candlestick Terms (CT), Financial Terms (FT).

---

## Mandate A: Solana memecoins (TSB). Phase 0 = paper only

### A1. Entry gate: Holder Scout (`screener.py`)

A token is screened against TSB's six red flags. Unknown data is penalised, never treated as a pass.

| # | Red flag | Rule | Effect |
|---|---|---|---|
| 4 | Contract risk | Mint authority or freeze authority not revoked | **Hard reject** |
| 4 | Contract risk | Still on the bonding curve | +15 risk |
| 4 | Contract risk | Liquidity under $5k | +20 risk |
| 3 | Holder concentration | Top 10 wallets hold over 45% | **Hard reject** |
| 3 | Holder concentration | Top 10 wallets hold over 30% | +25 risk |
| 1 | Insider accumulation | Creator's opening buy over 10% of supply | +30 risk |
| 5 | Creator profile | Any prior rug | **Hard reject** |
| 5 | Creator profile | Wallet under 3 days old | +15 risk |
| 5 | Creator profile | More than 5 prior launches | +20 risk |
| 2 | Wash trading | Over 35% of volume is self-trading | +30 risk |
| 6 | Fake social proof | One wallet makes over 15% of all trades | +25 risk |
| 6 | Fake social proof | Under 40 unique buyers | +10 risk |
| 6 | Fake social proof | No X account | +10 risk |

- **Risk 0–39:** standard mode
- **Risk 40–69:** scalp mode
- **Risk 70+:** reject

### A2. Conviction (`engine.py`)

`conviction = 0.5 × safety + 0.3 × momentum + 0.2 × sentiment`

A trade needs **conviction ≥ 0.60 and momentum ≥ 0.35**. The momentum gate exists because a token can look safe while nobody is buying it, and that isn't a trade.

Momentum is penalised in two cases:
- Chasing a 5-minute candle that is already up more than 150%. TSB calls those buyers exit liquidity.
- Buying into an active dump.

### A3. Position rules (`risk.py`)

All values are in USD. P&L is always measured at the price you could actually sell at, after slippage and fees.

| Rule | Value | Source |
|---|---|---|
| Stake | $20 | TSB "Foot in the Door" |
| Stop-loss | −$7.50 | TSB ($5–10) |
| Scalp take-profit | +$1.50, full exit | TSB ($1–2) |
| Recover stake | At +$10, sell enough to take the $20 back out; the rest rides | TSB |
| Trailing floor | Locks in $5, then $10, then $20 of profit as the peak passes $10, $20 and $40 | TSB |
| Rug watch | Any rug alert means sell everything immediately | TSB |
| Max hold | 15 minutes | TSB ("rugs strike within minutes") |
| Max open positions | 5 | added |
| Daily loss limit | −$30, then the desk stops for the day | added |

### A4. Not yet coded (next build steps)

- **Creator wallet history, bundled-launch detection, wash-ratio measurement.** These need Helius' enhanced transactions API. Until they're built, those fields come back as *unknown* and add risk.
- **Live rug watch.** This means LP removal, the dev wallet moving, and whale dumps. Today the only rug signal is a pair vanishing.
- **Verification Desk, Pattern Finder and the smart-money tracker** from TSB §4.
- **Staged exits** (TSB §7). Not needed until a single position is over about $1k.

---

## Mandate B: Equities, ETFs and commodities (TJR and SCI price action)

### B1. Market structure (`structure.py`)

- **Swings.** A swing high or low needs 2 bars on each side to confirm it. The code only uses a swing once it is confirmed, so it never acts on information a live chart wouldn't show yet.
- **Labels.** Swings are labelled HH, HL, LH or LL.
  - Uptrend = HH + HL
  - Downtrend = LH + LL
  - Anything else = range, so no trend bias (SCI Day 1)
- **BOS (break of structure).** Counts only on a candle **close** beyond the swing. A wick through it is not a BOS (TJR Day 6).
- **CHoCH (change of character).** The first close against the prevailing trend (CT).
- **Liquidity sweep.** A wick through a swing high or low that then closes back inside it (TJR Days 8, 10, 12).
- **FVG (fair value gap).** A gap between candle 1's high and candle 3's low, or the reverse (CT). Detected, but not yet used in entries.

### B2. The setup (TJR Day 12 + SCI Day 2/4)

1. Price sweeps sell-side liquidity, taking out a swing low.
2. Within 12 bars, a candle closes above the most recent swing high (BOS or CHoCH up).
3. **Entry:** close of the break candle.
   **Stop:** the lowest point of the sweep.
   **Target:** the nearest swing high (buy-side liquidity) that is at least **2R** away.
4. **Filter:** the 4H trend must not point against the trade ("all timeframes match").
5. Shorts are the mirror image.

### B3. Backtest results

Data: 2 years of 1H bars with a 4H filter. Results are after realistic costs. One position at a time. If the stop and target are both hit in the same bar, the backtest counts it as a stop.

| Market | Trades | Net EV per trade | 1st year | 2nd year |
|---|---|---|---|---|
| Gold (GC=F) | 132 | +0.07R | +0.24R | −0.09R |
| Silver (SI=F) | 157 | +0.09R | +0.13R | +0.05R |
| QQQ | 41 | +0.23R | +0.30R | +0.14R |
| SPY | 40 | +0.10R | +0.23R | −0.02R |
| EUR/USD | 224 | −0.07R | −0.06R | −0.09R |
| BTC | 209 | −0.13R | −0.14R | −0.11R |

**What this means.** Coded literally, the model is roughly break-even. It is slightly positive on metals and US indices and negative on FX and BTC. Gold and SPY lost money in the second year. None of the positive results is statistically significant yet: with about 130 trades, the noise is about ±0.13R per trade.

The 4H filter helps on SI, SPY and GC, which supports SCI's "trade with the trend" rule.

This is a **baseline to improve**, not a strategy to fund. The next things to test:
- Session filter: only trade sweeps at the London or New York open (CT)
- Entering on a pullback into the FVG or order block after the BOS, instead of at the break candle's close
- A partial exit at 1R with the stop moved to break-even

Reproduce:
```bash
cd src && python -m desk.research
```

---

## Mindset rules (TJR Days 3, 5, 7, 9, 11) → desk rules

| Bootcamp rule | Desk translation |
|---|---|
| "No trader has a 100% win rate" | The KPI is expectancy across the whole sample, never the result of one trade |
| "Take accountability when you lose" | Every decision and trade is written to `journal/`, including rejects |
| "Follow my trading plan every single day" | The bot can't break its rules. You change a rule only in `config.py`, and only after a backtest |
| "Do what works for you" | Each strategy is judged on its own numbers; drop what doesn't pay |
