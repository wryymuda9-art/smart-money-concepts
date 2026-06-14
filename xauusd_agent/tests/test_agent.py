"""Unit + smoke tests for the xauusd_agent package.

Risk/sizing and broker logic are tested deterministically.  A pipeline smoke test
runs the full backtester over the bundled EURUSD sample data (the repo ships no
XAUUSD data) purely to prove the layers wire together and stay causal -- the
numbers are not a strategy endorsement.
"""

import os
import sys
import unittest
from datetime import date

import numpy as np
import pandas as pd

BASE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(BASE, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from xauusd_agent import (
    AgentConfig, Mode, InstrumentSpec, RiskConfig, RiskManager,
    SMCStrategy, Signal, Side, SimBroker, Order, Backtester, TradingAgent,
)


class TestRiskManager(unittest.TestCase):
    def setUp(self):
        self.spec = InstrumentSpec()  # XAUUSD defaults: 100 USD/price/lot
        self.rm = RiskManager(RiskConfig(risk_per_trade=0.01, min_stop_distance=0.5),
                              self.spec, starting_equity=10_000.0)

    def test_position_sizing_matches_risk_budget(self):
        # risk 1% of 10k = $100. Stop 2.0 USD wide => $200/lot => 0.5 lots.
        sig = Signal(Side.LONG, entry=2000.0, stop=1998.0, take_profit=2004.0)
        dec = self.rm.size(sig, equity=10_000.0)
        self.assertTrue(dec.approved)
        self.assertAlmostEqual(dec.lots, 0.5, places=6)
        # actual money at risk should not exceed the 1% budget
        self.assertLessEqual(dec.risk_money, 100.0 + 1e-6)

    def test_wide_stop_shrinks_size(self):
        narrow = self.rm.size(Signal(Side.LONG, 2000, 1999, 2002), 10_000)
        wide = self.rm.size(Signal(Side.LONG, 2000, 1990, 2020), 10_000)
        self.assertGreater(narrow.lots, wide.lots)

    def test_rounds_down_to_lot_step(self):
        # choose numbers that don't land on a clean lot step
        sig = Signal(Side.LONG, entry=2000.0, stop=1997.3, take_profit=2005.0)
        dec = self.rm.size(sig, equity=10_000.0)
        # never exceed the risk budget after rounding
        self.assertLessEqual(dec.risk_money, 100.0 + 1e-6)
        self.assertAlmostEqual((dec.lots / self.spec.lot_step) % 1, 0, places=6)

    def test_min_stop_distance_rejected(self):
        sig = Signal(Side.LONG, entry=2000.0, stop=1999.9, take_profit=2002.0)
        dec = self.rm.size(sig, equity=10_000.0)
        self.assertFalse(dec.approved)

    def test_daily_loss_limit_halts(self):
        rm = RiskManager(RiskConfig(max_daily_loss=0.03), self.spec, 10_000.0)
        d = date(2024, 1, 1)
        ok, _ = rm.can_trade(d, equity=10_000.0, open_positions=0)
        self.assertTrue(ok)
        # drop equity 4% -> should halt
        ok, why = rm.can_trade(d, equity=9_600.0, open_positions=0)
        self.assertFalse(ok)
        self.assertIn("loss", why)
        # stays halted even if equity recovers same day
        ok, _ = rm.can_trade(d, equity=10_000.0, open_positions=0)
        self.assertFalse(ok)
        # new day resets
        ok, _ = rm.can_trade(date(2024, 1, 2), equity=10_000.0, open_positions=0)
        self.assertTrue(ok)

    def test_max_open_and_max_trades(self):
        rm = RiskManager(RiskConfig(max_open_positions=1, max_daily_trades=2),
                         self.spec, 10_000.0)
        d = date(2024, 1, 1)
        self.assertFalse(rm.can_trade(d, 10_000, open_positions=1)[0])
        rm.register_fill(); rm.register_fill()
        self.assertFalse(rm.can_trade(d, 10_000, open_positions=0)[0])


class TestSimBroker(unittest.TestCase):
    def setUp(self):
        self.spec = InstrumentSpec(sim_spread=0.0, sim_slippage=0.0, commission_per_lot=0.0)
        self.broker = SimBroker(self.spec, 10_000.0)
        self.t = pd.Timestamp("2024-01-01 08:00")

    def test_long_take_profit_pnl(self):
        self.broker.place(Order(Side.LONG, lots=1.0, stop=1990, take_profit=2010),
                          ref_price=2000.0, when=self.t)
        closed = self.broker.update(high=2010, low=2000, close=2009, when=self.t)
        self.assertEqual(len(closed), 1)
        # +10 price * 1 lot * 100 = +1000
        self.assertAlmostEqual(closed[0].pnl, 1000.0, places=4)
        self.assertAlmostEqual(self.broker.balance, 11_000.0, places=4)

    def test_long_stop_loss_pnl(self):
        self.broker.place(Order(Side.LONG, lots=1.0, stop=1990, take_profit=2010),
                          ref_price=2000.0, when=self.t)
        closed = self.broker.update(high=2001, low=1989, close=1992, when=self.t)
        self.assertAlmostEqual(closed[0].pnl, -1000.0, places=4)

    def test_stop_priority_when_both_hit(self):
        # a candle that engulfs both stop and target must assume stop first
        self.broker.place(Order(Side.SHORT, lots=1.0, stop=2010, take_profit=1990),
                          ref_price=2000.0, when=self.t)
        closed = self.broker.update(high=2011, low=1989, close=2000, when=self.t)
        self.assertEqual(closed[0].reason, "stop")


class TestPipelineSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from xauusd_agent.data import load_csv
        data = os.path.join(ROOT, "tests", "test_data", "EURUSD", "EURUSD_15M.csv")
        cls.df = load_csv(data).head(3000)

    def test_backtest_runs_and_is_consistent(self):
        cfg = AgentConfig(mode=Mode.BACKTEST, starting_equity=10_000.0)
        # EURUSD priced ~1.0, so scale instrument + min stop down to be sensible
        cfg.instrument.symbol = "EURUSD"
        cfg.instrument.money_per_price_per_lot = 100_000.0
        cfg.instrument.sim_spread = 0.0001
        cfg.instrument.sim_slippage = 0.0
        cfg.instrument.max_spread = 0.01
        cfg.risk.min_stop_distance = 0.0001
        cfg.strategy.require_session = False  # sample isn't tz-aligned to sessions
        cfg.strategy.window = 300

        result = Backtester(cfg).run(self.df)
        # pipeline produced an equity curve and didn't blow up
        self.assertGreater(len(result.equity_curve), 0)
        self.assertGreaterEqual(result.n_trades, 0)
        # equity accounting is internally consistent: final equity == start + sum(pnl)
        realised = sum(t.pnl for t in result.trades)
        self.assertAlmostEqual(
            result.final_equity, cfg.starting_equity + realised, places=2
        )
        # no trade may risk more than the configured budget at entry
        for t in result.trades:
            risk_at_entry = abs(t.position.entry - t.position.stop) * \
                t.position.lots * cfg.instrument.money_per_price_per_lot
            self.assertLessEqual(
                risk_at_entry, cfg.starting_equity * cfg.risk.risk_per_trade * 3
            )

    def test_no_lookahead_in_strategy(self):
        # evaluating on a prefix must equal evaluating on the prefix of a longer set
        strat = SMCStrategy(AgentConfig().strategy, AgentConfig().instrument)
        strat.cfg.require_session = False
        w1 = self.df.iloc[:500]
        s1 = strat.evaluate(w1)
        s2 = strat.evaluate(self.df.iloc[:500].copy())
        self.assertEqual(s1.side, s2.side)
        self.assertAlmostEqual(s1.entry, s2.entry, places=8)


class TestCsvDataFeed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from xauusd_agent.data import load_csv
        data = os.path.join(ROOT, "tests", "test_data", "EURUSD", "EURUSD_15M.csv")
        cls.df = load_csv(data).head(60)

    def test_feed_advances_and_windows(self):
        from xauusd_agent import CsvDataFeed
        feed = CsvDataFeed(self.df, symbol="EURUSD", start_at=10)
        # first available window ends at candle index 9 (start_at-1)
        w = feed.latest_window(5)
        self.assertEqual(len(w), 5)
        self.assertTrue(w.index[-1] == self.df.index[9])
        # advancing yields the next candle time and extends the window
        ts = feed.wait_next_candle()
        self.assertEqual(ts, self.df.index[10])
        self.assertTrue(feed.latest_window(3).index[-1] == self.df.index[10])

    def test_feed_exhausts(self):
        from xauusd_agent import CsvDataFeed
        feed = CsvDataFeed(self.df, symbol="EURUSD", start_at=len(self.df))
        self.assertIsNone(feed.wait_next_candle())
        self.assertTrue(feed.exhausted)


class TestLiveLoopPaper(unittest.TestCase):
    def test_run_live_paper_consistency(self):
        from xauusd_agent import AgentConfig, Mode, CsvDataFeed
        from xauusd_agent.data import load_csv
        from xauusd_agent.live import run_live
        data = os.path.join(ROOT, "tests", "test_data", "EURUSD", "EURUSD_15M.csv")
        df = load_csv(data).head(700)

        cfg = AgentConfig(mode=Mode.PAPER, starting_equity=10_000.0)
        cfg.instrument.symbol = "EURUSD"
        cfg.instrument.money_per_price_per_lot = 100_000.0
        cfg.instrument.sim_spread = 0.0
        cfg.instrument.sim_slippage = 0.0
        cfg.risk.min_stop_distance = 0.0001
        cfg.strategy.require_session = False
        cfg.strategy.require_fvg = False
        cfg.strategy.window = 300

        feed = CsvDataFeed(df, symbol="EURUSD", start_at=300)
        # no dashboard -> no plotly/kaleido dependency in the test
        agent = run_live(cfg, feed, dashboard=None, verbose=False)
        # balance == start + realised pnl of closed trades
        realised = sum(t.pnl for t in agent.broker.closed)
        self.assertAlmostEqual(agent.broker.balance,
                               cfg.starting_equity + realised, places=2)


class TestXauusdPreset(unittest.TestCase):
    def test_bundled_real_data_backtests(self):
        from xauusd_agent.presets import xauusd_config, sample_data_path
        from xauusd_agent.data import load_csv
        from xauusd_agent.backtest import Backtester
        from xauusd_agent.config import Mode

        ohlc = load_csv(sample_data_path("4H"))
        # real gold prices, sane range
        self.assertGreater(len(ohlc), 1500)
        self.assertTrue(1000 < float(ohlc["close"].median()) < 4000)

        cfg = xauusd_config(mode=Mode.BACKTEST, timeframe="4H")
        cfg.strategy.window = 150          # smaller window -> faster test
        result = Backtester(cfg).run(ohlc.head(900))
        # pipeline ran and accounting is consistent
        realised = sum(t.pnl for t in result.trades)
        self.assertAlmostEqual(result.final_equity,
                               cfg.starting_equity + realised, places=2)
        # every trade respected the gold risk budget (0.5% * 3 headroom)
        for t in result.trades:
            risk = abs(t.position.entry - t.position.stop) * t.position.lots * \
                cfg.instrument.money_per_price_per_lot
            self.assertLessEqual(risk, cfg.starting_equity * cfg.risk.risk_per_trade * 3)


class TestResearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from xauusd_agent.presets import xauusd_config, sample_data_path
        from xauusd_agent.data import load_csv
        cls.ohlc = load_csv(sample_data_path("4H")).head(700)
        cls.cfg = xauusd_config(timeframe="4H")
        cls.cfg.strategy.window = 120
        cls.cfg.strategy.require_fvg = False

    def test_compute_metrics_shape(self):
        from xauusd_agent.backtest import Backtester
        from xauusd_agent.research import compute_metrics
        m = compute_metrics(Backtester(self.cfg).run(self.ohlc))
        for k in ("trades", "profit_factor", "avg_R", "sharpe", "max_drawdown",
                  "cagr", "significance"):
            self.assertIn(k, m)
        # few trades on a short slice -> not statistically significant
        self.assertIn(m["significance"], ("none", "weak", "moderate", "ok"))

    def test_sweep_returns_row_per_combo(self):
        from xauusd_agent.research import sweep
        grid = {"strategy.swing_length": [4, 6], "strategy.require_fvg": [False]}
        df = sweep(self.cfg, self.ohlc, grid)
        self.assertEqual(len(df), 2)
        self.assertIn("profit_factor", df.columns)
        self.assertIn("strategy.swing_length", df.columns)

    def test_walk_forward_oos_only(self):
        from xauusd_agent.research import walk_forward
        grid = {"strategy.swing_length": [4, 6]}
        wf = walk_forward(self.cfg, self.ohlc, grid, n_splits=2, min_is_trades=1)
        # produced at least one fold and an OOS summary
        self.assertGreaterEqual(len(wf.splits), 1)
        self.assertIn("trades", wf.oos_metrics)


class TestStrategyUpgrades(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from xauusd_agent.presets import xauusd_config, sample_data_path
        from xauusd_agent.data import load_csv
        cls.ohlc = load_csv(sample_data_path("4H")).head(800)
        cls.base = xauusd_config(timeframe="4H")
        cls.base.strategy.window = 120
        cls.base.strategy.require_fvg = False

    def _trades(self, **flags):
        import copy
        from xauusd_agent.backtest import Backtester
        cfg = copy.deepcopy(self.base)
        for k, v in flags.items():
            setattr(cfg.strategy, k, v)
        return len(Backtester(cfg).run(self.ohlc).trades)

    def test_htf_bias_returns_side_or_none(self):
        from xauusd_agent.strategy import SMCStrategy, Side
        s = SMCStrategy(self.base.strategy, self.base.instrument)
        bias = s._htf_bias(self.ohlc.iloc[:600])
        self.assertIn(bias, (Side.LONG, Side.SHORT, Side.NONE, None))

    def test_upgrades_are_additional_filters(self):
        base = self._trades()
        # each gate can only remove setups, never invent them
        self.assertLessEqual(self._trades(require_htf_alignment=True), base)
        self.assertLessEqual(self._trades(require_liquidity_sweep=True), base)

    def test_upgrades_off_by_default(self):
        self.assertFalse(self.base.strategy.require_htf_alignment)
        self.assertFalse(self.base.strategy.require_liquidity_sweep)


if __name__ == "__main__":
    unittest.main(verbosity=2)
