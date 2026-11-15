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


def main(hours: float) -> None:
    cutoff = time.time() - hours * 3600
    rows = []
    for f in glob.glob(os.path.join(JOURNAL, "decisions_*.jsonl")):
        for line in open(f):
            r = json.loads(line)
            if r.get("price_usd") and datetime.fromisoformat(r["ts"]).timestamp() <= cutoff:
                rows.append(r)
    if not rows:
        print(f"No priced decisions older than {hours}h yet. Run the paper desk first.")
        return
    prices = {}
    for r in rows:
        if r["address"] not in prices:
            try:
                prices[r["address"]] = dx.price(r["address"])
            except Exception:
                prices[r["address"]] = None
            time.sleep(0.25)
    s = score(rows, prices)
    for k, (c, n) in s.items():
        print(f"{k:8}: {c}/{n} crashed 90%+ ({100 * c / n:.0f}%)" if n else f"{k}: none")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24)
    main(ap.parse_args().hours)
