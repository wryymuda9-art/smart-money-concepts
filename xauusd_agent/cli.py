"""Command-line entry point for backtesting the XAUUSD agent.

Examples
--------
Backtest on an MT5 csv export::

    python -m xauusd_agent.cli backtest --csv path/to/XAUUSD_M5.csv

Tune risk / strategy::

    python -m xauusd_agent.cli backtest --csv data.csv \
        --risk-per-trade 0.0025 --swing-length 7 --no-require-fvg
"""

from __future__ import annotations

import argparse
import json

from .config import AgentConfig, Mode
from .data import load_csv
from .backtest import Backtester


def _build_config(args) -> AgentConfig:
    cfg = AgentConfig(mode=Mode.BACKTEST, starting_equity=args.equity)
    cfg.instrument.symbol = args.symbol
    cfg.risk.risk_per_trade = args.risk_per_trade
    cfg.risk.max_daily_loss = args.max_daily_loss
    cfg.risk.max_daily_trades = args.max_daily_trades
    cfg.strategy.swing_length = args.swing_length
    cfg.strategy.window = args.window
    cfg.strategy.require_fvg = args.require_fvg
    cfg.strategy.require_session = args.require_session
    return cfg


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="xauusd_agent")
    sub = parser.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="run a historical backtest")
    bt.add_argument("--csv", required=True, help="OHLCV csv (MT5/generic export)")
    bt.add_argument("--symbol", default="XAUUSD")
    bt.add_argument("--equity", type=float, default=10_000.0)
    bt.add_argument("--risk-per-trade", type=float, default=0.005)
    bt.add_argument("--max-daily-loss", type=float, default=0.03)
    bt.add_argument("--max-daily-trades", type=int, default=10)
    bt.add_argument("--swing-length", type=int, default=5)
    bt.add_argument("--window", type=int, default=400)
    bt.add_argument("--require-fvg", dest="require_fvg", action="store_true", default=True)
    bt.add_argument("--no-require-fvg", dest="require_fvg", action="store_false")
    bt.add_argument("--require-session", dest="require_session", action="store_true", default=True)
    bt.add_argument("--no-require-session", dest="require_session", action="store_false")
    bt.add_argument("--progress-every", type=int, default=0)

    args = parser.parse_args(argv)

    if args.command == "backtest":
        cfg = _build_config(args)
        ohlc = load_csv(args.csv)
        result = Backtester(cfg).run(ohlc, progress_every=args.progress_every)
        print(result)
        print(json.dumps(result.summary(), indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
