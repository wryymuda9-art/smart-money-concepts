"""Ready-made XAUUSD (gold) configurations and bundled sample data.

`AgentConfig`'s defaults are already gold (100 oz/lot, $100 per 1.0 price move per
lot). These helpers add timeframe-appropriate tuning and locate the real XAUUSD
sample data shipped under ``tests/test_data/XAUUSD/``.

Bundled real data (for demos/tests only — supply your own for live use):
    XAUUSD_4H.csv   ~2,081 candles, 2020-12 .. 2022-04  (real, with volume)
    XAUUSD_M15.csv  ~3,138 candles, 2025-11 .. 2026-01  (real, day-trade timeframe)
    XAUUSD_M5.csv   ~5,000 candles, 2026-02 .. 2026-03  (real, scalping timeframe)
"""

from __future__ import annotations

import os

from .config import AgentConfig, ManagementConfig, InstrumentSpec, Mode

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests", "test_data", "XAUUSD",
)


def justmarkets_instrument(account_type: str = "standard",
                           sim_spread: float = None,
                           commission_per_lot: float = None,
                           max_lot: float = 50.0) -> InstrumentSpec:
    """XAUUSD instrument spec for the JustMarkets broker.

    Contract specs are standard across JustMarkets accounts (100 oz/lot, 0.01 lot
    step). **Spread and commission depend on the account type** — pass the real
    numbers from your account (Account -> Instrument specs / contract details) via
    ``sim_spread`` (price units, USD per ounce) and ``commission_per_lot`` (USD,
    round-turn). The per-account values below are reasonable placeholders to be
    CONFIRMED, not official quotes.
    """
    defaults = {
        "standard": (0.25, 0.0),   # spread-only, no commission
        "pro": (0.18, 0.0),        # tighter spread, no commission
        "raw": (0.10, 6.0),        # near-zero spread + round-turn commission
        "cent": (0.30, 0.0),       # like standard (cent lots)
    }
    spr, comm = defaults.get(account_type.lower(), defaults["standard"])
    return InstrumentSpec(
        symbol="XAUUSD", contract_size=100.0, money_per_price_per_lot=100.0,
        min_lot=0.01, lot_step=0.01, max_lot=max_lot,
        sim_spread=(spr if sim_spread is None else sim_spread),
        sim_slippage=0.03,
        commission_per_lot=(comm if commission_per_lot is None else commission_per_lot),
        max_spread=0.50,
    )


def sample_data_path(timeframe: str = "M15") -> str:
    """Absolute path to a bundled real XAUUSD sample CSV ('4H', 'M15' or '5M')."""
    name = {
        "4H": "XAUUSD_4H.csv",
        "M15": "XAUUSD_M15.csv", "15M": "XAUUSD_M15.csv",
        "M15_MULTI": "XAUUSD_M15_multi.csv", "MULTI": "XAUUSD_M15_multi.csv",
        "M5": "XAUUSD_M5.csv", "5M": "XAUUSD_M5.csv",
    }.get(timeframe.upper())
    if name is None:
        raise ValueError("timeframe must be one of 4H, M15, M15_MULTI, M5")
    return os.path.join(_DATA_DIR, name)


def xauusd_config(mode: Mode = Mode.BACKTEST, timeframe: str = "5M",
                  starting_equity: float = 10_000.0,
                  with_management: bool = False,
                  management_style: str = "runner",
                  broker: str = "justmarkets", account_type: str = "pro",
                  instrument=None) -> AgentConfig:
    """A sensible XAUUSD config tuned for the given timeframe.

    * **5M / scalping** — tight structure, kill-zone timing on, FVG confluence on.
    * **15M / day-trade** — slightly larger structure.
    * **1H/4H / swing** — larger structure, sessions off (intraday concept).

    ``with_management=True`` adds in-trade management. ``management_style``:

    * ``"runner"`` *(default, recommended)* — **let winners run**: no partial, trail
      3R behind the peak, far target. On 13-month multi-regime M15 this doubled the
      out-of-sample return vs the conservative combo (walk-forward +5.9% vs +2.6%,
      PF 1.70, ~2% drawdown) — a *validated* edge improvement. Lower win rate (~40%),
      bigger winners.
    * ``"balanced"`` — take half off at +1R and trail the rest 1.5R (higher win rate,
      smaller average winner).
    """
    cfg = AgentConfig(mode=mode, starting_equity=starting_equity)
    tf = timeframe.upper()

    # broker cost model
    if instrument is not None:
        cfg.instrument = instrument
    elif broker and broker.lower() == "justmarkets":
        cfg.instrument = justmarkets_instrument(account_type)

    if with_management:
        if management_style == "balanced":
            cfg.management = ManagementConfig(
                partial_enabled=True, partial_at_r=1.0, partial_fraction=0.5,
                partial_then_breakeven=False,
                trailing_enabled=True, trailing_at_r=1.0, trailing_distance_r=1.5,
            )
        else:  # "runner" — let winners run (validated best)
            cfg.management = ManagementConfig(
                partial_enabled=False,
                trailing_enabled=True, trailing_at_r=1.0, trailing_distance_r=3.0,
            )
            cfg.strategy.default_rr = 6.0

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
