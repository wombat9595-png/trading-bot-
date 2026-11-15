"""Holder Scout: the customer-facing Telegram bot (the sellable product).

It's an information tool. It reports facts and risk flags about a token the USER chose,
and alerts on tokens the USER holds. It never says "buy". That keeps it on the
information side of the line, not the financial-advice side (get a lawyer to confirm).

Commands:
  /start                 intro + disclaimer
  /check <mint>          6-red-flag safety report in plain English
  /watch <mint>          live rug-watch alerts on a token you hold
  /unwatch <mint>        stop watching
  /list                  your watchlist
  /pro                   how to upgrade

Free tier: 3 checks/day, 1 watched token. Pro: unlimited checks, 20 watched tokens.
Pro users = Telegram user IDs in state/pro_users.json (Whop webhook can write this later).

Run:  cd src && python -m desk.bot     (needs TELEGRAM_BOT_TOKEN; HELIUS_API_KEY strongly advised)
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from .config import DEFAULT
from .screener import ScreenResult, TokenSnapshot, screen

STATE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "state")
FREE_CHECKS_PER_DAY = 3
FREE_WATCH_SLOTS = 1
PRO_WATCH_SLOTS = 20
UPGRADE_URL = os.getenv("UPGRADE_URL", "https://whop.com/  (link coming soon)")
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

DISCLAIMER = ("Holder Scout reports on-chain facts and risk flags. It is general information only, "
              "not financial advice, and it does not consider your situation. A clean report is not "
              "a recommendation to buy. Memecoins can go to zero in minutes. Only risk what you can lose.")

# Rug-watch thresholds
DROP_ALERT_PCT = 40.0      # price down this much vs. last check
LIQ_DROP_ALERT_PCT = 50.0  # liquidity down this much vs. when you started watching


# ---------- verdict text (pure, tested) ----------

def verdict(snap: TokenSnapshot, sr: ScreenResult) -> str:
    mode = sr.mode(DEFAULT.screen)
    only_unverified = (snap.top10_pct is None and snap.mint_authority_revoked is not False
                       and snap.freeze_authority_revoked is not False and not snap.creator_prior_rugs)
    if sr.hard_fail and only_unverified:
        head = "⚪ UNVERIFIED (holder data unavailable, treat as unsafe)"
    elif sr.hard_fail:
        head = "🔴 DANGER"
    elif mode == "reject":
        head = "🔴 HIGH RISK"
    elif mode == "scalp":
        head = "🟠 CAUTION"
    else:
        head = "🟢 NO MAJOR RED FLAGS FOUND"
    lines = [f"{head}: {snap.symbol or snap.address[:6]}  (risk {sr.risk_score}/100)", ""]
    if sr.flags:
        lines.append("Red flags:")
        lines += [f"• {f}" for f in sr.flags]
    checks = []
    if snap.mint_authority_revoked:
        checks.append("mint authority revoked")
    if snap.freeze_authority_revoked:
        checks.append("freeze authority revoked")
    if snap.top10_pct is not None and snap.top10_pct <= DEFAULT.screen.max_top10_pct:
        checks.append(f"top-10 holders {snap.top10_pct:.0f}%")
    if snap.has_x_account:
        checks.append("has an X account")
    if checks:
        lines += ["", "Passed: " + ", ".join(checks)]
    if sr.unknowns:
        lines += ["", "Couldn't measure: " + ", ".join(u.replace("_", " ") for u in sr.unknowns)]
    lines += ["", "Not financial advice. /watch to get rug alerts on this token."]
    return "\n".join(lines)


# ---------- state ----------

@dataclass
class User:
    checks_day: str = ""
    checks_used: int = 0
    watch: dict = field(default_factory=dict)   # mint -> {"symbol", "last_price", "start_liq"}


class Store:
    def __init__(self, path: str | None = None):
        self.dir = path or STATE_DIR
        os.makedirs(self.dir, exist_ok=True)
        self.users_path = os.path.join(self.dir, "users.json")
        self.pro_path = os.path.join(self.dir, "pro_users.json")
        self.users: dict[str, User] = {}
        if os.path.exists(self.users_path):
            for k, v in json.load(open(self.users_path)).items():
                self.users[k] = User(**v)

    def save(self) -> None:
        tmp = self.users_path + ".tmp"
        json.dump({k: vars(u) for k, u in self.users.items()}, open(tmp, "w"))
        os.replace(tmp, self.users_path)

    def user(self, uid: int | str) -> User:
        return self.users.setdefault(str(uid), User())

    def is_pro(self, uid: int | str) -> bool:
        try:
            return str(uid) in {str(x) for x in json.load(open(self.pro_path))}
        except (FileNotFoundError, ValueError):
            return False

    def take_check(self, uid: int | str) -> bool:
        if self.is_pro(uid):
            return True
        u = self.user(uid)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if u.checks_day != today:
            u.checks_day, u.checks_used = today, 0
        if u.checks_used >= FREE_CHECKS_PER_DAY:
            return False
        u.checks_used += 1
        self.save()
        return True


# ---------- command handling (pure-ish, tested with a fake snapshot builder) ----------

def handle(text: str, uid: int, store: Store, build_snapshot) -> str:
    parts = text.strip().split()
    if not parts:
        return ""
    cmd = parts[0].split("@")[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/start":
        return ("Holder Scout checks Solana tokens for the six classic rug-pull red flags: insider buys, "
                "wash trading, holder concentration, contract risk, creator history and fake hype.\n\n"
                "/check <token address>: safety report\n/watch <address>: rug alerts on a token you hold\n"
                "/list: your watchlist\n/pro: upgrade\n\n" + DISCLAIMER)
    if cmd == "/pro":
        return (f"Pro: unlimited checks + live rug alerts on up to {PRO_WATCH_SLOTS} tokens.\n"
                f"Free: {FREE_CHECKS_PER_DAY} checks/day, {FREE_WATCH_SLOTS} watched token.\n"
                f"Upgrade: {UPGRADE_URL}\nYour Telegram ID (needed for activation): {uid}")
    if cmd == "/list":
        w = store.user(uid).watch
        return "Watching:\n" + "\n".join(f"• {v.get('symbol') or k[:6]}  {k}" for k, v in w.items()) if w else "Watchlist empty. /watch <address>"
    if cmd in ("/check", "/watch", "/unwatch"):
        if not MINT_RE.match(arg):
            return f"Send a Solana token address, e.g. {cmd} 7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
    if cmd == "/unwatch":
        removed = store.user(uid).watch.pop(arg, None)
        store.save()
        return "Stopped watching." if removed else "That token isn't on your watchlist."
    if cmd == "/check":
        if not store.take_check(uid):
            return f"You've used your {FREE_CHECKS_PER_DAY} free checks today. /pro for unlimited."
        snap = build_snapshot(arg)
        if snap is None:
            return "No trading pair found for that address on DexScreener."
        return verdict(snap, screen(snap, DEFAULT.screen))
    if cmd == "/watch":
        u = store.user(uid)
        slots = PRO_WATCH_SLOTS if store.is_pro(uid) else FREE_WATCH_SLOTS
        if arg not in u.watch and len(u.watch) >= slots:
            return f"Watchlist full ({slots}). /unwatch one, or /pro for {PRO_WATCH_SLOTS} slots."
        snap = build_snapshot(arg)
        if snap is None:
            return "No trading pair found for that address."
        u.watch[arg] = {"symbol": snap.symbol, "last_price": snap.price_usd, "start_liq": snap.liquidity_usd}
        store.save()
        return (f"Watching {snap.symbol}. You'll get an alert if price drops {DROP_ALERT_PCT:.0f}%+ between checks, "
                f"liquidity falls {LIQ_DROP_ALERT_PCT:.0f}%+, or the pool disappears.")
    return "Unknown command. /start for help."


def rug_watch_alerts(store: Store, fetch_pair_state) -> list[tuple[str, str]]:
    """One sweep over every watchlist. fetch_pair_state(mint) -> (price, liquidity) or None."""
    out: list[tuple[str, str]] = []
    cache: dict[str, tuple | None] = {}
    for uid, u in store.users.items():
        for mint, w in list(u.watch.items()):
            if mint not in cache:
                cache[mint] = fetch_pair_state(mint)
            st = cache[mint]
            name = w.get("symbol") or mint[:6]
            if st is None:
                out.append((uid, f"🚨 {name}: trading pair has disappeared. Possible rug. Check now."))
                continue
            px, liq = st
            last = w.get("last_price")
            if last and px and px <= last * (1 - DROP_ALERT_PCT / 100):
                out.append((uid, f"🚨 {name}: price down {100 * (1 - px / last):.0f}% since last check."))
            start_liq = w.get("start_liq")
            if start_liq and liq is not None and liq <= start_liq * (1 - LIQ_DROP_ALERT_PCT / 100):
                out.append((uid, f"🚨 {name}: liquidity down {100 * (1 - liq / start_liq):.0f}% since you started watching. Possible LP pull."))
                w["start_liq"] = liq   # don't repeat the same alert every minute
            if px is not None:
                w["last_price"] = px
    store.save()
    return out


# ---------- live wiring ----------

def _live_snapshot(mint: str) -> TokenSnapshot | None:
    from .paper import build_snapshot
    return build_snapshot(mint)


def _live_pair_state(mint: str):
    from .data import dexscreener as dx
    try:
        p = dx.best_pair(mint)
    except requests.RequestException:
        return ("err", None)  # network hiccup is not a rug
    if not p:
        return None
    return float(p["priceUsd"]) if p.get("priceUsd") else None, (p.get("liquidity") or {}).get("usd")


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    api = f"https://api.telegram.org/bot{token}"
    store = Store()
    offset, last_sweep = 0, 0.0

    def send(chat, text):
        requests.post(f"{api}/sendMessage", json={"chat_id": chat, "text": text, "disable_web_page_preview": True}, timeout=15)

    print("Holder Scout bot running")
    while True:
        try:
            r = requests.get(f"{api}/getUpdates", params={"offset": offset, "timeout": 25}, timeout=35).json()
            for upd in r.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                if msg.get("text"):
                    reply = handle(msg["text"], msg["from"]["id"], store, _live_snapshot)
                    if reply:
                        send(msg["chat"]["id"], reply)
        except requests.RequestException as e:
            print("telegram error", e)
            time.sleep(5)
        if time.time() - last_sweep > 60:
            last_sweep = time.time()

            def state(m):
                s = _live_pair_state(m)
                return None if s is None else (s if s[0] != "err" else (None, None))
            for uid, text in rug_watch_alerts(store, state):
                send(int(uid), text)


if __name__ == "__main__":
    main()
