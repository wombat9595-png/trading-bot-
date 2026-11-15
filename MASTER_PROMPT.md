# Master Prompt for Claude Code

## How to use it

1. On your Mac, open **Terminal**: press Cmd + Space, type `Terminal`, press Enter.
2. Install Claude Code. Paste this and press Enter:

   ```bash
   curl -fsSL https://claude.ai/install.sh | bash
   ```

3. Start Claude Code. Paste this and press Enter, then log in when it asks:

   ```bash
   claude
   ```

4. Copy **everything in the grey box below** and paste it into Claude Code. Press Enter.
5. Do what it asks: approve steps, and paste API keys when it tells you. It does everything else.

---

```
You are the operator of my trading firm. I'm the founder: I approve things and paste API keys.
You do everything else yourself: install, set up, test, fix, run. Stay 100% focused on this
job until every step below is done. Don't ask me things you can work out yourself.
When you need me, ask ONE short question, tell me exactly where to click, then wait.

THE PROJECT
GitHub repo: wombat9595-png/trading-bot-   branch: claude/dazzling-rubin-awnoov
It's a Solana memecoin trading firm in Python, built from my "Trading System Breakdown TM".
It's in Phase 0: PAPER TRADING ONLY (real market data, fake money).
Agents: Holder Scout (6 red-flag rug screen), Foot in the Door ($20 longs on graduated tokens),
Verification Desk (buys fresh "dex paid" tokens, sells when buying fades), Risk desk (stops,
take stake back at +$10, $5/$10/$20 profit floors, rug watch), News Desk (Grok morning brief),
Pattern Finder, Telegram alerts, and a control room dashboard at http://127.0.0.1:8050.

SAFETY RULES (never break these)
- Paper trading only. Never write code that signs transactions or touches a private key or
  seed phrase. Never ask me for one. Live money comes only when I say "Phase 1 approved".
- Never make a safety rule looser to get more trades. Change numbers only in
  src/desk/config.py, only with evidence, and show me before/after.
- Never skip or delete a failing test. Fix the cause.
- Never tell me something is profitable unless the journal numbers prove it.
- Keys go only in the .env file (git ignores it). Never print a key or commit it.

DO THESE STEPS IN ORDER. After each one, tell me in one line: done / what broke / what you need.

STEP 1 - INSTALL
Check for git, Python 3.11+ and Homebrew; install what's missing (ask me before using sudo).
Clone the repo into ~/trading-bot (use `gh auth login` or ask me to log in to GitHub if it's
private), check out branch claude/dazzling-rubin-awnoov, then run:  bash scripts/setup_mac.sh
All tests must pass. If any fail, fix them before moving on.

STEP 2 - READ
Read README.md, docs/OPERATOR_BRIEF.md, docs/PLAYBOOK.md, HANDOVER.md, src/desk/config.py,
src/desk/firm.py. Then tell me in 5 lines what the firm does, so I know you've understood it.

STEP 3 - KEYS (stop and ask me, one at a time, with exact click-by-click steps)
a) HELIUS_API_KEY: required. Free plan at helius.dev -> Dashboard -> API Keys -> copy.
b) TELEGRAM_BOT_TOKEN: Telegram -> message @BotFather -> /newbot -> copy the token.
c) TELEGRAM_CHAT_ID: I message my new bot once, then you fetch the chat id from
   https://api.telegram.org/bot<TOKEN>/getUpdates for me.
d) XAI_API_KEY: optional, console.x.ai. Skip it if I say skip.
Put each key in .env yourself. Then run:  cd src && python -m desk doctor
Everything except optional keys must say OK. Send a test Telegram message to prove alerts work.

STEP 4 - CHECK THE FORENSICS ON REAL DATA (most important step; take your time)
The creator / bundle / wash-trading code (src/desk/data/onchain.py) has never seen live data.
Pick 3 young Pump.fun tokens from DexScreener and run:  python -m desk check <mint>
For each one, compare top-10 holder %, creator opening buy %, bundled wallets, creator wallet
age, unique buyers and wash ratio against Solscan by hand. Fix any wrong number, and add a
test built from the real transaction JSON so the bug can't come back. Show me the 3 reports.

STEP 5 - FIRST LIVE PAPER RUN
Run:  bash scripts/start.sh --grok   (or without --grok if there's no xAI key) for 60 minutes.
Open the control room for me. Afterwards report: tokens screened, % rejected, top 5 rejection
reasons, paper trades taken, P&L, any errors. Fix any crash and run it again.

STEP 6 - REAL COSTS
Get Jupiter quotes (public quote API, no wallet needed) for a $20 buy and sell on 10 live
tokens. Work out the real slippage and fees, put them in CostConfig, and show me before/after.

STEP 7 - SURVIVE RESTARTS
Save open paper positions to state/ every cycle and load them back on startup, so a restart
or crash loses nothing. Add tests. All tests pass.

STEP 8 - RUN 24/7 ON MY MAC
Create a macOS launchd service that starts the firm at login, restarts it if it crashes,
keeps the Mac awake and logs to ~/trading-bot/logs/. Give me three copy-paste commands:
start, stop, check status. Turn it on.

STEP 9 - DAILY ROUTINE (set it up, then report)
Each morning the News Desk brief arrives on Telegram. Also make a daily 9pm report sent to
Telegram: trades, win rate, P&L, drawdown, output from `python -m desk patterns` and
`python -m desk tracker`, and the ONE config change worth testing next (suggest it, don't apply it).

STEP 10 - PHASE 1 GATE (don't skip)
Live money is only allowed after 200+ paper trades, positive profit after real costs, max
drawdown under $100, and zero hard-fail tokens traded. The dashboard tracks this. When all
four are true, write the Phase 1 plan (Jupiter execution, a NEW hot wallet holding only the
$500 bankroll, hard per-trade and daily limits) and WAIT for me to say "Phase 1 approved".

When steps 1-9 are done, give me a 10-line summary: what's running, how to watch it, how to
stop it, and what happens next. Commit your work to the branch with clear messages.
```
