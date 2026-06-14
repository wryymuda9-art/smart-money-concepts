"""End-to-end XAUUSD demo on the bundled REAL gold data.

    SMC_CREDIT=0 python -m xauusd_agent.examples.run_xauusd            # 4H backtest
    SMC_CREDIT=0 python -m xauusd_agent.examples.run_xauusd --dashboard out.html

Backtests the SMC agent on real XAUUSD candles and (optionally) renders the live
dashboard. The bundled data is for demonstration only — point ``--csv`` at your
own MT5 export (or use the `download` CLI) for real evaluation.
"""

from __future__ import annotations

import argparse
import json

from ..config import Mode
from ..data import load_csv
from ..presets import xauusd_config, sample_data_path
from ..backtest import Backtester


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="XAUUSD SMC agent demo on real gold data")
    p.add_argument("--timeframe", default="4H", help="bundled sample: 4H or 5M")
    p.add_argument("--csv", default=None, help="use your own OHLCV csv instead")
    p.add_argument("--dashboard", default=None, help="also write a dashboard HTML here")
    p.add_argument("--png", default=None, help="also write a dashboard PNG here")
    args = p.parse_args(argv)

    cfg = xauusd_config(mode=Mode.BACKTEST, timeframe=args.timeframe)
    path = args.csv or sample_data_path(args.timeframe)
    ohlc = load_csv(path)
    print(f"XAUUSD {args.timeframe}: {len(ohlc)} candles "
          f"{ohlc.index.min()} -> {ohlc.index.max()}")

    result = Backtester(cfg).run(ohlc)
    print(result)
    print(json.dumps(result.summary(), indent=2))

    if args.dashboard or args.png:
        from ..viz import LiveDashboard, DashboardConfig
        from ..live import run_live_replay
        dcfg = DashboardConfig(swing_length=cfg.strategy.swing_length,
                               show_sessions=cfg.strategy.require_session)
        dash = LiveDashboard(html_path=args.dashboard or "xauusd_dashboard.html",
                             cfg=dcfg, title=f"XAUUSD {args.timeframe} · SMC Agent")
        run_live_replay(cfg, ohlc, dash, plot_window=140, png_path=args.png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
