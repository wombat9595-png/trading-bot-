"""The firm: every desk running together in one loop. Phase 0 = paper money only.

    cd src && python -m desk run            # firm + dashboard on http://127.0.0.1:8050

Each cycle:
  1. Risk desk manages open positions (rug watch, stops, floors, Verification fade exits)
  2. Alerts desk journals closed trades, fires milestone hold-or-exit alerts
  3. Holder Scout screens new tokens (cheap checks first, forensics only on survivors)
  4. Decision engine + desk routing open new $20 paper positions
  5. State is written to state/desk.json for the dashboard, and open positions to
     state/positions.json so a crash or restart picks them up exactly where they were
  6. News Desk sends the morning briefing once a day

Control from the dashboard (or by editing state/control.json): pause entries, flatten all.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, fields
from datetime import datetime, timezone

from .agents import alerts
from .agents.sentiment_grok import NEUTRAL, score_token
from .config import DEFAULT, Settings
from .data import dexscreener as dx
from .engine import decide
from .paper import build_snapshot
from .risk import Book, Fill, Position
from .screener import screen
from .strategies import assign_desk, desk_has_room, momentum_faded

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STATE = os.path.join(ROOT, "state")
JOURNAL = os.path.join(ROOT, "journal")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, default=str)
    os.replace(tmp, path)


def append_jsonl(path: str, row: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(row, default=str) + "\n")


SEEN_KEEP = 5000          # most recent token addresses remembered across restarts
_POS_SKIP = {"risk", "costs", "fills"}   # config is re-applied from settings on load


def position_to_dict(pos: Position) -> dict:
    d = {f.name: getattr(pos, f.name) for f in fields(Position) if f.name not in _POS_SKIP}
    d["fills"] = [asdict(f) for f in pos.fills]
    return d


def position_from_dict(d: dict, settings: Settings) -> Position:
    known = {f.name for f in fields(Position)} - _POS_SKIP
    pos = Position(risk=settings.risk, costs=settings.costs, **{k: v for k, v in d.items() if k in known})
    pos.fills = [Fill(**f) for f in d.get("fills", [])]
    if not pos.fills:
        raise ValueError("position has no entry fill")
    return pos


class Firm:
    def __init__(self, settings: Settings = DEFAULT, use_grok: bool = False,
                 snapshot_fn=build_snapshot, pair_fn=None, tokens_fn=dx.latest_solana_tokens,
                 sentiment_fn=score_token, send_fn=alerts.send):
        self.s = settings
        self.use_grok = use_grok
        self.snapshot_fn, self.tokens_fn = snapshot_fn, tokens_fn
        self.pair_fn = pair_fn or dx.best_pair
        self.sentiment_fn, self.send = sentiment_fn, send_fn
        self.book = Book(risk=settings.risk)
        self.meta: dict[str, dict] = {}            # symbol -> desk, address, entry liquidity
        self.seen: dict[str, None] = {}            # insertion-ordered set of screened addresses
        self.ms = alerts.MilestoneTracker(settings.milestones_usd)
        self.stats = {"screened": 0, "approved": 0, "rejected": 0, "started": now_iso(), "cycles": 0}
        self.heartbeat: dict[str, str] = {}
        self.last_brief_day = ""
        self.last_manage = 0.0
        self.control: dict = {}
        os.makedirs(STATE, exist_ok=True)
        os.makedirs(JOURNAL, exist_ok=True)
        # carry lifetime realised P&L across restarts so milestones don't re-fire
        self.lifetime_realised = sum(r.get("pnl_usd", 0) for r in self.read_trades())
        self.ms.check(self.lifetime_realised)
        self.restored = self.load_positions()

    # ---------- persistence ----------
    def positions_path(self) -> str:
        return os.path.join(STATE, "positions.json")

    def save_positions(self) -> None:
        """Everything needed to resume after a crash. Atomic write, called every cycle and on every entry."""
        write_json(self.positions_path(), {
            "saved": now_iso(),
            "positions": [{**position_to_dict(pos), "meta": self.meta[sym]}
                          for sym, pos in self.book.open.items() if not pos.closed],
            "seen": list(self.seen)[-SEEN_KEEP:],
            "last_brief_day": self.last_brief_day})

    def load_positions(self) -> int:
        """Reload open positions saved by a previous run. Returns how many were restored.
        A bad record is skipped (and reported), never allowed to stop the firm starting."""
        path = self.positions_path()
        data = read_json(path, None)
        if not isinstance(data, dict):
            if os.path.exists(path):
                print("positions.json unreadable: starting with no open positions")
            return 0
        self.seen.update(dict.fromkeys(a for a in data.get("seen", []) if isinstance(a, str)))
        self.last_brief_day = data.get("last_brief_day") or ""
        n = 0
        for row in data.get("positions", []):
            try:
                meta = row["meta"]
                if not meta.get("address") or not meta.get("desk"):
                    raise ValueError("missing address/desk")
                pos = position_from_dict(row, self.s)
            except Exception as e:
                print("skipped unreadable saved position:", e)
                continue
            if pos.closed or pos.symbol in self.book.open:
                continue
            self.book.open[pos.symbol] = pos
            self.meta[pos.symbol] = meta
            self.seen[meta["address"]] = None
            n += 1
        return n

    # ---------- journal ----------
    def day(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d")

    def trades_path(self) -> str:
        return os.path.join(JOURNAL, "firm_trades.jsonl")

    def decisions_path(self) -> str:
        return os.path.join(JOURNAL, f"decisions_{self.day()}.jsonl")

    def read_trades(self) -> list[dict]:
        try:
            return [json.loads(l) for l in open(self.trades_path())]
        except FileNotFoundError:
            return []

    def today_realised(self) -> float:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return sum(r["pnl_usd"] for r in self.read_trades() if r["closed_utc"].startswith(today))

    # ---------- 1. manage ----------
    def manage(self, flatten: bool) -> None:
        self.heartbeat["risk_desk"] = now_iso()
        self.last_manage = time.time()
        for sym, pos in list(self.book.open.items()):
            m = self.meta[sym]
            ts = time.time()
            if flatten:
                px = self._price(m["address"]) or 0.0
                pos._close(ts, px, "founder flatten")
                continue
            try:
                pair = self._pair(m["address"], m.get("pair"))
            except Exception:
                continue  # network blip is not a rug; try next cycle
            if not pair or not pair.get("priceUsd"):
                pos.on_tick(ts, 0.0, rug_alert="pair vanished")
                continue
            px = float(pair["priceUsd"])
            liq = (pair.get("liquidity") or {}).get("usd")
            rug = None
            if m.get("entry_liq") and liq is not None and liq <= m["entry_liq"] * (1 - self.s.desks.rug_liquidity_drop_pct / 100):
                rug = f"liquidity down {100 * (1 - liq / m['entry_liq']):.0f}% since entry"
            m5 = (pair.get("txns") or {}).get("m5") or {}
            if not rug and m["desk"] == "verification" and momentum_faded(m5.get("buys"), m5.get("sells"), self.s.desks):
                pos._close(ts, px, "verification momentum faded")
                continue
            act = pos.on_tick(ts, px, rug_alert=rug)
            m["last_price"] = px
            if act:
                self.send(f"{sym} [{m['desk']}]: {act} | P&L ${pos.pnl_at(px):+.2f}")

    def _pair(self, addr: str, pool: str | None = None) -> dict | None:
        """Market data for a token, pinned to the pool the position was opened on when we know it,
        so price and liquidity are always compared like with like."""
        return self.pair_fn(addr, pool) if pool else self.pair_fn(addr)

    def _price(self, addr: str) -> float | None:
        try:
            pool = next((m.get("pair") for m in self.meta.values() if m.get("address") == addr), None)
            p = self._pair(addr, pool)
            return float(p["priceUsd"]) if p and p.get("priceUsd") else None
        except Exception:
            return None

    # ---------- 2. settle ----------
    def settle(self) -> None:
        for pos in self.book.settle():
            m = self.meta.pop(pos.symbol, {})
            row = {"closed_utc": now_iso(), "symbol": pos.symbol, "address": m.get("address"), "desk": m.get("desk"),
                   "mode": pos.mode, "hold_s": int(pos.fills[-1].ts - pos.opened_ts), "pnl_usd": round(pos.realised_pnl, 2),
                   "exit_reason": pos.exit_reason, "stake_recovered": pos.stake_recovered,
                   "entry_price": pos.fills[0].price, "fills": len(pos.fills),
                   "conviction": m.get("conviction"), "risk_score": m.get("risk_score"),
                   "hard_fail": m.get("hard_fail")}
            append_jsonl(self.trades_path(), row)
            self.lifetime_realised += pos.realised_pnl
            self.send(f"CLOSED {pos.symbol} [{row['desk']}] {row['exit_reason']} | ${row['pnl_usd']:+.2f}")
            for mile in self.ms.check(self.lifetime_realised):
                self.send(f"🏁 MILESTONE: ${mile:,.0f} realised. Founder decision needed: keep compounding, or withdraw?")

    # ---------- 3+4. scan & enter ----------
    def scan(self) -> None:
        self.heartbeat["holder_scout"] = now_iso()
        try:
            tokens = self.tokens_fn()
        except Exception as e:
            print("discovery error", e)
            return
        for tok in tokens:
            addr = tok["tokenAddress"]
            if addr in self.seen:
                continue
            # Screening one token takes seconds and a fresh feed can hold dozens. Open positions
            # must not wait for the whole scan: stops and rug watch run at least every poll interval.
            if self.book.open and time.time() - self.last_manage >= self.s.desks.poll_seconds:
                self.manage(flatten=False)
                self.settle()
                self.save_positions()
                self.write_state(self.control)
            ok, why = self.book.can_open(day_pnl=self.today_realised())
            if not ok:
                return                    # not marked as seen: it gets screened once there is room
            self.seen[addr] = None
            try:
                snap = self.snapshot_fn(addr, deep=False)        # cheap: DexScreener + mint + top-10
            except Exception as e:
                print("snapshot error", addr, e)
                continue
            if snap is None:
                continue
            self.stats["screened"] += 1
            desk = assign_desk(snap, tok.get("_source", ""), self.s.desks, self.s.screen)
            pre = screen(snap, self.s.screen)
            if desk is None or pre.hard_fail:
                self._log(snap, desk, None, pre, f"no desk" if desk is None else "hard fail on cheap checks")
                continue
            if not desk_has_room(desk, [m["desk"] for m in self.meta.values()], self.s.desks):
                self._log(snap, desk, None, pre, f"{desk} desk full")
                continue
            try:
                full = self.snapshot_fn(addr, deep=True)          # forensics only for survivors
                snap = full or snap
            except Exception:
                pass
            sent = self.sentiment_fn(snap.symbol, addr) if self.use_grok else NEUTRAL
            if self.use_grok:
                self.heartbeat["news_desk"] = now_iso()
            d = decide(snap, sent, self.s.engine, self.s.screen)
            self._log(snap, desk, d, d.screen, "")
            if not d.trade or snap.symbol in self.book.open:
                continue
            px = snap.price_usd or self._price(addr)
            if not px:
                continue
            self.book.open[snap.symbol] = Position.open(snap.symbol, time.time(), px, d.mode, self.s.risk, self.s.costs)
            self.meta[snap.symbol] = {"desk": desk, "address": addr, "pair": snap.details.get("pair"),
                                      "entry_liq": snap.liquidity_usd,
                                      "conviction": d.conviction, "risk_score": d.screen.risk_score, "last_price": px,
                                      "hard_fail": bool(d.screen.hard_fail)}   # audited by the Phase 1 gate
            self.stats["approved"] += 1
            self.save_positions()                 # a crash right after an entry must not lose it
            self.send(f"PAPER BUY {snap.symbol} [{desk}/{d.mode}] conv {d.conviction:.2f} risk {d.screen.risk_score} @ {px:.8g}")

    def _log(self, snap, desk, d, sr, note: str) -> None:
        if d is None or not d.trade:
            self.stats["rejected"] += 1
        append_jsonl(self.decisions_path(), {
            "ts": now_iso(), "address": snap.address, "symbol": snap.symbol, "price_usd": snap.price_usd,
            "desk": desk, "trade": bool(d and d.trade), "mode": d.mode if d else "reject",
            "conviction": d.conviction if d else 0.0, "risk_score": sr.risk_score,
            "reasons": (d.reasons if d else sr.flags) + ([note] if note else []), "unknowns": sr.unknowns})

    # ---------- 5. state ----------
    def write_state(self, control: dict) -> None:
        positions = []
        for sym, pos in self.book.open.items():
            m = self.meta[sym]
            px = m.get("last_price") or pos.fills[0].price
            positions.append({"symbol": sym, "address": m["address"], "desk": m["desk"], "mode": pos.mode,
                              "age_s": int(time.time() - pos.opened_ts), "entry": pos.fills[0].price, "price": px,
                              "pnl_usd": round(pos.pnl_at(px), 2), "floor": pos.floor, "stake_recovered": pos.stake_recovered})
        write_json(os.path.join(STATE, "desk.json"), {
            "updated": now_iso(), "phase": "0 - paper", "paused": control.get("paused", False),
            "grok": self.use_grok, "open": positions, "stats": self.stats,
            "today_realised": round(self.today_realised(), 2), "lifetime_realised": round(self.lifetime_realised, 2),
            "heartbeat": self.heartbeat, "config": {k: asdict(v) for k, v in vars(self.s).items() if hasattr(v, "__dataclass_fields__")}})

    # ---------- loop ----------
    def cycle(self) -> None:
        control = self.control = read_json(os.path.join(STATE, "control.json"), {})
        flatten = control.get("flatten", False)
        self.manage(flatten)
        if flatten:
            write_json(os.path.join(STATE, "control.json"), {**control, "flatten": False, "paused": True})
            self.send("Founder flatten: all paper positions closed, entries paused.")
            control["paused"] = True
        self.settle()
        self.save_positions()
        self.write_state(control)            # dashboard sees exits immediately, before a slow scan
        if not control.get("paused"):
            self.scan()
        self.stats["cycles"] += 1
        self.write_state(control)
        self.maybe_brief()
        self.save_positions()

    def maybe_brief(self) -> None:
        local = datetime.now()
        key = local.strftime("%Y-%m-%d")
        if local.hour >= self.s.desks.brief_hour_local and self.last_brief_day != key:
            self.last_brief_day = key
            try:
                from .news import morning_brief
                self.send(morning_brief(use_grok=self.use_grok))
                self.heartbeat["news_desk"] = now_iso()
            except Exception as e:
                print("brief error", e)

    def run(self, minutes: float | None = None) -> None:
        end = time.time() + minutes * 60 if minutes else None
        self.send(f"Firm online (Phase 0 paper). Desks: Foot in the Door, Verification. Grok: {'on' if self.use_grok else 'off'}."
                  + (f" Restored {self.restored} open position(s) from the last run." if self.restored else ""))
        try:
            while end is None or time.time() < end:
                t0 = time.time()
                try:
                    self.cycle()
                except Exception as e:
                    print("cycle error", e)
                time.sleep(max(1.0, self.s.desks.poll_seconds - (time.time() - t0)))
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Clean stop (Ctrl+C, SIGTERM, end of --minutes): close every position we can price.
        A position with no price right now stays open and saved, and resumes on the next start,
        rather than being booked as a made-up total loss."""
        ts = time.time()
        for sym, pos in list(self.book.open.items()):
            px = self._price(self.meta[sym]["address"])
            if px:
                pos._close(ts, px, "firm shutdown")
        self.settle()
        self.save_positions()
        self.write_state({"paused": True})
        left = len(self.book.open)
        self.send(f"Firm offline. Lifetime realised ${self.lifetime_realised:+.2f}."
                  + (f" {left} position(s) had no price and stay open for the next start." if left else ""))
