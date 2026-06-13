"""Configuration objects for the XAUUSD trading agent.

Everything that tunes behaviour lives here as dataclasses so a strategy run is
fully described by a single ``AgentConfig`` instance (easy to log, serialise and
reproduce).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class Mode(str, Enum):
    """Execution mode. LIVE is the only one that can touch a real account."""

    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


@dataclass
class InstrumentSpec:
    """Contract specification for the traded symbol.

    Defaults describe a typical XAUUSD CFD: 1.00 lot controls 100 oz, so a price
    move of 1.0 USD/oz is worth 100 USD per lot.  Work in *price units* (USD per
    ounce) throughout to avoid pip/point ambiguity that plagues gold.
    """

    symbol: str = "XAUUSD"
    contract_size: float = 100.0          # ounces per 1.0 lot
    money_per_price_per_lot: float = 100.0  # USD P/L per 1.0 price move per 1.0 lot
    min_lot: float = 0.01
    max_lot: float = 100.0
    lot_step: float = 0.01
    # Gold spreads are wide and variable; reject entries when the spread (in price
    # units) is larger than this. 0.5 == 50 cents.
    max_spread: float = 0.50
    # Assumed cost model for simulation, in price units per side.
    sim_spread: float = 0.30
    sim_slippage: float = 0.05
    commission_per_lot: float = 0.0       # round-turn USD per lot (set per broker)


@dataclass
class RiskConfig:
    """Risk-management and position-sizing parameters."""

    risk_per_trade: float = 0.005         # fraction of equity risked per trade (0.5%)
    max_daily_loss: float = 0.03          # stop trading for the day after -3% equity
    max_daily_trades: int = 10            # cap number of entries per day
    max_open_positions: int = 1           # concurrent positions allowed
    min_stop_distance: float = 0.50       # reject signals with a tighter stop (price units)
    # Reward-to-risk used when the strategy has no structural target.
    default_rr: float = 2.0


@dataclass
class StrategyConfig:
    """Smart-Money-Concepts strategy parameters."""

    swing_length: int = 5                 # smc.swing_highs_lows lookback/forward
    # Trailing window (candles) recomputed at each decision point. Keeps the
    # backtest causal (no look-ahead) and bounds compute cost.
    window: int = 400
    require_fvg: bool = True              # demand an FVG overlapping the order block
    require_session: bool = True          # only trade inside the kill-zones below
    sessions: List[str] = field(
        default_factory=lambda: ["London open kill zone", "New York kill zone"]
    )
    time_zone: str = "UTC"
    # How far past the order block to place the protective stop, as a fraction of
    # the order-block height.
    stop_buffer_frac: float = 0.10
    # If True, target the nearest opposing liquidity level; else use default_rr.
    target_liquidity: bool = True
    liquidity_range_percent: float = 0.01
    # Fallback reward:risk used when no structural liquidity target is found.
    default_rr: float = 2.0
    # Minimum order-block strength (smc OB "Percentage") to accept, 0 disables.
    min_ob_strength: float = 0.0


@dataclass
class AgentConfig:
    """Top-level configuration tying every layer together."""

    mode: Mode = Mode.BACKTEST
    starting_equity: float = 10_000.0
    instrument: InstrumentSpec = field(default_factory=InstrumentSpec)
    risk: RiskConfig = field(default_factory=RiskConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
