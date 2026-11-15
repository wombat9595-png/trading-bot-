"""Alerts desk: Telegram notifications + founder escalation at profit milestones."""
from __future__ import annotations

import os

import requests


def send(text: str) -> bool:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print(f"[alert] {text}")
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text}, timeout=10)
        return r.ok
    except requests.RequestException:
        return False


class MilestoneTracker:
    """Fires once per milestone as cumulative realised P&L crosses it."""

    def __init__(self, milestones: tuple[float, ...]):
        self.pending = sorted(milestones)

    def check(self, realised_total: float) -> list[float]:
        hit = [m for m in self.pending if realised_total >= m]
        self.pending = [m for m in self.pending if m not in hit]
        return hit
