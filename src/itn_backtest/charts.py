"""Static performance charts for one completed replay run."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang HK", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.9 has zoneinfo
    ZoneInfo = None


def _to_eastern(timestamp_ns: int) -> datetime:
    utc = datetime.fromtimestamp(timestamp_ns / 1_000_000_000, tz=timezone.utc)
    if ZoneInfo is None:
        return utc
    return utc.astimezone(ZoneInfo("America/New_York"))


def write_performance_chart(states: List[Dict[str, Any]], target: Path) -> None:
    """Write a three-panel PnL, inventory, and balance step chart."""

    if not states:
        return
    times = [_to_eastern(row["state_ts_ns"]) for row in states]
    fig, axes = plt.subplots(3, 1, figsize=(15, 11), sharex=True, constrained_layout=True)

    axes[0].step(times, [row["cumulative_realized_net_pnl_usd"] for row in states], where="post", label="已实现净收益", linewidth=1.8)
    axes[0].step(times, [row["cumulative_locked_net_pnl_usd"] for row in states], where="post", label="已锁定净收益", linewidth=1.2, linestyle="--")
    axes[0].axhline(0, color="black", linewidth=0.7)
    axes[0].set_title("ITN Redeem 回测：收益、库存与余额")
    axes[0].set_ylabel("收益（USD）")
    axes[0].legend(loc="best")
    axes[0].grid(alpha=0.25)

    axes[1].step(times, [row["stock_position_qty"] for row in states], where="post", label="股票仓位")
    axes[1].step(times, [row["wallet_token_qty"] for row in states], where="post", label="钱包 Token")
    axes[1].step(times, [row["redeem_pending_qty"] for row in states], where="post", label="Redeem pending")
    axes[1].step(times, [row["unhedged_short_qty"] for row in states], where="post", label="未对冲空头", linestyle="--")
    axes[1].axhline(0, color="black", linewidth=0.7)
    axes[1].set_ylabel("数量")
    axes[1].legend(loc="best", ncol=2)
    axes[1].grid(alpha=0.25)

    axes[2].step(times, [row["cash_balance_usd"] for row in states], where="post", label="现金余额")
    axes[2].step(times, [row["available_cash_usd"] for row in states], where="post", label="可用余额（扣除冻结资金）")
    axes[2].step(times, [row["reserved_short_margin_usd"] for row in states], where="post", label="空头保证金冻结", linestyle=":")
    axes[2].step(times, [row["equity_balance_usd"] for row in states], where="post", label="策略权益余额")
    axes[2].axhline(states[0]["initial_capital_usd"], color="black", linewidth=0.8, linestyle=":", label="初始本金")
    axes[2].set_ylabel("余额（USD）")
    axes[2].set_xlabel("美东时间")
    axes[2].legend(loc="best")
    axes[2].grid(alpha=0.25)
    axes[2].xaxis.set_major_locator(mdates.AutoDateLocator())
    axes[2].xaxis.set_major_formatter(mdates.ConciseDateFormatter(axes[2].xaxis.get_major_locator()))

    fig.savefig(target, dpi=160)
    plt.close(fig)
