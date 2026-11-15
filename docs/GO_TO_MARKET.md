# Go-to-Market: Holder Scout

## 1. What we sell, and what we don't

**We sell Holder Scout,** a Telegram bot that checks a Solana token for the six rug-pull red flags and sends live rug alerts on tokens the user already holds. It reports facts and never says "buy". That makes it an information tool.

**We don't sell the trading bot, or signals, yet.** Three reasons:

1. **No track record.** The backtest is break-even and the memecoin side hasn't finished paper trading. Advertising profits it hasn't made is misleading conduct under Australian Consumer Law.
2. **Licensing.** Telling people what to trade is "financial product advice", and from 2026 ASIC is pulling crypto services into the licensing regime. Signals for money without an AFSL is the biggest legal risk in this whole plan.
3. **It's your edge.** Your system document is marked confidential. Selling the bot hands that edge to everyone who buys it.

The trading bot becomes sellable later (section 7), once it has 200+ verified paper trades and a lawyer's sign-off.

## 2. Why anyone would pay

Basic rug checkers are free: RugCheck, Rug Rat Radar, @solscanitbot. A free checker answers "is this token safe right now?" when you ask it. We win on things they don't do:

| Free checkers | Holder Scout Pro |
|---|---|
| You have to remember to ask | **Alerts come to you**: liquidity pulled, price dumped, pool gone, on tokens you hold, 24/7 |
| Raw numbers | **Plain-English verdict** with the reason for every flag |
| Contract checks only | **All six red flags**, including creator history and wash trading (Helius build) |
| No social view | **Grok checks X** for shill bots and fake hype (Pro feature, next build) |

**Our honest marketing hook is the rug-catch scoreboard (`python -m desk.tracker`).** It reports what share of the tokens we flagged crashed 90%+ within 24 hours, compared with the tokens we passed. It's a real, checkable number, and we only publish it once the data supports it.

## 3. Pricing (estimate)

Anchors: free checkers at $0, the RugCheck API from about €12/month, and paid crypto Telegram groups around $50/month.

| Plan | Price | Includes |
|---|---|---|
| Free | $0 | 3 checks a day, 1 watched token. This is the funnel |
| **Pro** | **US$19/month** | Unlimited checks, 20 watched tokens, Grok X-hype check |
| Founding member | **US$12/month, locked in for life**, first 25 people only | Same as Pro. Creates urgency and rewards the people who help you get started |
| Annual | US$149/year | About 35% off. Collects cash up front |

We price in USD because the crypto audience is global. No lifetime plans: every user costs us API calls every month for as long as they stay.

**Unit economics (rough):**
- Fixed costs: about US$60–100/month for a server, a paid Helius plan and Grok usage. Check each one's current price when you sign up.
- Whop takes about 2.7% + 30¢ per payment.
- Break-even is roughly 5–8 Pro users.
- 50 users × $19 ≈ **US$950/month**. 200 users ≈ **US$3.8k/month**.

## 4. How people pay: Whop

Use Whop, not Shopify. Whop takes the payment and automatically adds or removes people from a private Telegram group when they subscribe or cancel. Pay-as-you-go is about 2.7% + 30¢, with no monthly fee (confirm the current rate at docs.whop.com/fees).

Version 1 activates Pro by hand: the customer sends their Telegram ID (shown by `/pro`), and you add it to `state/pro_users.json`. Once paid users arrive, a webhook automates that (my build).

## 5. Step by step to the first sale (about 3 weeks)

**Week 1: make it real**

| # | Who | Task |
|---|---|---|
| 1 | You | Get a free Helius API key (helius.dev). Without it, every check comes back "unverified" |
| 2 | You | In Telegram, message @BotFather, send `/newbot`, and name it **Holder Scout** (the username should end in `bot`, e.g. `HolderScoutBot`). If it's taken, try `HolderScoutSolBot` |
| 3 | You | Register a free ABN as a sole trader at abr.gov.au. That's about 15 minutes |
| 4 | You | Book a **30-minute consult with a fintech/crypto lawyer** before you take any money. It's roughly a few hundred dollars (estimate). Take the question list in section 8 |
| 5 | Claude | Helius adapter, so the creator, wash-trading and bundle red flags get measured |
| 6 | Claude | Terms of service, privacy note and disclaimer drafts for the lawyer to review |

**Week 2: free beta and proof**

| # | Who | Task |
|---|---|---|
| 7 | You | Put the bot on a server (Railway or a ~$6 VPS). I'll write the exact click-by-click steps for whichever host you pick |
| 8 | You | Run the paper desk daily so the rug-catch scoreboard builds data |
| 9 | You | Post the launch message (section 6) in 3–5 places: your X account, Solana Telegram groups that allow tools, and r/solana if its rules allow it. Goal: **30 free users** |
| 10 | You | DM every beta user once with the feedback script and collect honest quotes |
| 11 | Claude | Fix whatever beta users hit; build the Grok X-hype check |

**Week 3: open the doors**

| # | Who | Task |
|---|---|---|
| 12 | You | Create a Whop account, add a "Holder Scout Pro" product at US$19/mo plus a founding plan at $12/mo, connect your Telegram group, and add your bank account for payouts |
| 13 | You | Set `UPGRADE_URL` in `.env` to your Whop link and restart the bot |
| 14 | You | Send the founding-member message (section 6) to every beta user |
| 15 | You | **First sale.** Add their Telegram ID to `state/pro_users.json`. Then ask them for a quote and one referral |

**Goals:** 1 paying user by day 21, 10 by day 45, 25 founding seats filled by day 60. If fewer than 3 of the 30 beta users will pay $12, the offer is wrong. Change the product before spending on ads.

## 6. Copy, ready to paste

**Launch post (X / Telegram)**
> Built a free Telegram bot that checks Solana tokens for the 6 classic rug-pull red flags before you ape: insider buys, wash trading, top-holder concentration, mint/freeze authority, creator history, fake hype.
> Paste a contract address and get a plain-English verdict in seconds. It'll also watch tokens you hold and ping you if liquidity gets pulled.
> Free to use: @HolderScoutBot
> Not financial advice. It flags risk; it doesn't pick coins.

**Founding-member message (to beta users)**
> Thanks for testing Holder Scout. Pro is launching: unlimited checks and 24/7 rug alerts on up to 20 tokens you hold.
> Beta users get founding pricing: $12/month locked for life (normally $19). Only 25 seats, and they go first-come.
> [Whop link]
> Reply with any feature you want next. Founding members decide what gets built.

**Feedback DM**
> Quick one: has Holder Scout flagged anything you were about to buy? What's one thing it should do that it doesn't? Honest answers only, I'm building it around them.

**Rules for all copy:** never state a win rate, profit or "catches X% of rugs" until the tracker has measured it. No "guaranteed" and no "safe". Always say "not financial advice".

## 7. Later: selling the trading system itself

Unlock this only when **all** of these are true:
- Phase 0 has 200+ paper trades with positive EV after real costs.
- Phase 1 has been profitable with real money for 3+ months, with a public, timestamped trade log.
- A lawyer has confirmed the structure: most likely self-hosted software the buyer runs on their own wallet and settings, with no signals, no managed accounts and no profit claims.

Likely price at that point: US$49–99/month, or a one-off licence. The work comes before the price.

## 8. Questions for the lawyer

1. Is a Telegram bot that reports token risk flags, and alerts on tokens the user chose, a financial service? Or is it information, given it never recommends buying?
2. Does a feed of new tokens that pass the screen cross into general advice? What wording or design keeps it clear of that?
3. What disclaimer and Terms of Service wording do you recommend, and what should limit my liability if a "clean" token rugs?
4. Sole trader or Pty Ltd for this? When does GST registration apply?
5. Later on, can I sell self-hosted trading software without an AFSL, and what marketing claims are allowed?
