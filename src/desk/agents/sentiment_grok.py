"""News Desk / sentiment agent: Grok with live X search.

Why Grok here: it is the only model with first-party, real-time access to X, which is
where memecoin narrative lives. Verified API shape (docs.x.ai, Nov 2026):
POST https://api.x.ai/v1/responses, tools=[{"type": "x_search"}], model "grok-4.7".

Fails safe: any error returns a neutral score (0.5) flagged as unavailable, so a dead
sentiment feed can never push a trade over the line on its own.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import requests

URL = "https://api.x.ai/v1/responses"
MODEL = os.getenv("XAI_MODEL", "grok-4.7")

PROMPT = """You are a crypto sentiment analyst. Search X for posts about the Solana token
${symbol} (contract {address}) from the last 6 hours.

Judge ORGANIC interest only. Discount: bot-like repeated posts, paid-shill language,
brand-new accounts, giveaways, and posts by the deployer. Count distinct real accounts.

Reply with ONLY a JSON object, no prose:
{{"score": <0.0-1.0, 0.5 = neutral/no signal>, "organic_accounts": <int>,
  "shill_ratio": <0.0-1.0>, "narrative": "<10 words max>", "red_flags": ["..."]}}"""


@dataclass
class Sentiment:
    score: float
    available: bool
    narrative: str = ""
    organic_accounts: int = 0
    shill_ratio: float = 0.0
    red_flags: tuple[str, ...] = ()


NEUTRAL = Sentiment(0.5, False)


def _extract_text(body: dict) -> str:
    if body.get("output_text"):
        return body["output_text"]
    parts = []
    for item in body.get("output", []):
        for c in item.get("content", []) or []:
            if c.get("type") in ("output_text", "text"):
                parts.append(c.get("text", ""))
    return "".join(parts)


def score_token(symbol: str, address: str, timeout: float = 60) -> Sentiment:
    key = os.getenv("XAI_API_KEY")
    if not key:
        return NEUTRAL
    try:
        r = requests.post(URL, timeout=timeout, headers={"Authorization": f"Bearer {key}"}, json={
            "model": MODEL,
            "input": [{"role": "user", "content": PROMPT.format(symbol=symbol, address=address)}],
            "tools": [{"type": "x_search"}],
        })
        r.raise_for_status()
        text = _extract_text(r.json())
        d = json.loads(text[text.find("{"): text.rfind("}") + 1])
        return Sentiment(
            score=min(1.0, max(0.0, float(d.get("score", 0.5)))),
            available=True,
            narrative=str(d.get("narrative", ""))[:80],
            organic_accounts=int(d.get("organic_accounts", 0)),
            shill_ratio=float(d.get("shill_ratio", 0.0)),
            red_flags=tuple(map(str, d.get("red_flags", [])))[:5],
        )
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return NEUTRAL
