"""Rug-catch scoreboard: the honest marketing number.

For every token the screener judged at least `hours` ago, compare today's price with the
price at decision time. Reports what share of FLAGGED tokens crashed 90%+ versus the share
of PASSED tokens that did. A screener only has value if the first number is clearly higher.

cd src && python -m desk.tracker --hours 24
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import time
from datetime import datetime

from .data import dexscreener as dx

JOURNAL = os.path.join(os.path.dirname(__file__), "..", "..", "journal")


def crashed(then: float, now: float | None, pct: float = 90.0) -> bool:
    return now is None or now <= then * (1 - pct / 100)


def score(rows: list[dict], prices: dict[str, float | None]) -> dict:
    out = {"flagged": [0, 0], "passed": [0, 0]}   # [crashed, total]
    for r in rows:
        bucket = "flagged" if r["mode"] == "reject" or r["risk_score"] >= 40 else "passed"
        out[bucket][1] += 1
        out[bucket][0] += crashed(r["price_usd"], prices.get(r["address"]))
    return out


MAX_TOKENS = 600     # cap on price lookups per run, so the daily report always finishes


def load_rows(hours: float) -> list[dict]:
    cutoff = time.time() - hours * 3600
    rows = []
    for f in sorted(glob.glob(os.path.join(JOURNAL, "decisions_*.jsonl"))):
        for line in open(f):
            r = json.loads(line)
            if r.get("price_usd") and datetime.fromisoformat(r["ts"]).timestamp() <= cutoff:
                rows.append(r)
    return rows


def render(s: dict, hours: float, sampled_from: int | None = None) -> str:
    out = [f"RUG-CATCH SCOREBOARD (tokens judged {hours:.0f}h+ ago)"]
    for k, (c, n) in s.items():
        out.append(f"{k:8}: {c}/{n} crashed 90%+ ({100 * c / n:.0f}%)" if n else f"{k:8}: none yet")
    if sampled_from:
        out.append(f"(most recent {MAX_TOKENS} of {sampled_from} tokens)")
    return "\n".join(out)


def run(hours: float = 24) -> str:
    rows = load_rows(hours)
    if not rows:
        return f"No priced decisions older than {hours:.0f}h yet. Run the paper desk first."
    first: dict[str, dict] = {}
    for r in rows:
        first.setdefault(r["address"], r)             # judge each token once, at its first decision
    total = len(first)
    rows = list(first.values())[-MAX_TOKENS:]
    prices = {}
    for r in rows:
        try:
            prices[r["address"]] = dx.price(r["address"])
        except Exception:
            continue                                  # no answer is not a crash: leave it out
        time.sleep(0.25)
    rows = [r for r in rows if r["address"] in prices]
    return render(score(rows, prices), hours, total if total > MAX_TOKENS else None)


def main(hours: float) -> None:
    print(run(hours))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24)
    main(ap.parse_args().hours)
