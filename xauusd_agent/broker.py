"""Broker abstraction.

Two implementations share one interface so the rest of the agent never changes
between testing and going live:

* ``SimBroker``  - fully simulated fills, spread, slippage and commission. Drives
  BACKTEST and PAPER modes. Deterministic and dependency-free.
* ``Mt5Broker``  - thin adapter over the ``MetaTrader5`` package for LIVE mode.
  Imported lazily so the rest of the package works without MT5 installed
  (MT5's python bindings are Windows-only).

A "position" here is a single netted trade with an attached stop and target.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional

from .config import InstrumentSpec
from .strategy import Side


class OrderType(str, Enum):
    MARKET = "market"


@dataclass
class Order:
    side: Side
    lots: float
    stop: float
    take_profit: float
    type: OrderType = OrderType.MARKET
    comment: str = ""


@dataclass
class Position:
    id: int
    symbol: str
    side: Side
    lots: float
    entry: float
    stop: float
    take_profit: float
    open_time: datetime
    money_per_price_per_lot: float
    commission: float = 0.0
    comment: str = ""
    # in-trade management state
    init_risk: float = 0.0          # |entry - initial stop| in price units
    peak: float = 0.0               # best price reached (for trailing)
    partial_done: bool = False

    def unrealised(self, price: float) -> float:
        direction = 1 if self.side is Side.LONG else -1
        return (price - self.entry) * direction * self.lots * self.money_per_price_per_lot


@dataclass
class ClosedTrade:
    position: Position
    exit_price: float
    close_time: datetime
    pnl: float
    reason: str


class SimBroker:
    """Deterministic simulated broker for backtest / paper trading."""

    def __init__(self, instrument: InstrumentSpec, starting_equity: float = 10_000.0,
                 management=None):
        from .config import ManagementConfig
        self.instrument = instrument
        self.mgmt = management or ManagementConfig()
        self.balance = starting_equity
        self.positions: List[Position] = []
        self.closed: List[ClosedTrade] = []
        self._next_id = 1

    # -- account ----------------------------------------------------------------

    def equity(self, price: float) -> float:
        floating = sum(p.unrealised(price) for p in self.positions)
        return self.balance + floating

    @property
    def open_count(self) -> int:
        return len(self.positions)

    # -- order routing ----------------------------------------------------------

    def place(self, order: Order, ref_price: float, when: datetime) -> Position:
        """Open a market position. Entry pays half-spread + slippage and commission."""
        spec = self.instrument
        half_spread = spec.sim_spread / 2.0
        if order.side is Side.LONG:
            fill = ref_price + half_spread + spec.sim_slippage
        else:
            fill = ref_price - half_spread - spec.sim_slippage

        commission = spec.commission_per_lot * order.lots
        self.balance -= commission

        pos = Position(
            id=self._next_id,
            symbol=spec.symbol,
            side=order.side,
            lots=order.lots,
            entry=fill,
            stop=order.stop,
            take_profit=order.take_profit,
            open_time=when,
            money_per_price_per_lot=spec.money_per_price_per_lot,
            commission=commission,
            comment=order.comment,
        )
        pos.init_risk = abs(pos.entry - pos.stop)
        pos.peak = pos.entry
        self.positions.append(pos)
        self._next_id += 1
        return pos

    def _close(self, pos: Position, exit_price: float, when: datetime, reason: str) -> ClosedTrade:
        pnl = pos.unrealised(exit_price)
        self.balance += pnl
        self.positions.remove(pos)
        trade = ClosedTrade(pos, exit_price, when, pnl, reason)
        self.closed.append(trade)
        return trade

    def _close_partial(self, pos: Position, fraction: float, exit_price: float,
                       when: datetime, reason: str) -> Optional[ClosedTrade]:
        """Close `fraction` of a position; the remainder stays open."""
        import dataclasses
        closed_lots = round(pos.lots * fraction, 8)
        if closed_lots <= 0:
            return None
        direction = 1 if pos.side is Side.LONG else -1
        pnl = (exit_price - pos.entry) * direction * closed_lots * pos.money_per_price_per_lot
        self.balance += pnl
        leg = dataclasses.replace(pos, lots=closed_lots)
        trade = ClosedTrade(leg, exit_price, when, pnl, reason)
        self.closed.append(trade)
        pos.lots = round(pos.lots - closed_lots, 8)
        return trade

    def update(self, high: float, low: float, close: float, when: datetime) -> List[ClosedTrade]:
        """Process one candle: stops / targets / partials, then trail for next bar."""
        mgmt = self.mgmt
        out: List[ClosedTrade] = []
        for pos in list(self.positions):
            long = pos.side is Side.LONG
            d = 1 if long else -1
            risk = pos.init_risk

            # 1. protective stop (checked against the *current* stop, pre-update)
            if (low <= pos.stop) if long else (high >= pos.stop):
                out.append(self._close(pos, pos.stop, when, "stop"))
                continue

            # 2. partial take-profit (closer than the final target)
            if mgmt.partial_enabled and not pos.partial_done and risk > 0:
                ptp = pos.entry + d * mgmt.partial_at_r * risk
                if (high >= ptp) if long else (low <= ptp):
                    t = self._close_partial(pos, mgmt.partial_fraction, ptp, when, "partial")
                    if t is not None:
                        out.append(t)
                    pos.partial_done = True
                    if mgmt.partial_then_breakeven:
                        pos.stop = max(pos.stop, pos.entry) if long else min(pos.stop, pos.entry)
                    continue  # process the remainder from the next candle

            # 3. final target on the (possibly reduced) position
            if (high >= pos.take_profit) if long else (low <= pos.take_profit):
                out.append(self._close(pos, pos.take_profit, when, "target"))
                continue

            # 4. still open -> advance peak and tighten stop for the NEXT candle
            pos.peak = max(pos.peak, high) if long else min(pos.peak, low)
            if risk > 0 and mgmt.breakeven_enabled:
                if (pos.peak - pos.entry) * d >= mgmt.breakeven_at_r * risk:
                    be = pos.entry + d * mgmt.breakeven_offset_r * risk
                    pos.stop = max(pos.stop, be) if long else min(pos.stop, be)
            if risk > 0 and mgmt.trailing_enabled:
                if (pos.peak - pos.entry) * d >= mgmt.trailing_at_r * risk:
                    trail = pos.peak - d * mgmt.trailing_distance_r * risk
                    pos.stop = max(pos.stop, trail) if long else min(pos.stop, trail)
        return out

    def close_all(self, price: float, when: datetime, reason: str = "eod") -> List[ClosedTrade]:
        return [self._close(p, price, when, reason) for p in list(self.positions)]


class Mt5Broker:
    """MetaTrader 5 live adapter. Imported lazily; only used in Mode.LIVE.

    This is intentionally minimal and *guarded*: it refuses to do anything until
    ``connect()`` succeeds, and every order goes through ``MetaTrader5.order_send``
    so the broker terminal remains the single source of truth.
    """

    def __init__(self, instrument: InstrumentSpec, login: Optional[int] = None,
                 password: Optional[str] = None, server: Optional[str] = None,
                 deviation: int = 20, magic: int = 770077):
        self.instrument = instrument
        self.login = login
        self.password = password
        self.server = server
        self.deviation = deviation
        self.magic = magic
        self._mt5 = None

    def connect(self) -> None:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on host OS
            raise RuntimeError(
                "MetaTrader5 package is not installed. `pip install MetaTrader5` "
                "on a Windows host with an MT5 terminal to trade live."
            ) from exc

        kwargs = {}
        if self.login:
            kwargs.update(login=self.login, password=self.password, server=self.server)
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")
        self._mt5 = mt5

    def _require(self):
        if self._mt5 is None:
            raise RuntimeError("Mt5Broker.connect() must be called before trading.")
        return self._mt5

    def account_equity(self) -> float:
        mt5 = self._require()
        info = mt5.account_info()
        if info is None:
            raise RuntimeError(f"MT5 account_info() failed: {mt5.last_error()}")
        return float(info.equity)

    def open_count(self) -> int:
        mt5 = self._require()
        positions = mt5.positions_get(symbol=self.instrument.symbol)
        return 0 if positions is None else len(positions)

    def place(self, order: Order) -> dict:  # pragma: no cover - requires live terminal
        mt5 = self._require()
        symbol = self.instrument.symbol
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"No tick for {symbol}: {mt5.last_error()}")
        is_long = order.side is Side.LONG
        price = tick.ask if is_long else tick.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(order.lots),
            "type": mt5.ORDER_TYPE_BUY if is_long else mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": float(order.stop),
            "tp": float(order.take_profit),
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": order.comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"order_send failed: {getattr(result, 'retcode', None)} {mt5.last_error()}")
        return result._asdict()

    def shutdown(self) -> None:
        if self._mt5 is not None:
            self._mt5.shutdown()
