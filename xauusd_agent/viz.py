"""Live visual dashboard for the XAUUSD agent.

Renders the same dark "Smart Money Concepts" candlestick chart you see in the
repo's ``test.gif`` (order blocks, FVGs, liquidity, previous highs/lows, swing
structure, BOS/CHoCH, sessions, retracements) and overlays the agent's OWN
activity on top:

    * entry markers      ▲ long / ▼ short, at the candle the order was placed
    * stop-loss lines     dashed red,   entry time -> exit/now
    * take-profit lines   dashed green,  entry time -> exit/now
    * exit markers        ✕ coloured by win (green) / loss (red)
    * a stats header      equity, open PnL, trades, win-rate

Headless-friendly: each :meth:`LiveDashboard.update` writes a self-refreshing
HTML file (open it in a browser to watch it tick) and can also snapshot a PNG.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from smartmoneyconcepts import smc

from .strategy import Side
from .broker import Position, ClosedTrade


# -- palette (matches the repo's gif) ------------------------------------------
BG = "rgba(12, 14, 18, 1)"
UP = "#77dd76"
DOWN = "#ff6962"
GHOST = "rgba(255, 255, 255, 0.4)"


def _format_volume(volume: float) -> str:
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if volume >= div:
            return f"{volume / div:.3f}{unit}"
    return f"{volume:.2f}"


# -- smc overlays (adapted from tests/generate_gif.py, made NaN/empty safe) -----

def _add_fvg(fig, xs, fvg):
    n = len(xs)
    for i in range(len(fvg)):
        if np.isnan(fvg["FVG"][i]):
            continue
        x1 = int(fvg["MitigatedIndex"][i] if fvg["MitigatedIndex"][i] != 0 else n - 1)
        fig.add_shape(type="rect", x0=xs[i], y0=fvg["Top"][i],
                      x1=xs[x1], y1=fvg["Bottom"][i],
                      line=dict(width=0), fillcolor="yellow", opacity=0.18)


def _add_swings(fig, xs, shl):
    idx = [i for i in range(len(shl)) if not np.isnan(shl["HighLow"][i])]
    for a, b in zip(idx, idx[1:]):
        color = "rgba(0,128,0,0.25)" if shl["HighLow"][a] == -1 else "rgba(255,0,0,0.25)"
        fig.add_trace(go.Scatter(x=[xs[a], xs[b]],
                                 y=[shl["Level"][a], shl["Level"][b]],
                                 mode="lines", line=dict(color=color),
                                 hoverinfo="skip", showlegend=False))


def _add_bos_choch(fig, xs, data):
    for i in range(len(data)):
        for key, col in (("BOS", "rgba(255,165,0,0.5)"), ("CHOCH", "rgba(80,140,255,0.6)")):
            if np.isnan(data[key][i]):
                continue
            broken = int(data["BrokenIndex"][i])
            lvl = data["Level"][i]
            fig.add_trace(go.Scatter(x=[xs[i], xs[broken]], y=[lvl, lvl],
                                     mode="lines", line=dict(color=col),
                                     hoverinfo="skip", showlegend=False))
            mid = round((i + broken) / 2)
            fig.add_trace(go.Scatter(x=[xs[mid]], y=[lvl], mode="text", text=key,
                                     textposition="top center" if data[key][i] == 1 else "bottom center",
                                     textfont=dict(color=col, size=8),
                                     hoverinfo="skip", showlegend=False))


def _add_ob(fig, xs, ob):
    n = len(xs)
    for i in range(len(ob)):
        if np.isnan(ob["OB"][i]) or ob["OB"][i] == 0:
            continue
        bull = ob["OB"][i] == 1
        x1 = int(ob["MitigatedIndex"][i] if ob["MitigatedIndex"][i] != 0 else n - 1)
        fig.add_shape(type="rect", x0=xs[i], y0=ob["Bottom"][i],
                      x1=xs[x1], y1=ob["Top"][i], line=dict(width=0),
                      fillcolor="rgba(0,160,80,0.18)" if bull else "rgba(160,0,40,0.18)")
        xc = xs[int(i + (x1 - i) / 2)]
        yc = (ob["Bottom"][i] + ob["Top"][i]) / 2
        fig.add_annotation(x=xc, y=yc, text=f'OB: {_format_volume(ob["OBVolume"][i])} ({ob["Percentage"][i]:.1f}%)',
                           font=dict(color=GHOST, size=8), showarrow=False)


def _add_liquidity(fig, xs, liq):
    for i in range(len(liq)):
        if not np.isnan(liq["Liquidity"][i]):
            end = int(liq["End"][i])
            fig.add_trace(go.Scatter(x=[xs[i], xs[end]],
                                     y=[liq["Level"][i], liq["Level"][i]], mode="lines",
                                     line=dict(color="rgba(255,165,0,0.3)"),
                                     hoverinfo="skip", showlegend=False))


def _add_prev_hl(fig, xs, phl):
    def runs(col):
        lv, ix = [], []
        for i in range(len(col)):
            if not np.isnan(col[i]) and col[i] != (lv[-1] if lv else None):
                lv.append(col[i]); ix.append(i)
        return lv, ix
    for col, label, pos in (("PreviousHigh", "PH", "top center"), ("PreviousLow", "PL", "bottom center")):
        lv, ix = runs(phl[col])
        for a in range(len(ix) - 1):
            fig.add_trace(go.Scatter(x=[xs[ix[a]], xs[ix[a + 1]]],
                                     y=[lv[a], lv[a]], mode="lines",
                                     line=dict(color="rgba(255,255,255,0.2)"),
                                     hoverinfo="skip", showlegend=False))
            fig.add_trace(go.Scatter(x=[xs[ix[a + 1]]], y=[lv[a]], mode="text",
                                     text=label, textposition=pos,
                                     textfont=dict(color=GHOST, size=8),
                                     hoverinfo="skip", showlegend=False))


def _add_sessions(fig, xs, sess):
    for i in range(len(sess) - 1):
        if sess["Active"][i] == 1:
            fig.add_shape(type="rect", x0=xs[i], y0=sess["Low"][i],
                          x1=xs[i + 1], y1=sess["High"][i],
                          line=dict(width=0), fillcolor="#16866E", opacity=0.12)


# -- agent trade overlays -------------------------------------------------------

def _to_pydt(ts):
    return pd.Timestamp(ts).to_pydatetime()


def _add_trades(fig, xs, t0_ts, t1_ts, positions: Sequence[Position], closed: Sequence[ClosedTrade]):
    t0, t1 = t0_ts, t1_ts          # pandas Timestamps for comparison
    t1x = _to_pydt(t1_ts)          # python datetime for plotting the right edge

    def in_window(ts):
        return t0 <= pd.Timestamp(ts) <= t1

    # closed trades: entry/exit markers + SL/TP spans
    for tr in closed:
        p = tr.position
        if not in_window(p.open_time):
            continue
        x_end = _to_pydt(tr.close_time) if in_window(tr.close_time) else t1x
        x_open = _to_pydt(p.open_time)
        long = p.side is Side.LONG
        fig.add_trace(go.Scatter(x=[x_open], y=[p.entry], mode="markers",
                                 marker=dict(symbol="triangle-up" if long else "triangle-down",
                                             size=11, color=UP if long else DOWN,
                                             line=dict(width=1, color="white")),
                                 name="entry", hoverinfo="text",
                                 text=[f"{p.side.value} {p.lots:.2f} @ {p.entry:.2f}"],
                                 showlegend=False))
        # SL / TP spans
        fig.add_trace(go.Scatter(x=[x_open, x_end], y=[p.stop, p.stop], mode="lines",
                                 line=dict(color="rgba(255,80,80,0.55)", dash="dot", width=1),
                                 hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=[x_open, x_end], y=[p.take_profit, p.take_profit], mode="lines",
                                 line=dict(color="rgba(80,255,140,0.55)", dash="dot", width=1),
                                 hoverinfo="skip", showlegend=False))
        win = tr.pnl > 0
        fig.add_trace(go.Scatter(x=[x_end], y=[tr.exit_price], mode="markers",
                                 marker=dict(symbol="x", size=9, color=UP if win else DOWN),
                                 name="exit", hoverinfo="text",
                                 text=[f"exit {tr.reason} {tr.pnl:+.2f}"], showlegend=False))

    # still-open positions: entry marker + live SL/TP out to the right edge
    for p in positions:
        if not in_window(p.open_time):
            continue
        x_open = _to_pydt(p.open_time)
        long = p.side is Side.LONG
        fig.add_trace(go.Scatter(x=[x_open], y=[p.entry], mode="markers",
                                 marker=dict(symbol="triangle-up" if long else "triangle-down",
                                             size=12, color=UP if long else DOWN,
                                             line=dict(width=1.5, color="yellow")),
                                 hoverinfo="text", text=[f"OPEN {p.side.value} {p.lots:.2f} @ {p.entry:.2f}"],
                                 showlegend=False))
        fig.add_trace(go.Scatter(x=[x_open, t1x], y=[p.stop, p.stop], mode="lines",
                                 line=dict(color="rgba(255,80,80,0.8)", dash="dash", width=1.2),
                                 hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=[x_open, t1x], y=[p.take_profit, p.take_profit], mode="lines",
                                 line=dict(color="rgba(80,255,140,0.8)", dash="dash", width=1.2),
                                 hoverinfo="skip", showlegend=False))


# -- figure builder -------------------------------------------------------------

@dataclass
class DashboardConfig:
    swing_length: int = 5
    prev_hl_timeframe: str = "4h"
    show_fvg: bool = True
    show_ob: bool = True
    show_liquidity: bool = True
    show_swings: bool = True
    show_bos_choch: bool = True
    show_prev_hl: bool = False     # needs a tz-aware/long enough index; off by default
    show_sessions: bool = False
    width: int = 1100
    height: int = 620


def build_figure(window_df: pd.DataFrame, cfg: DashboardConfig,
                 positions: Sequence[Position] = (), closed: Sequence[ClosedTrade] = (),
                 header: str = "", title: str = "XAUUSD · SMC Agent") -> go.Figure:
    # native python datetimes for the x-axis (kaleido/orjson can't encode pd.Timestamp)
    xs = [t.to_pydatetime() for t in pd.DatetimeIndex(window_df.index)]
    o, h, l, c = (window_df["open"].values, window_df["high"].values,
                  window_df["low"].values, window_df["close"].values)

    fig = go.Figure(data=[go.Candlestick(
        x=xs, open=o, high=h, low=l, close=c,
        increasing_line_color=UP, decreasing_line_color=DOWN, name="price")])

    shl = smc.swing_highs_lows(window_df, swing_length=cfg.swing_length)
    if cfg.show_fvg:
        _add_fvg(fig, xs, smc.fvg(window_df, join_consecutive=True))
    if cfg.show_swings:
        _add_swings(fig, xs, shl)
    if cfg.show_bos_choch:
        _add_bos_choch(fig, xs, smc.bos_choch(window_df, shl))
    if cfg.show_ob:
        _add_ob(fig, xs, smc.ob(window_df, shl))
    if cfg.show_liquidity:
        _add_liquidity(fig, xs, smc.liquidity(window_df, shl))
    if cfg.show_prev_hl:
        try:
            _add_prev_hl(fig, xs, smc.previous_high_low(window_df, time_frame=cfg.prev_hl_timeframe))
        except Exception:
            pass
    if cfg.show_sessions:
        try:
            _add_sessions(fig, xs, smc.sessions(window_df, session="London"))
        except Exception:
            pass

    _add_trades(fig, xs, window_df.index[0], window_df.index[-1], positions, closed)

    fig.update_layout(
        title=dict(text=title, x=0.01, font=dict(color="white", size=14)),
        xaxis_rangeslider_visible=False, showlegend=False,
        margin=dict(l=10, r=10, b=10, t=40),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor=BG, font=dict(color="white"),
        width=cfg.width, height=cfg.height)
    fig.update_xaxes(showgrid=False, color="rgba(255,255,255,0.5)")
    fig.update_yaxes(showgrid=False, color="rgba(255,255,255,0.5)")
    if header:
        fig.add_annotation(xref="paper", yref="paper", x=0.01, y=0.99, xanchor="left",
                           yanchor="top", text=header, showarrow=False, align="left",
                           font=dict(color="rgba(255,255,255,0.75)", size=11),
                           bgcolor="rgba(0,0,0,0.35)", borderpad=4)
    return fig


# -- live dashboard -------------------------------------------------------------

class LiveDashboard:
    """Writes a self-refreshing HTML (and optional PNG) each time it's updated."""

    def __init__(self, html_path: str = "xauusd_dashboard.html",
                 cfg: Optional[DashboardConfig] = None, refresh_secs: int = 2,
                 title: str = "XAUUSD · SMC Agent (live)"):
        self.html_path = html_path
        self.cfg = cfg or DashboardConfig()
        self.refresh_secs = refresh_secs
        self.title = title
        self.last_fig: Optional[go.Figure] = None

    @staticmethod
    def _header(equity, start_equity, positions, closed, last_close):
        floating = sum(p.unrealised(last_close) for p in positions)
        wins = sum(1 for t in closed if t.pnl > 0)
        wr = (wins / len(closed)) if closed else 0.0
        ret = (equity - start_equity) / start_equity if start_equity else 0.0
        return (f"equity ${equity:,.0f} ({ret:+.2%})   open {len(positions)} "
                f"(float ${floating:+,.0f})   trades {len(closed)}  win {wr:.0%}")

    def update(self, window_df: pd.DataFrame, equity: float, start_equity: float,
               positions: Sequence[Position] = (), closed: Sequence[ClosedTrade] = (),
               png_path: Optional[str] = None) -> str:
        last_close = float(window_df["close"].iloc[-1])
        header = self._header(equity, start_equity, positions, closed, last_close)
        fig = build_figure(window_df, self.cfg, positions, closed, header=header, title=self.title)
        self.last_fig = fig

        html = fig.to_html(full_html=True, include_plotlyjs="cdn")
        meta = f'<meta http-equiv="refresh" content="{self.refresh_secs}">'
        html = html.replace("<head>", "<head>" + meta, 1)
        with open(self.html_path, "w") as fh:
            fh.write(html)

        if png_path:
            fig.write_image(png_path)
        return self.html_path

    def snapshot_png(self, png_path: str) -> str:
        if self.last_fig is None:
            raise RuntimeError("call update() before snapshot_png()")
        self.last_fig.write_image(png_path)
        return png_path
