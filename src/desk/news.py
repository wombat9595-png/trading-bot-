"""News Desk: the founder's morning briefing (TSB section 4), sent to Telegram.

Desk numbers from the journal + (if XAI_API_KEY is set) Grok's read of X: hot narratives,
whale and top-trader chatter, catalysts.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from .agents.sentiment_grok import ask

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
JOURNAL = os.path.join(ROOT, "journal")

GROK_BRIEF = """You are the overnight analyst for a Solana memecoin desk. Using X posts from the
last 12 hours, give a morning briefing in under 120 words:
1. Top 3 narratives driving Solana memecoins right now (one line each).
2. Any widely discussed rugs or scams to avoid (name + one line).
3. Catalysts in the next 24h (listings, launches, macro events).
Plain text, no hype, flag anything that looks like coordinated shilling."""


def desk_stats(hours: float = 24) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    trades = []
    try:
        for line in open(os.path.join(JOURNAL, "firm_trades.jsonl")):
            r = json.loads(line)
            if datetime.fromisoformat(r["closed_utc"]) >= cutoff:
                trades.append(r)
    except FileNotFoundError:
        pass
    pnl = [t["pnl_usd"] for t in trades]
    by_desk: dict[str, list[float]] = {}
    for t in trades:
        by_desk.setdefault(t.get("desk") or "?", []).append(t["pnl_usd"])
    return {"n": len(pnl), "wins": sum(p > 0 for p in pnl), "pnl": round(sum(pnl), 2),
            "best": max(trades, key=lambda t: t["pnl_usd"], default=None),
            "worst": min(trades, key=lambda t: t["pnl_usd"], default=None),
            "by_desk": {k: (len(v), round(sum(v), 2)) for k, v in by_desk.items()}}


def morning_brief(use_grok: bool = True) -> str:
    s = desk_stats()
    lines = [f"☀️ MORNING BRIEF {datetime.now().strftime('%a %d %b')}", "",
             f"Last 24h: {s['n']} paper trades, {s['wins']} winners, realised ${s['pnl']:+.2f}"]
    for desk, (n, p) in s["by_desk"].items():
        lines.append(f"  {desk}: {n} trades, ${p:+.2f}")
    if s["best"]:
        lines.append(f"Best: {s['best']['symbol']} ${s['best']['pnl_usd']:+.2f} ({s['best']['exit_reason']})")
        lines.append(f"Worst: {s['worst']['symbol']} ${s['worst']['pnl_usd']:+.2f} ({s['worst']['exit_reason']})")
    if use_grok:
        g = ask(GROK_BRIEF)
        lines += ["", "X intel (Grok):", g if g else "unavailable (no XAI_API_KEY or API error)"]
    return "\n".join(lines)


if __name__ == "__main__":
    print(morning_brief())
