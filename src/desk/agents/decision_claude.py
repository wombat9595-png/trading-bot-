"""Optional Claude second opinion on a trade the deterministic engine already approved.

Claude can VETO, never force a trade. Off by default (EngineConfig.use_llm_review)
because a model call adds seconds to entry; best used for slower decisions (Phase 2
event trades, the founder hold-or-exit alerts, post-trade reviews).

Fails CLOSED: no key, API error, refusal or unparseable output -> veto.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

SYSTEM = """You are the risk officer on a Solana memecoin desk. A rules engine has approved a
$20 paper trade. Your only job is to catch what the rules missed: signs this is a rug,
a bundled launch, wash-traded volume, or a narrative that has already peaked.
Most new memecoins go to zero; approve only if the evidence is genuinely clean.
Be brief and specific."""

SCHEMA = {
    "type": "object",
    "properties": {
        "approve": {"type": "boolean"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["approve", "confidence", "reason"],
    "additionalProperties": False,
}


@dataclass
class Review:
    approve: bool
    reason: str
    confidence: float = 0.0


def review(evidence: dict, model: str = "claude-opus-5-5") -> Review:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return Review(False, "no ANTHROPIC_API_KEY: LLM review unavailable, fail closed")
    try:
        import anthropic
    except ImportError:
        return Review(False, "anthropic SDK not installed (pip install -e '.[ai]')")

    client = anthropic.Anthropic(timeout=30.0)
    try:
        resp = client.beta.messages.create(
            model=model,
            max_tokens=1024,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": "Trade evidence:\n" + json.dumps(evidence, indent=1, default=str)}],
        )
    except anthropic.APIConnectionError as e:
        return Review(False, f"connection error: {e}")
    except anthropic.APIStatusError as e:
        return Review(False, f"API error {e.status_code}")

    if resp.stop_reason == "refusal":
        return Review(False, "model declined to review")
    text = "".join(b.text for b in resp.content if b.type == "text")
    try:
        d = json.loads(text)
        return Review(bool(d["approve"]), str(d["reason"]), float(d["confidence"]))
    except (ValueError, KeyError):
        return Review(False, "unparseable review output")
