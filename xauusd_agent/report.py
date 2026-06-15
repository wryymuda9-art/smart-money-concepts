"""Performance report ("tearsheet") for a finished backtest.

Turns a :class:`~xauusd_agent.backtest.BacktestResult` into a one-glance picture:
an equity curve, the underwater (drawdown) plot, and a metrics header. Renders to
HTML (always) and PNG (needs plotly+kaleido+Chrome, like the dashboard).
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .backtest import BacktestResult
from .research import compute_metrics

BG = "rgba(12, 14, 18, 1)"
UP = "#77dd76"
DOWN = "#ff6962"


def build_report_figure(result: BacktestResult, title: str = "XAUUSD · SMC Agent") -> go.Figure:
    eq = result.equity_curve
    m = compute_metrics(result)

    if len(eq) == 0:
        eq = pd.Series([result.config.starting_equity], index=[pd.Timestamp.utcnow()])
    running_max = eq.cummax()
    drawdown = (eq - running_max) / running_max * 100.0

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.07,
        row_heights=[0.62, 0.38],
        subplot_titles=("Equity", "Drawdown %"),
    )
    fig.add_trace(go.Scatter(x=eq.index, y=eq.values, mode="lines",
                             line=dict(color=UP, width=1.5), name="equity"), row=1, col=1)
    fig.add_hline(y=result.config.starting_equity, line=dict(color="rgba(255,255,255,0.25)",
                  dash="dot"), row=1, col=1)
    fig.add_trace(go.Scatter(x=eq.index, y=drawdown.values, mode="lines",
                             line=dict(color=DOWN, width=1), fill="tozeroy",
                             fillcolor="rgba(255,105,98,0.25)", name="drawdown"), row=2, col=1)

    pf = m["profit_factor"]
    header = (
        f"trades {m['trades']}   win {m['win_rate']:.0%}   "
        f"PF {pf if pf != float('inf') else '∞'}   avgR {m['avg_R']}   "
        f"return {m['total_return']:+.2%}   maxDD {m['max_drawdown']:.2%}   "
        f"sharpe {m['sharpe']}   conf: {m['significance']}"
    )

    fig.update_layout(
        title=dict(text=f"{title}<br><sub>{header}</sub>", x=0.01,
                   font=dict(color="white", size=15)),
        showlegend=False, margin=dict(l=50, r=20, b=30, t=70),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor=BG, font=dict(color="white"),
        width=1100, height=620,
    )
    fig.update_xaxes(showgrid=False, color="rgba(255,255,255,0.5)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.06)",
                     color="rgba(255,255,255,0.5)")
    return fig


def save_report(result: BacktestResult, html_path: Optional[str] = "xauusd_report.html",
                png_path: Optional[str] = None,
                title: str = "XAUUSD · SMC Agent") -> go.Figure:
    """Render the tearsheet to HTML and/or PNG. Returns the figure."""
    fig = build_report_figure(result, title=title)
    if html_path:
        fig.write_html(html_path, include_plotlyjs="cdn")
    if png_path:
        fig.write_image(png_path)
    return fig
