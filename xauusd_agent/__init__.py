"""
xauusd_agent
============

An algorithmic trading agent for XAUUSD (gold) day-trading and scalping built on
top of the `smartmoneyconcepts` (ICT / Smart Money Concepts) indicator library.

The agent is intentionally split into independent, testable layers:

    DataFeed  ->  Strategy (smc)  ->  RiskManager  ->  Broker
                         |                |
                         v                v
                     Signal           Order / Position

Run modes (see `config.Mode`):

    BACKTEST : replay historical candles through the full pipeline.
    PAPER    : same logic, simulated fills, intended for forward-testing live data.
    LIVE     : route orders to a real broker (MetaTrader 5). OFF by default and
               only reachable by explicitly setting Mode.LIVE.

NOTHING in this package places a real order unless you construct an `Mt5Broker`
and run the agent with `Mode.LIVE`. The default everywhere is simulation.
"""

from .config import AgentConfig, RiskConfig, StrategyConfig, InstrumentSpec, Mode
from .strategy import SMCStrategy, Signal, Side
from .risk import RiskManager
from .broker import SimBroker, Order, Position, OrderType
from .backtest import Backtester, BacktestResult
from .agent import TradingAgent
from .viz import LiveDashboard, DashboardConfig, build_figure
from .live import run_live_replay

__all__ = [
    "AgentConfig",
    "RiskConfig",
    "StrategyConfig",
    "InstrumentSpec",
    "Mode",
    "SMCStrategy",
    "Signal",
    "Side",
    "RiskManager",
    "SimBroker",
    "Order",
    "Position",
    "OrderType",
    "Backtester",
    "BacktestResult",
    "TradingAgent",
    "LiveDashboard",
    "DashboardConfig",
    "build_figure",
    "run_live_replay",
]

__version__ = "0.1.0"
