"""Historical OHLC for the equities / ETF / commodities mandate (backtesting only).

Uses Yahoo's public chart endpoint. Unofficial and rate-limited: fine for research,
not for live execution. Hourly data goes back ~730 days.
"""
from __future__ import annotations

import requests

from ..structure import Candle

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"


def fetch(symbol: str, interval: str = "1h", range_: str = "730d") -> list[Candle]:
    r = requests.get(URL.format(sym=symbol), params={"interval": interval, "range": range_},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for ts, o, h, l, c, v in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"], q["volume"]):
        if None in (o, h, l, c):
            continue
        out.append(Candle(float(ts), o, h, l, c, float(v or 0)))
    return out
