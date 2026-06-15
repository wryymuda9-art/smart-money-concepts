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

import pandas as pd

from .config import AgentConfig, Mode
from .data import load_csv
from .backtest import Backtester


def _build_config(args) -> AgentConfig:
    # a --config file (yaml/json) is the base; only explicitly-passed flags override it
    if getattr(args, "config", None):
        from .configio import load_config
        cfg = load_config(args.config)
        cfg.mode = Mode.BACKTEST
    else:
        cfg = AgentConfig(mode=Mode.BACKTEST)

    def ov(value, default):
        """Use the flag value if given, else the config/default already in place."""
        return default if value is None else value

    cfg.starting_equity = ov(getattr(args, "equity", None), cfg.starting_equity)
    cfg.instrument.symbol = ov(getattr(args, "symbol", None), cfg.instrument.symbol)
    cfg.risk.risk_per_trade = ov(getattr(args, "risk_per_trade", None), cfg.risk.risk_per_trade)
    cfg.risk.max_daily_loss = ov(getattr(args, "max_daily_loss", None), cfg.risk.max_daily_loss)
    cfg.risk.max_daily_trades = ov(getattr(args, "max_daily_trades", None), cfg.risk.max_daily_trades)
    cfg.strategy.swing_length = ov(getattr(args, "swing_length", None), cfg.strategy.swing_length)
    cfg.strategy.window = ov(getattr(args, "window", None), cfg.strategy.window)
    cfg.strategy.require_fvg = ov(getattr(args, "require_fvg", None), cfg.strategy.require_fvg)
    cfg.strategy.require_session = ov(getattr(args, "require_session", None), cfg.strategy.require_session)
    return cfg


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="xauusd_agent")
    sub = parser.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="run a historical backtest")
    bt.add_argument("--csv", required=True, help="OHLCV csv (MT5/generic export)")
    bt.add_argument("--config", default=None, help="YAML/JSON config file (base; flags override)")
    # overrides default to None so a --config file is only changed by flags you pass
    bt.add_argument("--symbol", default=None)
    bt.add_argument("--equity", type=float, default=None)
    bt.add_argument("--risk-per-trade", type=float, default=None)
    bt.add_argument("--max-daily-loss", type=float, default=None)
    bt.add_argument("--max-daily-trades", type=int, default=None)
    bt.add_argument("--swing-length", type=int, default=None)
    bt.add_argument("--window", type=int, default=None)
    bt.add_argument("--require-fvg", dest="require_fvg", action="store_const", const=True, default=None)
    bt.add_argument("--no-require-fvg", dest="require_fvg", action="store_const", const=False)
    bt.add_argument("--require-session", dest="require_session", action="store_const", const=True, default=None)
    bt.add_argument("--no-require-session", dest="require_session", action="store_const", const=False)
    bt.add_argument("--progress-every", type=int, default=0)
    bt.add_argument("--report-html", default=None, help="write a performance tearsheet (HTML)")
    bt.add_argument("--report-png", default=None, help="write a performance tearsheet (PNG)")

    dash = sub.add_parser("dashboard", help="replay candles into a live SMC dashboard")
    dash.add_argument("--csv", required=True, help="OHLCV csv (MT5/generic export)")
    dash.add_argument("--symbol", default="XAUUSD")
    dash.add_argument("--equity", type=float, default=10_000.0)
    dash.add_argument("--risk-per-trade", type=float, default=0.005)
    dash.add_argument("--max-daily-loss", type=float, default=0.03)
    dash.add_argument("--max-daily-trades", type=int, default=10)
    dash.add_argument("--swing-length", type=int, default=5)
    dash.add_argument("--window", type=int, default=400)
    dash.add_argument("--require-fvg", dest="require_fvg", action="store_true", default=True)
    dash.add_argument("--no-require-fvg", dest="require_fvg", action="store_false")
    dash.add_argument("--require-session", dest="require_session", action="store_true", default=False)
    dash.add_argument("--html", default="xauusd_dashboard.html", help="output HTML path")
    dash.add_argument("--png", default=None, help="also write a PNG snapshot here")
    dash.add_argument("--plot-window", type=int, default=120, help="candles shown on chart")
    dash.add_argument("--refresh-secs", type=int, default=2, help="HTML auto-refresh interval")
    dash.add_argument("--max-candles", type=int, default=None, help="limit replay length")

    live = sub.add_parser("live", help="run live/paper against a MetaTrader 5 terminal")
    live.add_argument("--symbol", default="XAUUSD")
    live.add_argument("--timeframe", default="M5")
    live.add_argument("--equity", type=float, default=10_000.0)
    live.add_argument("--risk-per-trade", type=float, default=0.005)
    live.add_argument("--max-daily-loss", type=float, default=0.03)
    live.add_argument("--max-daily-trades", type=int, default=10)
    live.add_argument("--swing-length", type=int, default=5)
    live.add_argument("--window", type=int, default=400)
    live.add_argument("--require-fvg", dest="require_fvg", action="store_true", default=True)
    live.add_argument("--no-require-fvg", dest="require_fvg", action="store_false")
    live.add_argument("--require-session", dest="require_session", action="store_true", default=True)
    live.add_argument("--no-require-session", dest="require_session", action="store_false")
    live.add_argument("--execute", action="store_true",
                      help="ACTUALLY place orders via MT5 (default: paper, no orders)")
    live.add_argument("--login", type=int, default=None)
    live.add_argument("--password", default=None)
    live.add_argument("--server", default=None)
    live.add_argument("--html", default="xauusd_dashboard.html")
    live.add_argument("--plot-window", type=int, default=120)

    dl = sub.add_parser("download", help="download history from MT5 to a CSV")
    dl.add_argument("--symbol", default="XAUUSD")
    dl.add_argument("--timeframe", default="M5")
    dl.add_argument("--start", required=True, help="e.g. 2024-01-01")
    dl.add_argument("--end", required=True, help="e.g. 2024-06-01")
    dl.add_argument("--out", required=True, help="output csv path")
    dl.add_argument("--login", type=int, default=None)
    dl.add_argument("--password", default=None)
    dl.add_argument("--server", default=None)

    for name, helptext in (("optimize", "grid-search parameters on data"),
                           ("walkforward", "walk-forward (out-of-sample) validation")):
        sp = sub.add_parser(name, help=helptext)
        grp = sp.add_mutually_exclusive_group(required=True)
        grp.add_argument("--csv", help="OHLCV csv")
        grp.add_argument("--timeframe", help="use bundled XAUUSD sample: 4H or 5M")
        sp.add_argument("--equity", type=float, default=10_000.0)
        sp.add_argument("--window", type=int, default=150)
        sp.add_argument("--objective", default="profit_factor",
                        help="metric to optimise (profit_factor, avg_R, sharpe, expectancy_usd)")
        sp.add_argument("--top", type=int, default=10, help="rows to show (optimize)")
        sp.add_argument("--splits", type=int, default=3, help="walk-forward folds")
        sp.add_argument("--out", default=None, help="save full results table to csv")

    args = parser.parse_args(argv)

    if args.command == "backtest":
        cfg = _build_config(args)
        ohlc = load_csv(args.csv)
        result = Backtester(cfg).run(ohlc, progress_every=args.progress_every)
        print(result)
        print(json.dumps(result.summary(), indent=2))
        if args.report_html or args.report_png:
            from .report import save_report
            save_report(result, html_path=args.report_html, png_path=args.report_png,
                        title=f"{cfg.instrument.symbol} · SMC Agent")
            print(f"report -> {args.report_html or ''} {args.report_png or ''}".strip())
        return 0

    if args.command == "dashboard":
        from .viz import LiveDashboard, DashboardConfig
        from .live import run_live_replay

        cfg = _build_config(args)
        ohlc = load_csv(args.csv)
        dcfg = DashboardConfig(swing_length=args.swing_length,
                               show_sessions=args.require_session)
        dashboard = LiveDashboard(html_path=args.html, cfg=dcfg,
                                  refresh_secs=args.refresh_secs)
        run_live_replay(cfg, ohlc, dashboard, plot_window=args.plot_window,
                        png_path=args.png, max_candles=args.max_candles)
        return 0

    if args.command == "live":
        from .feed import Mt5DataFeed
        from .broker import Mt5Broker
        from .viz import LiveDashboard, DashboardConfig
        from .live import run_live

        cfg = _build_config(args)
        cfg.mode = Mode.LIVE if args.execute else Mode.PAPER
        cfg.instrument.symbol = args.symbol

        feed = Mt5DataFeed(symbol=args.symbol, timeframe=args.timeframe,
                           login=args.login, password=args.password, server=args.server)
        feed.connect()

        broker = None
        if args.execute:
            broker = Mt5Broker(cfg.instrument, login=args.login,
                               password=args.password, server=args.server)
            broker.connect()
            print("LIVE execution enabled — orders WILL be sent to MT5.")
        else:
            print("PAPER mode — reading live MT5 data, simulating fills (no orders sent).")

        dashboard = LiveDashboard(html_path=args.html,
                                  cfg=DashboardConfig(swing_length=args.swing_length,
                                                      show_sessions=args.require_session))
        try:
            run_live(cfg, feed, dashboard, broker=broker, plot_window=args.plot_window)
        finally:
            feed.shutdown()
        return 0

    if args.command == "download":
        from .feed import Mt5DataFeed
        feed = Mt5DataFeed(symbol=args.symbol, timeframe=args.timeframe,
                           login=args.login, password=args.password, server=args.server)
        feed.connect()
        try:
            df = feed.download(args.start, args.end, args.out)
        finally:
            feed.shutdown()
        print(f"saved {len(df)} candles to {args.out}")
        return 0

    if args.command in ("optimize", "walkforward"):
        from .presets import xauusd_config, sample_data_path
        from .research import sweep, walk_forward

        base = xauusd_config(mode=Mode.BACKTEST, timeframe=args.timeframe or "4H",
                             starting_equity=args.equity)
        base.strategy.window = args.window
        path = args.csv or sample_data_path(args.timeframe)
        ohlc = load_csv(path)
        print(f"data: {len(ohlc)} candles {ohlc.index.min()} -> {ohlc.index.max()}")

        # a sensible default search space for XAUUSD structure/risk
        grid = {
            "strategy.swing_length": [4, 6, 8],
            "strategy.require_fvg": [True, False],
            "strategy.default_rr": [2.0, 3.0],
        }

        if args.command == "optimize":
            df = sweep(base, ohlc, grid, sort_by=args.objective, verbose=True)
            if args.out:
                df.to_csv(args.out, index=False)
            with pd.option_context("display.max_columns", None, "display.width", 200):
                print(df.head(args.top).to_string(index=False))
            return 0

        wf = walk_forward(base, ohlc, grid, n_splits=args.splits,
                          objective=args.objective, verbose=True)
        print(wf)
        print(json.dumps(wf.summary(), indent=2, default=str))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
