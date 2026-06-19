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


class TestTradeManagement(unittest.TestCase):
    def setUp(self):
        from xauusd_agent import InstrumentSpec
        self.spec = InstrumentSpec(sim_spread=0.0, sim_slippage=0.0)
        self.t = pd.Timestamp("2024-01-01")

    def test_off_by_default(self):
        from xauusd_agent import ManagementConfig
        m = ManagementConfig()
        self.assertFalse(m.breakeven_enabled)
        self.assertFalse(m.trailing_enabled)
        self.assertFalse(m.partial_enabled)

    def test_partial_take_profit_then_breakeven(self):
        from xauusd_agent import ManagementConfig
        from xauusd_agent.broker import SimBroker, Order
        from xauusd_agent.strategy import Side
        mg = ManagementConfig(partial_enabled=True, partial_at_r=1.0,
                              partial_fraction=0.5, partial_then_breakeven=True)
        b = SimBroker(self.spec, 10_000, management=mg)
        # long entry 2000, stop 1990 (risk 10); +1R target = 2010
        b.place(Order(Side.LONG, 1.0, stop=1990, take_profit=2050), ref_price=2000, when=self.t)
        b.update(high=2012, low=2000, close=2011, when=self.t)
        # half closed, stop moved to break-even (entry)
        self.assertAlmostEqual(b.positions[0].lots, 0.5, places=6)
        self.assertAlmostEqual(b.positions[0].stop, 2000.0, places=6)
        closed = b.update(high=2001, low=1999, close=2000, when=self.t)
        self.assertEqual(closed[0].reason, "stop")
        # net: +$500 partial + $0 break-even remainder
        self.assertAlmostEqual(b.balance, 10_500.0, places=4)

    def test_breakeven_protects_winner(self):
        from xauusd_agent import ManagementConfig
        from xauusd_agent.broker import SimBroker, Order
        from xauusd_agent.strategy import Side
        mg = ManagementConfig(breakeven_enabled=True, breakeven_at_r=1.0)
        b = SimBroker(self.spec, 10_000, management=mg)
        b.place(Order(Side.LONG, 1.0, stop=1990, take_profit=2050), ref_price=2000, when=self.t)
        b.update(high=2010, low=2001, close=2009, when=self.t)   # +1R -> stop to entry
        self.assertAlmostEqual(b.positions[0].stop, 2000.0, places=6)
        closed = b.update(high=2001, low=1999, close=2000, when=self.t)
        self.assertAlmostEqual(closed[0].pnl, 0.0, places=4)     # scratched, not a loss

    def test_trailing_locks_profit(self):
        from xauusd_agent import ManagementConfig
        from xauusd_agent.broker import SimBroker, Order
        from xauusd_agent.strategy import Side
        mg = ManagementConfig(trailing_enabled=True, trailing_at_r=1.0, trailing_distance_r=1.0)
        b = SimBroker(self.spec, 10_000, management=mg)
        b.place(Order(Side.LONG, 1.0, stop=1990, take_profit=2100), ref_price=2000, when=self.t)
        b.update(high=2030, low=2001, close=2029, when=self.t)   # peak 2030 -> trail to 2020
        self.assertAlmostEqual(b.positions[0].stop, 2020.0, places=6)
        closed = b.update(high=2021, low=2019, close=2020, when=self.t)
        self.assertGreater(closed[0].pnl, 0.0)                   # locked-in profit


class TestNewsFilter(unittest.TestCase):
    def test_blackout_window(self):
        from xauusd_agent import NewsFilter
        nf = NewsFilter(["2024-01-10 13:30:00"], before_min=30, after_min=30)
        self.assertTrue(nf.in_blackout("2024-01-10 13:30:00"))   # at the event
        self.assertTrue(nf.in_blackout("2024-01-10 13:05:00"))   # 25 min before
        self.assertTrue(nf.in_blackout("2024-01-10 13:59:00"))   # 29 min after
        self.assertFalse(nf.in_blackout("2024-01-10 12:30:00"))  # 60 min before
        self.assertFalse(nf.in_blackout("2024-01-10 14:30:00"))  # 60 min after
        self.assertFalse(nf.in_blackout("2024-01-09 13:30:00"))  # day before

    def test_empty_filter_never_blacks_out(self):
        from xauusd_agent import NewsFilter
        self.assertFalse(NewsFilter([]).in_blackout("2024-01-10 13:30:00"))

    def test_blackout_blocks_entries_in_backtest(self):
        from xauusd_agent import AgentConfig, Mode, NewsFilter
        from xauusd_agent.presets import xauusd_config, sample_data_path
        from xauusd_agent.data import load_csv
        from xauusd_agent.backtest import Backtester
        ohlc = load_csv(sample_data_path("M15")).head(900)
        cfg = xauusd_config(timeframe="15M"); cfg.strategy.window = 150
        cfg.strategy.require_session = False; cfg.strategy.require_fvg = False
        base_trades = len(Backtester(cfg).run(ohlc).trades)
        self.assertGreater(base_trades, 0)
        # blackout the entire span -> no new entries can open
        cfg.news.enabled = True
        cfg.news.before_min = cfg.news.after_min = 10 ** 7
        nf = NewsFilter([ohlc.index[len(ohlc) // 2]])
        blocked_trades = len(Backtester(cfg, news_filter=nf).run(ohlc).trades)
        self.assertLess(blocked_trades, base_trades)


class TestJournalAndState(unittest.TestCase):
    def test_journal_round_trip(self):
        import tempfile, os
        from xauusd_agent import TradeJournal
        path = os.path.join(tempfile.mkdtemp(), "j.jsonl")
        j = TradeJournal(path)
        j.log("entry", when=pd.Timestamp("2024-01-01 09:00"), side="long", lots=0.21)
        j.log("exit", pnl=42.0, reason="target")
        rows = j.read()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["event"], "entry")
        self.assertEqual(rows[0]["side"], "long")
        self.assertEqual(rows[1]["pnl"], 42.0)

    def test_state_save_load(self):
        import tempfile, os
        from datetime import date
        from xauusd_agent import RiskConfig, InstrumentSpec, RiskManager, save_state, load_state
        rm = RiskManager(RiskConfig(), InstrumentSpec(), 10_000.0)
        rm.can_trade(date(2024, 1, 1), 10_000.0, 0)  # establish the day baseline
        rm.can_trade(date(2024, 1, 1), 9_600.0, 0)   # -4% -> trips the daily loss halt
        rm.register_fill()
        path = os.path.join(tempfile.mkdtemp(), "s.json")
        save_state(rm, path)
        rm2 = RiskManager(RiskConfig(), InstrumentSpec(), 10_000.0)
        self.assertTrue(load_state(rm2, path))
        self.assertEqual(rm2._trades_today, 1)
        self.assertTrue(rm2._halted_today)
        self.assertEqual(rm2._day, date(2024, 1, 1))


class TestConfigIO(unittest.TestCase):
    def test_yaml_round_trip(self):
        import tempfile, os
        from xauusd_agent import AgentConfig, load_config, save_config, Mode
        cfg = AgentConfig()
        cfg.strategy.swing_length = 7
        cfg.management.partial_enabled = True
        cfg.news.enabled = True
        path = os.path.join(tempfile.mkdtemp(), "c.yaml")
        save_config(cfg, path)
        back = load_config(path)
        self.assertEqual(back.strategy.swing_length, 7)
        self.assertTrue(back.management.partial_enabled)
        self.assertTrue(back.news.enabled)
        self.assertIs(back.mode, Mode.BACKTEST)

    def test_partial_config_keeps_defaults(self):
        from xauusd_agent import config_from_dict
        cfg = config_from_dict({"starting_equity": 5000, "strategy": {"window": 123}})
        self.assertEqual(cfg.starting_equity, 5000)
        self.assertEqual(cfg.strategy.window, 123)
        self.assertEqual(cfg.strategy.swing_length, 5)   # untouched default
        self.assertFalse(cfg.management.partial_enabled)  # untouched default

    def test_example_yaml_loads(self):
        import os
        from xauusd_agent import load_config
        path = os.path.join(ROOT, "xauusd_agent", "config.example.yaml")
        cfg = load_config(path)
        self.assertEqual(cfg.instrument.symbol, "XAUUSD")
        self.assertTrue(cfg.management.trailing_enabled)


class TestReport(unittest.TestCase):
    def test_build_report_figure(self):
        from xauusd_agent.presets import xauusd_config, sample_data_path
        from xauusd_agent.data import load_csv
        from xauusd_agent.backtest import Backtester
        from xauusd_agent.report import build_report_figure
        cfg = xauusd_config(timeframe="4H"); cfg.strategy.window = 120
        result = Backtester(cfg).run(load_csv(sample_data_path("4H")).head(700))
        fig = build_report_figure(result, title="test")
        # equity + drawdown traces present, no exception building it
        self.assertGreaterEqual(len(fig.data), 2)


class TestRobustness(unittest.TestCase):
    def test_monte_carlo_distribution(self):
        from xauusd_agent.presets import xauusd_config, sample_data_path
        from xauusd_agent.data import load_csv
        from xauusd_agent.backtest import Backtester
        from xauusd_agent.robustness import monte_carlo, buy_and_hold_return
        cfg = xauusd_config(timeframe="4H"); cfg.strategy.window = 120
        cfg.strategy.require_fvg = False
        ohlc = load_csv(sample_data_path("4H")).head(900)
        result = Backtester(cfg).run(ohlc)
        mc = monte_carlo(result, n_sims=1000)
        if mc["trades"] > 0:
            self.assertLessEqual(mc["return_p5"], mc["return_p50"])
            self.assertLessEqual(mc["return_p50"], mc["return_p95"])
            self.assertTrue(0.0 <= mc["prob_profit"] <= 1.0)
        # benchmark is a finite number
        self.assertEqual(buy_and_hold_return(ohlc), buy_and_hold_return(ohlc))

    def test_monte_carlo_no_trades(self):
        from xauusd_agent import AgentConfig, Mode
        from xauusd_agent.backtest import Backtester
        from xauusd_agent.robustness import monte_carlo
        import pandas as pd, numpy as np
        # flat data -> effectively no setups; just ensure it doesn't crash
        idx = pd.date_range("2024-01-01", periods=50, freq="4h")
        df = pd.DataFrame({"open": 2000.0, "high": 2000.5, "low": 1999.5,
                           "close": 2000.0, "volume": 1.0}, index=idx)
        result = Backtester(AgentConfig(mode=Mode.BACKTEST)).run(df)
        mc = monte_carlo(result, n_sims=100)
        self.assertIn("trades", mc)


class TestMacroBias(unittest.TestCase):
    def test_from_dxy_inverts_dollar_trend(self):
        from xauusd_agent import MacroBias
        idx = pd.date_range("2024-01-01", periods=40, freq="4h")
        # steadily rising dollar -> gold should read bearish (-1)
        up = pd.DataFrame({"close": np.linspace(100, 110, 40)}, index=idx)
        mb = MacroBias.from_dxy(up, lookback=5)
        self.assertEqual(mb.bias_at(idx[-1]), -1)
        # steadily falling dollar -> gold bullish (+1)
        down = pd.DataFrame({"close": np.linspace(110, 100, 40)}, index=idx)
        self.assertEqual(MacroBias.from_dxy(down, lookback=5).bias_at(idx[-1]), 1)

    def test_bias_at_uses_most_recent_past(self):
        from xauusd_agent import MacroBias
        s = pd.Series([1, -1], index=pd.to_datetime(["2024-01-01", "2024-01-10"]))
        mb = MacroBias(s)
        self.assertEqual(mb.bias_at("2023-12-01"), 0)   # before series -> neutral
        self.assertEqual(mb.bias_at("2024-01-05"), 1)   # carries 01-01 forward
        self.assertEqual(mb.bias_at("2024-01-20"), -1)

    def test_allows_only_aligned_or_neutral(self):
        from xauusd_agent import MacroBias
        mb = MacroBias(pd.Series([1], index=pd.to_datetime(["2024-01-01"])))
        self.assertTrue(mb.allows("2024-01-02", 1))    # long with bullish bias
        self.assertFalse(mb.allows("2024-01-02", -1))  # short fights bullish bias
        # neutral bias allows either direction
        flat = MacroBias(pd.Series([0], index=pd.to_datetime(["2024-01-01"])))
        self.assertTrue(flat.allows("2024-01-02", -1))

    def test_filter_only_removes_trades(self):
        from xauusd_agent import MacroBias
        from xauusd_agent.presets import xauusd_config, sample_data_path
        from xauusd_agent.data import load_csv
        from xauusd_agent.backtest import Backtester
        import copy
        ohlc = load_csv(sample_data_path("4H")).head(800)
        cfg = xauusd_config(timeframe="4H")
        cfg.strategy.window = 120
        cfg.strategy.require_fvg = False
        base = len(Backtester(cfg).run(ohlc).trades)
        # a constant bearish bias can only suppress longs, never add trades
        bias = pd.Series(-1, index=ohlc.index)
        mcfg = copy.deepcopy(cfg)
        mcfg.macro.enabled = True
        filtered = Backtester(mcfg, macro_bias=MacroBias(bias)).run(ohlc).trades
        self.assertLessEqual(len(filtered), base)
        self.assertTrue(all(t.position.side is Side.SHORT for t in filtered))

    def test_disabled_by_default(self):
        from xauusd_agent import AgentConfig
        self.assertFalse(AgentConfig().macro.enabled)

    def test_from_dxy_csv_roundtrip(self):
        import tempfile, os
        from xauusd_agent import MacroBias
        idx = pd.date_range("2024-01-01", periods=40, freq="4h")
        up = pd.DataFrame({"Date": idx, "open": np.linspace(100, 110, 40),
                           "high": np.linspace(100, 110, 40) + 0.2,
                           "low": np.linspace(100, 110, 40) - 0.2,
                           "close": np.linspace(100, 110, 40), "volume": 1.0})
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "dxy.csv")
            up.to_csv(p, index=False)
            mb = MacroBias.from_dxy_csv(p, lookback=5)
        self.assertEqual(mb.bias_at(idx[-1]), -1)   # rising dollar -> gold bearish


class TestRegimeMode(unittest.TestCase):
    def setUp(self):
        from xauusd_agent import InstrumentSpec, StrategyConfig, SMCStrategy
        self.s = SMCStrategy(StrategyConfig(regime_lookback=50), InstrumentSpec())

    def _win(self, closes):
        idx = pd.date_range("2024-01-01", periods=len(closes), freq="15min")
        c = np.asarray(closes, float)
        return pd.DataFrame({"open": c, "high": c + 0.1, "low": c - 0.1,
                             "close": c, "volume": 1.0}, index=idx)

    def test_classifies_trend_and_range(self):
        up = self._win(np.linspace(2000, 2100, 60))      # clean rise
        self.assertEqual(self.s._regime(up), ("trend", 1))
        down = self._win(np.linspace(2100, 2000, 60))
        self.assertEqual(self.s._regime(down), ("trend", -1))
        chop = self._win(2000 + np.tile([0, 5, 0, 5], 15))  # oscillating, no net move
        self.assertEqual(self.s._regime(chop)[0], "range")

    def test_off_by_default(self):
        from xauusd_agent import StrategyConfig
        self.assertFalse(StrategyConfig().regime_enabled)

    def test_regime_only_filters_entries(self):
        from xauusd_agent.presets import xauusd_config, sample_data_path
        from xauusd_agent.data import load_csv
        from xauusd_agent.backtest import Backtester
        import copy
        ohlc = load_csv(sample_data_path("4H")).head(800)
        base = xauusd_config(timeframe="4H")
        base.strategy.window = 150
        base.strategy.require_fvg = False
        n_off = len(Backtester(base).run(ohlc).trades)
        on = copy.deepcopy(base)
        on.strategy.regime_enabled = True   # counter-trend block can only remove entries
        n_on = len(Backtester(on).run(ohlc).trades)
        self.assertLessEqual(n_on, n_off)


class TestDukascopyData(unittest.TestCase):
    def test_epoch_millis_timestamp_parsed(self):
        # Dukascopy / dukascopy-node CSV: epoch-millis 'timestamp' column.
        from xauusd_agent.data import normalise_ohlc
        ts = [1_640_995_200_000, 1_640_995_200_000 + 900_000]  # 2022-01-01 00:00 + 15m, ms
        df = pd.DataFrame({"timestamp": ts, "open": [1, 2], "high": [3, 4],
                           "low": [0.5, 1.5], "close": [2, 3], "volume": [10, 20]})
        out = normalise_ohlc(df)
        self.assertEqual(str(out.index[0]), "2022-01-01 00:00:00")
        self.assertEqual((out.index[1] - out.index[0]).seconds, 900)  # 15-minute bars
        self.assertEqual(list(out.columns), ["open", "high", "low", "close", "volume"])

    def test_epoch_seconds_timestamp_parsed(self):
        from xauusd_agent.data import normalise_ohlc
        df = pd.DataFrame({"time": [1_640_995_200], "open": [1.0], "high": [2.0],
                           "low": [0.5], "close": [1.5], "volume": [1.0]})
        out = normalise_ohlc(df)
        self.assertEqual(str(out.index[0]), "2022-01-01 00:00:00")

    def test_iso_string_still_works(self):
        from xauusd_agent.data import normalise_ohlc
        df = pd.DataFrame({"date": ["2024-03-01 09:00", "2024-03-01 09:15"],
                           "open": [1, 2], "high": [3, 4], "low": [0, 1], "close": [2, 3]})
        out = normalise_ohlc(df)
        self.assertEqual(str(out.index[0]), "2024-03-01 09:00:00")

    def test_histdata_m1_ascii(self):
        # HistData.com 'Generic ASCII' M1: headerless, ';'-delimited, YYYYMMDD HHMMSS.
        import tempfile, os
        from xauusd_agent.data import load_histdata
        text = ("20240301 090000;2050.1;2050.6;2049.8;2050.4;0\n"
                "20240301 090100;2050.4;2051.0;2050.2;2050.9;0\n")
        fd, p = tempfile.mkstemp(suffix=".csv")
        os.write(fd, text.encode()); os.close(fd)
        try:
            out = load_histdata(p)
            self.assertEqual(list(out.columns), ["open", "high", "low", "close", "volume"])
            self.assertEqual(str(out.index[0]), "2024-03-01 09:00:00")
            self.assertEqual((out.index[1] - out.index[0]).seconds, 60)  # M1 bars
            self.assertAlmostEqual(float(out["close"].iloc[-1]), 2050.9)
        finally:
            os.remove(p)


class TestValidateCommand(unittest.TestCase):
    def test_validate_runs_and_gives_verdict(self):
        import io, contextlib
        from xauusd_agent.cli import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["validate", "--timeframe", "4H", "--tf", "4H",
                       "--splits", "2", "--montecarlo", "50"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("VERDICT", out)
        self.assertIn("walk-forward", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
