"""Daily founder report, sent to Telegram at 9pm by launchd (scripts/install_service.sh).

    cd src && python -m desk report            # build, print and send
    cd src && python -m desk report --no-send  # print only

Trades, win rate, P&L, drawdown, the Phase 1 gate, Pattern Finder, the rug-catch scoreboard
and ONE config change worth testing next. The suggestion is text only. Nothing in this module
writes to config.py: the founder decides.

Suggestions only ever tighten the rules (trade less, cut what loses). This module never
suggests loosening a safety rule to get more trades.
"""
from __future__ import annotations

import glob
import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import patterns
from .config import DEFAULT, Settings
from .dashboard import GATE_MAX_DD, GATE_TRADES, summary

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
JOURNAL = os.path.join(ROOT, "journal")
TG_LIMIT = 3900


def trades_since(trades: list[dict], hours: float) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return [t for t in trades if datetime.fromisoformat(t["closed_utc"]) >= cutoff]


def decisions_since(hours: float) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = []
    for f in sorted(glob.glob(os.path.join(JOURNAL, "decisions_*.jsonl")))[-3:]:
        for line in open(f):
            r = json.loads(line)
            if datetime.fromisoformat(r["ts"]) >= cutoff:
                rows.append(r)
    return rows


def reason_key(reason: str) -> str:
    """Collapse the numbers out of a reason so identical causes group together."""
    import re
    return re.sub(r"\$?[\d,]+(\.\d+)?%?", "N", reason).strip()


def top_reject_reasons(decisions: list[dict], k: int = 5) -> list[tuple[str, int]]:
    c: Counter = Counter()
    for d in decisions:
        if d.get("trade"):
            continue
        for r in d.get("reasons") or ["(no reason logged)"]:
            if not r.startswith("safety "):
                c[reason_key(r)] += 1
    return c.most_common(k)


def suggest(trades: list[dict], s: Settings = DEFAULT) -> str:
    """Pure: the ONE config change worth testing next, as text. Never applied here."""
    n = len(trades)
    if n < patterns.MIN_N:
        return (f"None yet. {n} closed trade(s) is too few to justify any change "
                f"(need {patterns.MIN_N}+ in one bucket). Keep collecting.")
    a = patterns.analyse(trades)

    def bad(trait: str, val: str) -> tuple[int, float] | None:
        cnt, _, avg = a.get(trait, {}).get(val, (0, 0, 0.0))
        return (cnt, avg) if cnt >= patterns.MIN_N and avg < 0 else None

    options: list[tuple[float, str]] = []     # (total $ lost in the bucket, suggestion)

    def add(hit, text: str) -> None:
        if hit:
            options.append((hit[0] * hit[1], f"{text}  Evidence: {hit[0]} trades averaging ${hit[1]:+.2f}."))

    add(bad("mode", "scalp"), f"Test ScreenConfig.reject_score {s.screen.reject_score} -> {s.screen.high_risk_score} "
                              "(stop taking scalp-mode, risk 40+ tokens).")
    add(bad("conviction", "0.60-0.70"), f"Test EngineConfig.min_conviction {s.engine.min_conviction} -> 0.70 "
                                        "(drop the lowest-conviction entries).")
    add(bad("risk_score", "20-39"), f"Test ScreenConfig.high_risk_score {s.screen.high_risk_score} -> 20 "
                                    "(risk 20-39 tokens get the tight scalp exit instead of the standard one).")
    add(bad("desk", "verification"), f"Test DeskConfig.verification_max_open {s.desks.verification_max_open} -> "
                                     f"{max(0, s.desks.verification_max_open - 1)} (shrink the Verification Desk).")
    add(bad("desk", "foot_in_door"), f"Test DeskConfig.foot_in_door_max_open {s.desks.foot_in_door_max_open} -> "
                                     f"{max(0, s.desks.foot_in_door_max_open - 1)} (shrink Foot in the Door).")
    add(bad("exit", "max hold time"), f"Test RiskConfig.max_hold_seconds {s.risk.max_hold_seconds} -> "
                                      f"{s.risk.max_hold_seconds * 2 // 3} (positions that time out are losing; cut them sooner).")
    if not options:
        return "None. No bucket with enough trades is losing money; changing numbers now would be curve-fitting."
    return min(options)[1]


def build(tracker_text: str | None = None, hours: float = 24) -> str:
    sm = summary()
    all_trades = patterns.load()
    day = trades_since(all_trades, hours)
    pnl = [t["pnl_usd"] for t in day]
    g = sm["gate"]
    tick = lambda ok: "PASS" if ok else "not yet"
    out = [f"DAILY REPORT {datetime.now().strftime('%a %d %b %H:%M')}  (Phase 0, paper money)", "",
           f"Last {hours:.0f}h: {len(day)} trades, " + (f"{sum(p > 0 for p in pnl)} winners "
           f"({100 * sum(p > 0 for p in pnl) / len(pnl):.0f}%), P&L ${sum(pnl):+.2f}" if pnl else "nothing closed"),
           f"All time: {sm['n']} trades, " + (f"win rate {sm['win_rate']:.0%}, P&L ${sm['total']:+.2f}, "
           f"${sm['ev']:+.2f}/trade, max drawdown ${sm['max_dd']:.2f}" if sm["n"] else "no closed trades yet")]
    dec = decisions_since(hours)
    if dec:
        rej = sum(not d.get("trade") for d in dec)
        out.append(f"Screened {len(dec)} tokens, rejected {rej} ({100 * rej / len(dec):.0f}%)")
        out += [f"  {c:>4}x {r[:70]}" for r, c in top_reject_reasons(dec, 3)]
    out += ["", "PHASE 1 GATE: " + ("ALL FOUR PASS. Awaiting founder decision." if g["passed"] else "closed"),
            f"  {GATE_TRADES}+ paper trades: {sm['n']}/{GATE_TRADES}  [{tick(not g['trades_needed'])}]",
            f"  Profit after costs: ${sm['total']:+.2f}  [{tick(g['ev_positive'])}]",
            f"  Max drawdown under ${GATE_MAX_DD:.0f}: ${sm['max_dd']:.2f}  [{tick(g['dd_ok'])}]",
            f"  Zero hard-fail tokens traded: {g['hard_fail_traded']} traded"
            + (f", {g['hard_fail_unaudited']} unaudited" if g["hard_fail_unaudited"] else "") + f"  [{tick(g['hard_fail_ok'])}]",
            "", patterns.report(all_trades), ""]
    if tracker_text is None:
        from . import tracker
        try:
            tracker_text = tracker.run(24)
        except Exception as e:
            tracker_text = f"Rug-catch scoreboard unavailable: {str(e)[:80]}"
    out += [tracker_text, "", "ONE CHANGE WORTH TESTING NEXT (not applied):", suggest(all_trades)]
    return "\n".join(out)


def chunks(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Split on line breaks so each piece fits in one Telegram message."""
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            parts, cur, line = parts + ([cur] if cur else []) + [line[:limit]], "", line[limit:]
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    return parts + ([cur] if cur else [])


def main(send: bool = True) -> None:
    from .agents.alerts import send as tg
    text = build()
    print(text)
    if send:
        ok = all([tg(part) for part in chunks(text)])
        print("\n[sent to Telegram]" if ok else "\n[Telegram send FAILED or not configured]")
