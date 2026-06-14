"""Ready-made XAUUSD (gold) configurations and bundled sample data.

`AgentConfig`'s defaults are already gold (100 oz/lot, $100 per 1.0 price move per
lot). These helpers add timeframe-appropriate tuning and locate the real XAUUSD
sample data shipped under ``tests/test_data/XAUUSD/``.

Bundled real data (for demos/tests only — supply your own for live use):
    XAUUSD_4H.csv   ~2,081 candles, 2020-12 .. 2022-04  (real, with volume)
    XAUUSD_5M.csv   ~551 candles,  2020-02-03..04        (real, scalping timeframe)
"""

from __future__ import annotations

import os

from .config import AgentConfig, Mode

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests", "test_data", "XAUUSD",
)


def sample_data_path(timeframe: str = "4H") -> str:
    """Absolute path to a bundled real XAUUSD sample CSV ('4H' or '5M')."""
    name = {"4H": "XAUUSD_4H.csv", "5M": "XAUUSD_5M.csv"}.get(timeframe.upper())
    if name is None:
        raise ValueError("timeframe must be '4H' or '5M'")
    return os.path.join(_DATA_DIR, name)


def xauusd_config(mode: Mode = Mode.BACKTEST, timeframe: str = "5M",
                  starting_equity: float = 10_000.0) -> AgentConfig:
    """A sensible XAUUSD config tuned for the given timeframe.

    * **5M / scalping** — tight structure, kill-zone timing on, FVG confluence on.
    * **15M / day-trade** — slightly larger structure.
    * **1H/4H / swing** — larger structure, sessions off (intraday concept).
    """
    cfg = AgentConfig(mode=mode, starting_equity=starting_equity)
    tf = timeframe.upper()

    cfg.risk.risk_per_trade = 0.005          # 0.5% per trade
    cfg.risk.max_daily_loss = 0.03           # halt the day at -3%
    cfg.risk.max_daily_trades = 8
    cfg.risk.min_stop_distance = 0.5         # >= 50 cents of gold

    if tf in ("1M", "M1", "5M", "M5"):
        cfg.strategy.swing_length = 5
        cfg.strategy.window = 300
        cfg.strategy.require_session = True
        cfg.strategy.require_fvg = True
        cfg.strategy.sessions = ["London open kill zone", "New York kill zone"]
    elif tf in ("15M", "M15", "30M", "M30"):
        cfg.strategy.swing_length = 6
        cfg.strategy.window = 250
        cfg.strategy.require_session = True
        cfg.strategy.require_fvg = True
    else:  # 1H / 4H / swing
        cfg.strategy.swing_length = 5
        cfg.strategy.window = 200
        cfg.strategy.require_session = False   # sessions are intraday-only
        cfg.strategy.require_fvg = True
    return cfg
