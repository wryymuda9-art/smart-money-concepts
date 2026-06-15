"""Trade journal and run-state persistence.

Live trading needs two things the in-memory backtester doesn't:

* an **audit trail** — every signal, fill and exit written to disk so you can
  reconstruct what the bot did and why (``TradeJournal``, append-only JSONL);
* **state recovery** — if the process restarts mid-session, the day's loss/trade
  counters must survive so risk limits keep holding (``save_state`` /
  ``load_state`` for a ``RiskManager``).

Both are plain JSON on disk — no database, no dependencies.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Any, Dict, Optional


def _jsonable(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if hasattr(v, "item"):          # numpy scalars
        try:
            return v.item()
        except Exception:
            return str(v)
    return v


class TradeJournal:
    """Append-only JSONL log of agent events (entries, exits, errors, notes)."""

    def __init__(self, path: str = "xauusd_journal.jsonl"):
        self.path = path

    def log(self, event: str, when=None, **fields) -> Dict[str, Any]:
        record = {
            "ts": _jsonable(when) if when is not None else datetime.utcnow().isoformat(),
            "event": event,
            **{k: _jsonable(v) for k, v in fields.items()},
        }
        with open(self.path, "a") as fh:
            fh.write(json.dumps(record) + "\n")
        return record

    def read(self) -> list:
        if not os.path.exists(self.path):
            return []
        with open(self.path) as fh:
            return [json.loads(line) for line in fh if line.strip()]


def save_state(risk_manager, path: str = "xauusd_state.json") -> None:
    """Persist a RiskManager's intraday counters so a restart resumes safely."""
    state = {
        "day": risk_manager._day.isoformat() if risk_manager._day else None,
        "day_start_equity": risk_manager._day_start_equity,
        "trades_today": risk_manager._trades_today,
        "halted_today": risk_manager._halted_today,
    }
    with open(path, "w") as fh:
        json.dump(state, fh, indent=2)


def load_state(risk_manager, path: str = "xauusd_state.json") -> bool:
    """Restore counters saved by :func:`save_state`. Returns True if loaded."""
    if not os.path.exists(path):
        return False
    with open(path) as fh:
        state = json.load(fh)
    risk_manager._day = date.fromisoformat(state["day"]) if state.get("day") else None
    risk_manager._day_start_equity = state.get("day_start_equity", risk_manager.starting_equity)
    risk_manager._trades_today = state.get("trades_today", 0)
    risk_manager._halted_today = state.get("halted_today", False)
    return True
