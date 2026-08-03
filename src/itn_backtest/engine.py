"""Fast single-pass approximate replay engine."""

from __future__ import annotations

import heapq
import math
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pyarrow as pa

from .config import BacktestConfig


ACTIVE = 0
RESERVED = 1
USED = 2
EXPIRED = 3


@dataclass
class Trade:
    trade_id: int
    quote_index: int
    quote_row_id: str
    quote_received_ts_ns: int
    quote_expiry_ts_ns: int
    quote_price_usd: float
    signal_ts_ns: int
    signal_bid: float
    signal_edge_bps: float
    protective_sell_limit: float
    token_qty: float
    stock_qty: float
    stock_arrival_ts_ns: int
    status: str = "pending_stock"
    failure_reason: Optional[str] = None
    stock_bid_at_arrival: Optional[float] = None
    stock_bid_size_at_arrival: Optional[float] = None
    stock_fill_ts_ns: Optional[int] = None
    stock_fill_price: Optional[float] = None
    stock_fill_qty: float = 0.0
    rfq_deadline_ts_ns: Optional[int] = None
    token_received_ts_ns: Optional[int] = None
    redeem_submitted_ts_ns: Optional[int] = None
    redeem_completed_ts_ns: Optional[int] = None
    stock_short_proceeds_usd: float = 0.0
    token_buy_cost_usd: float = 0.0
    reserved_token_cost_usd: float = 0.0
    reserved_short_margin_usd: float = 0.0
    short_margin_locked_usd: float = 0.0
    gross_pnl_usd: Optional[float] = None
    total_cost_usd: Optional[float] = None
    net_pnl_usd: Optional[float] = None
    stock_order_id: Optional[str] = None
    rfq_order_id: Optional[str] = None
    redeem_order_id: Optional[str] = None
    cover_order_id: Optional[str] = None
    finalized: bool = False

    def to_row(self) -> Dict[str, Any]:
        completion = self.redeem_completed_ts_ns
        if completion is None:
            completion = self.stock_fill_ts_ns or self.stock_arrival_ts_ns
        return {
            "trade_id": self.trade_id,
            "status": self.status,
            "failure_reason": self.failure_reason,
            "quote_row_id": self.quote_row_id,
            "quote_received_ts_ns": self.quote_received_ts_ns,
            "quote_expiry_ts_ns": self.quote_expiry_ts_ns,
            "quote_price_usd": self.quote_price_usd,
            "quote_age_at_signal_ms": (self.signal_ts_ns - self.quote_received_ts_ns) / 1_000_000,
            "token_qty": self.token_qty,
            "stock_qty": self.stock_qty,
            "signal_ts_ns": self.signal_ts_ns,
            "signal_bid": self.signal_bid,
            "signal_edge_bps": self.signal_edge_bps,
            "protective_sell_limit": self.protective_sell_limit,
            "stock_arrival_ts_ns": self.stock_arrival_ts_ns,
            "stock_bid_at_arrival": self.stock_bid_at_arrival,
            "stock_bid_size_at_arrival": self.stock_bid_size_at_arrival,
            "stock_fill_ts_ns": self.stock_fill_ts_ns,
            "stock_fill_price": self.stock_fill_price,
            "stock_fill_qty": self.stock_fill_qty,
            "rfq_deadline_ts_ns": self.rfq_deadline_ts_ns,
            "token_received_ts_ns": self.token_received_ts_ns,
            "redeem_submitted_ts_ns": self.redeem_submitted_ts_ns,
            "redeem_completed_ts_ns": self.redeem_completed_ts_ns,
            "signal_to_arrival_ms": (self.stock_arrival_ts_ns - self.signal_ts_ns) / 1_000_000,
            "stock_to_token_ms": _duration_ms(self.stock_fill_ts_ns, self.token_received_ts_ns),
            "token_to_redeem_complete_ms": _duration_ms(self.token_received_ts_ns, self.redeem_completed_ts_ns),
            "total_lifecycle_ms": (completion - self.signal_ts_ns) / 1_000_000,
            "stock_short_proceeds_usd": self.stock_short_proceeds_usd,
            "token_buy_cost_usd": self.token_buy_cost_usd,
            "reserved_token_cost_usd": self.reserved_token_cost_usd,
            "reserved_short_margin_usd": self.reserved_short_margin_usd,
            "short_margin_locked_usd": self.short_margin_locked_usd,
            "gross_pnl_usd": self.gross_pnl_usd,
            "total_cost_usd": self.total_cost_usd,
            "net_pnl_usd": self.net_pnl_usd,
            "stock_order_id": self.stock_order_id,
            "rfq_order_id": self.rfq_order_id,
            "redeem_order_id": self.redeem_order_id,
            "cover_order_id": self.cover_order_id,
        }


def _duration_ms(start: Optional[int], end: Optional[int]) -> Optional[float]:
    if start is None or end is None:
        return None
    return (end - start) / 1_000_000


class QuoteBook:
    """Time-expiring, one-time-use quotes with fast minimum-price lookup."""

    def __init__(self, ttl_ns: int) -> None:
        self.ttl_ns = ttl_ns
        self.received: List[int] = []
        self.expiry: List[int] = []
        self.prices: List[float] = []
        self.states: List[int] = []
        self.expiry_queue: Deque[int] = deque()
        self.min_heap: List[Tuple[float, int]] = []
        self.active_count = 0

    def add(self, received_ts_ns: int, price: float) -> int:
        quote_id = len(self.prices)
        self.received.append(received_ts_ns)
        self.expiry.append(received_ts_ns + self.ttl_ns)
        self.prices.append(price)
        self.states.append(ACTIVE)
        self.expiry_queue.append(quote_id)
        heapq.heappush(self.min_heap, (price, quote_id))
        self.active_count += 1
        return quote_id

    def expire(self, now_ts_ns: int) -> None:
        while self.expiry_queue and self.expiry[self.expiry_queue[0]] <= now_ts_ns:
            quote_id = self.expiry_queue.popleft()
            if self.states[quote_id] in (ACTIVE, RESERVED):
                if self.states[quote_id] == ACTIVE:
                    self.active_count -= 1
                self.states[quote_id] = EXPIRED

    def best(self, now_ts_ns: int) -> Optional[int]:
        self.expire(now_ts_ns)
        while self.min_heap:
            _, quote_id = self.min_heap[0]
            if self.states[quote_id] == ACTIVE and self.expiry[quote_id] > now_ts_ns:
                return quote_id
            heapq.heappop(self.min_heap)
        return None

    def reserve(self, quote_id: int) -> bool:
        if self.states[quote_id] != ACTIVE:
            return False
        self.states[quote_id] = RESERVED
        self.active_count -= 1
        return True

    def release(self, quote_id: int, now_ts_ns: int) -> None:
        self.expire(now_ts_ns)
        if self.states[quote_id] == RESERVED:
            self.states[quote_id] = ACTIVE
            self.active_count += 1
            heapq.heappush(self.min_heap, (self.prices[quote_id], quote_id))

    def use(self, quote_id: int) -> bool:
        if self.states[quote_id] != RESERVED:
            return False
        self.states[quote_id] = USED
        return True

    def discard(self, quote_id: int) -> None:
        """Permanently remove an active quote that can no longer be safely used."""

        if self.states[quote_id] == ACTIVE:
            self.active_count -= 1
            self.states[quote_id] = EXPIRED


@dataclass
class ReplayResult:
    trades: List[Dict[str, Any]]
    orders: List[Dict[str, Any]]
    opportunities: List[Dict[str, Any]]
    state_changes: List[Dict[str, Any]]
    summary: Dict[str, Any]
    debug_trace: List[Dict[str, Any]] = field(default_factory=list)


class ReplayEngine:
    """Single-pass state machine for independent, capital-constrained RFQ trades."""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.quote_book = QuoteBook(config.quote_ttl_ns)
        self.scheduled: List[Tuple[int, int, str, int]] = []
        self.schedule_sequence = 0
        self.trades_by_id: Dict[int, Trade] = {}
        self.final_trades: List[Dict[str, Any]] = []
        self.orders: List[Dict[str, Any]] = []
        self.orders_by_id: Dict[str, Dict[str, Any]] = {}
        self.next_order_id = 1
        self.opportunities: List[Dict[str, Any]] = []
        self.state_changes: List[Dict[str, Any]] = []
        self.debug_trace: List[Dict[str, Any]] = []
        self.active_trade_ids: set[int] = set()
        self.next_trade_id = 1
        self.latest_market: Optional[Dict[str, float]] = None
        self.bid_size_consumed_by_snapshot: Dict[int, float] = {}
        self.reserved_token_cost_by_trade: Dict[int, float] = {}
        self.reserved_short_margin_by_trade: Dict[int, float] = {}
        self.locked_net_by_trade: Dict[int, float] = {}
        self.stock_position_qty = 0.0
        self.wallet_token_qty = 0.0
        self.redeem_pending_qty = 0.0
        self.unhedged_short_qty = 0.0
        self.open_trade_count = 0
        self.cumulative_gross_pnl = 0.0
        self.cumulative_total_cost = 0.0
        self.cumulative_realized_net_pnl = 0.0
        self.cumulative_locked_net_pnl = 0.0
        self.initial_capital_usd = float(config.capital["initial_capital_usd"])
        self.cash_balance_usd = self.initial_capital_usd

    def run(self, table: pa.Table) -> ReplayResult:
        data = table.to_pydict()
        timestamps = np.asarray(data["received_ts_ns"], dtype=np.int64)
        if timestamps.size == 0:
            return ReplayResult([], [], [], [], self._summary())
        self._state("run_started", None, int(timestamps[0]), 0.0)
        for index, now_ts_ns in enumerate(timestamps):
            self._process_due(int(now_ts_ns) - 1)
            self.quote_book.expire(int(now_ts_ns))
            self._update_market(data, index)
            quote_id = self.quote_book.add(int(now_ts_ns), float(data["rfq_price_usd"][index]))
            self._process_due(int(now_ts_ns))
            self._evaluate_opportunity(data, index, quote_id)
            self._process_due(int(now_ts_ns))

        self._process_due(int(timestamps[-1]))
        self._finalize_open_at_end(int(timestamps[-1]))
        return ReplayResult(
            trades=self.final_trades,
            orders=self.orders,
            opportunities=self.opportunities,
            state_changes=self.state_changes,
            summary=self._summary(),
            debug_trace=self.debug_trace,
        )

    def _update_market(self, data: Dict[str, Sequence[Any]], index: int) -> None:
        self.latest_market = {
            "timestamp_ns": int(data["received_ts_ns"][index]),
            "bid": float(data["bid"][index]),
            "ask": float(data["ask"][index]),
            "bid_size": float(data["bid_size"][index]),
            "ask_size": float(data["ask_size"][index]),
            "quote_age_s": float(data["stock_quote_age_s"][index]),
            "quote_stale": bool(data["stock_quote_stale"][index]),
        }

    @property
    def reserved_token_cost_usd(self) -> float:
        return sum(self.reserved_token_cost_by_trade.values())

    @property
    def reserved_short_margin_usd(self) -> float:
        return sum(self.reserved_short_margin_by_trade.values())

    @property
    def total_reserved_capital_usd(self) -> float:
        return self.reserved_token_cost_usd + self.reserved_short_margin_usd

    @property
    def available_cash_usd(self) -> float:
        return self.cash_balance_usd - self.total_reserved_capital_usd

    def _at_open_trade_cap(self) -> bool:
        cap = self.config.strategy["max_open_trades"]
        return cap is not None and len(self.active_trade_ids) >= int(cap)

    def _refresh_locked_pnl(self) -> None:
        self.cumulative_locked_net_pnl = self.cumulative_realized_net_pnl + sum(
            self.locked_net_by_trade.values()
        )

    def _stock_data_eligible(self) -> bool:
        if self.latest_market is None:
            return False
        age = self.latest_market["quote_age_s"]
        return (
            math.isfinite(self.latest_market["bid"])
            and math.isfinite(self.latest_market["ask"])
            and math.isfinite(age)
            and age <= float(self.config.data["max_stock_quote_age_s"])
            and not self.latest_market["quote_stale"]
        )

    def _evaluate_opportunity(self, data: Dict[str, Sequence[Any]], index: int, _new_quote_id: int) -> None:
        now = int(data["received_ts_ns"][index])
        best_quote_id = self.quote_book.best(now)
        eligible = self._stock_data_eligible()
        bid = self.latest_market["bid"] if self.latest_market else float("nan")
        price = self.quote_book.prices[best_quote_id] if best_quote_id is not None else None
        stock_qty = self.config.stock_qty
        token_cost = price * self.config.token_qty if price is not None else None
        edge = None
        limit = None
        if price is not None and eligible:
            notional = bid * stock_qty
            edge = (notional - token_cost) / notional * 10_000
            limit = (token_cost / stock_qty) / (1 - self.config.required_gross_edge_bps / 10_000)

        reason = "edge_below_required_profit"
        triggered_trade_ids: List[int] = []
        if best_quote_id is None:
            reason = "no_active_quote"
        elif not eligible:
            reason = "stock_quote_stale"
        else:
            # Quotes are tried from low to high price.  With a fixed quantity, once
            # the best one fails the edge/capital test, costlier quotes cannot pass.
            while not self._at_open_trade_cap():
                quote_id = self.quote_book.best(now)
                if quote_id is None:
                    reason = "no_active_quote" if not triggered_trade_ids else "triggered"
                    break
                candidate_price = self.quote_book.prices[quote_id]
                candidate_cost = candidate_price * self.config.token_qty
                estimated_margin = (
                    bid * stock_qty * float(self.config.capital["short_margin_ratio"])
                )
                candidate_notional = bid * stock_qty
                candidate_edge = (candidate_notional - candidate_cost) / candidate_notional * 10_000
                if candidate_edge <= self.config.required_gross_edge_bps:
                    reason = "edge_below_required_profit" if not triggered_trade_ids else "triggered"
                    break
                estimated_deadline = (
                    now
                    + self.config.stock_arrival_delay_ns
                    + self.config.stock_report_delay_ns
                    + self.config.rfq_execution_delay_ns
                )
                if estimated_deadline > self.quote_book.expiry[quote_id] - self.config.expiry_buffer_ns:
                    self.quote_book.discard(quote_id)
                    reason = "quote_expiry_insufficient"
                    continue
                if self.available_cash_usd + 1e-9 < candidate_cost + estimated_margin:
                    reason = "capital_insufficient" if not triggered_trade_ids else "triggered"
                    break
                if not self.quote_book.reserve(quote_id):
                    reason = "no_active_quote"
                    break
                candidate_limit = (candidate_cost / stock_qty) / (
                    1 - self.config.required_gross_edge_bps / 10_000
                )
                trade = self._start_trade(quote_id, now, bid, candidate_edge, candidate_limit)
                triggered_trade_ids.append(trade.trade_id)
            else:
                reason = "max_open_trades_reached" if not triggered_trade_ids else "triggered"

        if self.config.output["save_opportunity_series"]:
            self.opportunities.append(
                {
                    "decision_ts_ns": now,
                    "source_row_id": data["source_row_id"][index],
                    "current_bid": bid,
                    "current_bid_size": self.latest_market["bid_size"] if self.latest_market else None,
                    "stock_quote_age_s": self.latest_market["quote_age_s"] if self.latest_market else None,
                    "best_quote_row_id": data["source_row_id"][best_quote_id] if best_quote_id is not None else None,
                    "best_quote_received_ts_ns": self.quote_book.received[best_quote_id] if best_quote_id is not None else None,
                    "best_quote_expiry_ts_ns": self.quote_book.expiry[best_quote_id] if best_quote_id is not None else None,
                    "best_quote_price_usd": price,
                    "best_quote_age_ms": (now - self.quote_book.received[best_quote_id]) / 1_000_000 if best_quote_id is not None else None,
                    "active_quote_count": self.quote_book.active_count,
                    "gross_edge_bps": edge,
                    "protective_sell_limit": limit,
                    "is_stock_data_eligible": eligible,
                    "is_trigger": bool(triggered_trade_ids),
                    "skip_reason": reason,
                    "triggered_trade_count": len(triggered_trade_ids),
                    "reserved_trade_ids": ",".join(str(value) for value in triggered_trade_ids) or None,
                    "required_gross_edge_bps": self.config.required_gross_edge_bps,
                    "reserved_token_cost_usd": self.reserved_token_cost_usd,
                    "available_cash_usd": self.available_cash_usd,
                }
            )

    def _start_trade(self, quote_id: int, now: int, bid: float, edge: float, limit: float) -> Trade:
        trade = Trade(
            trade_id=self.next_trade_id,
            quote_index=quote_id,
            quote_row_id="",  # populated from source data by caller immediately below
            quote_received_ts_ns=self.quote_book.received[quote_id],
            quote_expiry_ts_ns=self.quote_book.expiry[quote_id],
            quote_price_usd=self.quote_book.prices[quote_id],
            signal_ts_ns=now,
            signal_bid=bid,
            signal_edge_bps=edge,
            protective_sell_limit=limit,
            token_qty=self.config.token_qty,
            stock_qty=self.config.stock_qty,
            stock_arrival_ts_ns=now + self.config.stock_arrival_delay_ns,
            reserved_token_cost_usd=self.quote_book.prices[quote_id] * self.config.token_qty,
            reserved_short_margin_usd=(
                bid * self.config.stock_qty * float(self.config.capital["short_margin_ratio"])
            ),
        )
        # The engine stores source IDs lazily in a private mapping set by caller.
        trade.quote_row_id = self._quote_row_ids[quote_id]
        self.next_trade_id += 1
        self.trades_by_id[trade.trade_id] = trade
        self.active_trade_ids.add(trade.trade_id)
        self.reserved_token_cost_by_trade[trade.trade_id] = trade.reserved_token_cost_usd
        self.reserved_short_margin_by_trade[trade.trade_id] = trade.reserved_short_margin_usd
        self.open_trade_count = len(self.active_trade_ids)
        trade.stock_order_id = self._create_order(
            trade=trade,
            order_type="stock_sell_short",
            venue="Alpaca",
            side="sell_short",
            symbol=self.config.universe["underlying_symbol"],
            quantity=trade.stock_qty,
            created_ts_ns=now,
            submitted_ts_ns=now + int(self.config.latency_ms["strategy_compute"] * 1_000_000),
            market_arrival_ts_ns=trade.stock_arrival_ts_ns,
            limit_price=trade.protective_sell_limit,
            quote_row_id=trade.quote_row_id,
            quote_price_usd=trade.quote_price_usd,
        )
        self._state("quote_reserved", trade, now, 0.0)
        self._schedule(trade.stock_arrival_ts_ns, "stock_arrival", trade.trade_id)
        return trade

    def _create_order(
        self,
        trade: Trade,
        order_type: str,
        venue: str,
        side: str,
        symbol: str,
        quantity: float,
        created_ts_ns: int,
        submitted_ts_ns: Optional[int] = None,
        market_arrival_ts_ns: Optional[int] = None,
        limit_price: Optional[float] = None,
        quote_row_id: Optional[str] = None,
        quote_price_usd: Optional[float] = None,
    ) -> str:
        order_id = "sim-%06d" % self.next_order_id
        self.next_order_id += 1
        row = {
            "order_id": order_id,
            "trade_id": trade.trade_id,
            "order_type": order_type,
            "venue": venue,
            "side": side,
            "symbol": symbol,
            "quantity": quantity,
            "created_ts_ns": created_ts_ns,
            "submitted_ts_ns": submitted_ts_ns,
            "market_arrival_ts_ns": market_arrival_ts_ns,
            "response_ts_ns": None,
            "completed_ts_ns": None,
            "status": "submitted",
            "failure_reason": None,
            "limit_price": limit_price,
            "reference_market_bid": None,
            "reference_market_ask": None,
            "reference_bid_size": None,
            "available_bid_size_at_arrival": None,
            "filled_qty": 0.0,
            "fill_price": None,
            "notional_usd": None,
            "underlying_qty_received": 0.0,
            "quote_row_id": quote_row_id,
            "quote_price_usd": quote_price_usd,
        }
        self.orders.append(row)
        self.orders_by_id[order_id] = row
        return order_id

    def _update_order(self, order_id: Optional[str], **changes: Any) -> None:
        if order_id is None:
            return
        self.orders_by_id[order_id].update(changes)

    def _schedule(self, timestamp: int, event_type: str, trade_id: int) -> None:
        self.schedule_sequence += 1
        heapq.heappush(self.scheduled, (timestamp, self.schedule_sequence, event_type, trade_id))

    def _process_due(self, up_to_ts_ns: int) -> None:
        while self.scheduled and self.scheduled[0][0] <= up_to_ts_ns:
            timestamp, _, event_type, trade_id = heapq.heappop(self.scheduled)
            trade = self.trades_by_id.get(trade_id)
            if trade is None or trade.finalized:
                continue
            self.quote_book.expire(timestamp)
            self._process_event(timestamp, event_type, trade)

    def _process_event(self, timestamp: int, event_type: str, trade: Trade) -> None:
        if event_type == "stock_arrival":
            self._on_stock_arrival(timestamp, trade)
        elif event_type == "stock_report":
            self._on_stock_report(timestamp, trade)
        elif event_type == "rfq_execute":
            self._on_rfq_execute(timestamp, trade)
        elif event_type == "token_received":
            self._on_token_received(timestamp, trade)
        elif event_type == "redeem_submitted":
            self._on_redeem_submitted(timestamp, trade)
        elif event_type == "redeem_completed":
            self._on_redeem_completed(timestamp, trade)
        elif event_type == "emergency_cover":
            self._on_emergency_cover(timestamp, trade)
        else:
            raise RuntimeError("Unknown scheduled event: %s" % event_type)

    def _on_stock_arrival(self, timestamp: int, trade: Trade) -> None:
        market = self.latest_market
        if market is None or not self._stock_data_eligible() or self.quote_book.states[trade.quote_index] != RESERVED:
            trade.failure_reason = "stock_data_unavailable" if market is None or not self._stock_data_eligible() else "quote_expired_before_stock"
            self._update_order(
                trade.stock_order_id,
                response_ts_ns=timestamp + self.config.stock_report_delay_ns,
                completed_ts_ns=timestamp + self.config.stock_report_delay_ns,
                status="rejected",
                failure_reason=trade.failure_reason,
            )
            self._schedule(timestamp + self.config.stock_report_delay_ns, "stock_report", trade.trade_id)
            return
        trade.stock_bid_at_arrival = market["bid"]
        snapshot_ts_ns = int(market["timestamp_ns"])
        consumed_bid_size = self.bid_size_consumed_by_snapshot.get(snapshot_ts_ns, 0.0)
        available_bid_size = max(0.0, market["bid_size"] - consumed_bid_size)
        trade.stock_bid_size_at_arrival = available_bid_size
        self._update_order(
            trade.stock_order_id,
            reference_market_bid=market["bid"],
            reference_market_ask=market["ask"],
            reference_bid_size=market["bid_size"],
            available_bid_size_at_arrival=available_bid_size,
            response_ts_ns=timestamp + self.config.stock_report_delay_ns,
        )
        fill_price = market["bid"] * (1 - float(self.config.stock_execution["short_slippage_bps"]) / 10_000)
        size_ok = (not self.config.stock_execution["require_bid_size"] or available_bid_size >= trade.stock_qty)
        price_ok = (
            not self.config.stock_execution["use_protective_sell_limit"]
            or fill_price > trade.protective_sell_limit
        )
        actual_short_proceeds = fill_price * trade.stock_qty
        actual_margin = actual_short_proceeds * float(self.config.capital["short_margin_ratio"])
        estimated_margin = self.reserved_short_margin_by_trade.get(trade.trade_id, 0.0)
        additional_margin_required = max(0.0, actual_margin - estimated_margin)
        margin_ok = self.available_cash_usd + 1e-9 >= additional_margin_required
        if price_ok and size_ok and margin_ok:
            trade.stock_fill_ts_ns = timestamp
            trade.stock_fill_price = fill_price
            trade.stock_fill_qty = trade.stock_qty
            trade.stock_short_proceeds_usd = actual_short_proceeds
            trade.short_margin_locked_usd = actual_margin
            self.reserved_short_margin_by_trade[trade.trade_id] = actual_margin
            trade.status = "stock_filled"
            if self.config.stock_execution["require_bid_size"]:
                self.bid_size_consumed_by_snapshot[snapshot_ts_ns] = consumed_bid_size + trade.stock_qty
            self._update_order(
                trade.stock_order_id,
                completed_ts_ns=timestamp,
                status="filled",
                filled_qty=trade.stock_qty,
                fill_price=fill_price,
                notional_usd=trade.stock_short_proceeds_usd,
            )
            self.stock_position_qty -= trade.stock_qty
            self.unhedged_short_qty += trade.stock_qty
            # Short-sale proceeds are not treated as reusable cash while the
            # short is open.  They are credited only once the position closes.
            self._state("stock_filled", trade, timestamp, 0.0)
        else:
            if not price_ok:
                trade.failure_reason = "stock_limit_not_met"
            elif not size_ok:
                trade.failure_reason = "insufficient_bid_size"
            else:
                trade.failure_reason = "insufficient_short_margin"
            self._update_order(
                trade.stock_order_id,
                completed_ts_ns=timestamp + self.config.stock_report_delay_ns,
                status="rejected",
                failure_reason=trade.failure_reason,
            )
        self._schedule(timestamp + self.config.stock_report_delay_ns, "stock_report", trade.trade_id)

    def _on_stock_report(self, timestamp: int, trade: Trade) -> None:
        if trade.stock_fill_qty <= 0:
            trade.status = "stock_rejected"
            self.quote_book.release(trade.quote_index, timestamp)
            self.reserved_token_cost_by_trade.pop(trade.trade_id, None)
            self.reserved_short_margin_by_trade.pop(trade.trade_id, None)
            self._finalize(trade)
            self._state("stock_rejected", trade, timestamp, 0.0)
            return
        trade.rfq_deadline_ts_ns = timestamp + self.config.rfq_execution_delay_ns
        trade.rfq_order_id = self._create_order(
            trade=trade,
            order_type="rfq_buy_token",
            venue="Ondo/Fireblocks",
            side="buy",
            symbol=self.config.universe["token_symbol"],
            quantity=trade.token_qty,
            created_ts_ns=timestamp,
            submitted_ts_ns=timestamp + int(self.config.latency_ms["rfq_submit"] * 1_000_000),
            market_arrival_ts_ns=trade.rfq_deadline_ts_ns,
            quote_row_id=trade.quote_row_id,
            quote_price_usd=trade.quote_price_usd,
        )
        self._schedule(trade.rfq_deadline_ts_ns, "rfq_execute", trade.trade_id)

    def _on_rfq_execute(self, timestamp: int, trade: Trade) -> None:
        valid_until = trade.quote_expiry_ts_ns - self.config.expiry_buffer_ns
        if timestamp > valid_until or not self.quote_book.use(trade.quote_index):
            trade.status = "rfq_expired"
            trade.failure_reason = "rfq_expired"
            self.reserved_token_cost_by_trade.pop(trade.trade_id, None)
            self._update_order(
                trade.rfq_order_id,
                response_ts_ns=timestamp,
                completed_ts_ns=timestamp,
                status="expired",
                failure_reason="rfq_expired",
            )
            trade.cover_order_id = self._create_order(
                trade=trade,
                order_type="emergency_buy_to_cover",
                venue="Alpaca",
                side="buy_to_cover",
                symbol=self.config.universe["underlying_symbol"],
                quantity=trade.stock_qty,
                created_ts_ns=timestamp,
                submitted_ts_ns=timestamp + int(self.config.latency_ms["emergency_cover_submit"] * 1_000_000),
                market_arrival_ts_ns=timestamp + self.config.emergency_cover_delay_ns,
                quote_row_id=trade.quote_row_id,
                quote_price_usd=trade.quote_price_usd,
            )
            self._state("rfq_expired", trade, timestamp, 0.0)
            self._schedule(timestamp + self.config.emergency_cover_delay_ns, "emergency_cover", trade.trade_id)
            return
        self._schedule(trade.stock_fill_ts_ns + self.config.stock_report_delay_ns + self.config.token_received_delay_ns, "token_received", trade.trade_id)

    def _on_token_received(self, timestamp: int, trade: Trade) -> None:
        trade.status = "token_received"
        trade.token_received_ts_ns = timestamp
        trade.token_buy_cost_usd = trade.quote_price_usd * trade.token_qty
        trade.gross_pnl_usd = trade.stock_short_proceeds_usd - trade.token_buy_cost_usd
        trade.total_cost_usd = trade.stock_short_proceeds_usd * float(self.config.costs["total_cost_deduction_bps"]) / 10_000
        trade.net_pnl_usd = trade.gross_pnl_usd - trade.total_cost_usd
        self._update_order(
            trade.rfq_order_id,
            response_ts_ns=timestamp,
            completed_ts_ns=timestamp,
            status="filled",
            filled_qty=trade.token_qty,
            fill_price=trade.quote_price_usd,
            notional_usd=trade.token_buy_cost_usd,
        )
        # The reservation guarded the cash before the stock leg.  It becomes an
        # actual Token cash outflow only after the RFQ is filled.
        self.reserved_token_cost_by_trade.pop(trade.trade_id, None)
        self.wallet_token_qty += trade.token_qty
        self.unhedged_short_qty -= trade.stock_qty
        self.locked_net_by_trade[trade.trade_id] = trade.net_pnl_usd
        self._refresh_locked_pnl()
        self._state("token_received", trade, timestamp, -trade.token_buy_cost_usd)
        trade.redeem_submitted_ts_ns = timestamp + self.config.redeem_submit_delay_ns
        trade.redeem_completed_ts_ns = trade.stock_fill_ts_ns + self.config.stock_report_delay_ns + self.config.token_received_delay_ns + self.config.redeem_complete_delay_ns
        trade.redeem_order_id = self._create_order(
            trade=trade,
            order_type="itn_redeem",
            venue="Ondo/Alpaca ITN",
            side="redeem",
            symbol=self.config.universe["token_symbol"],
            quantity=trade.token_qty,
            created_ts_ns=timestamp,
            submitted_ts_ns=trade.redeem_submitted_ts_ns,
            market_arrival_ts_ns=trade.redeem_completed_ts_ns,
            quote_row_id=trade.quote_row_id,
            quote_price_usd=trade.quote_price_usd,
        )
        self._schedule(trade.redeem_submitted_ts_ns, "redeem_submitted", trade.trade_id)
        self._schedule(trade.redeem_completed_ts_ns, "redeem_completed", trade.trade_id)

    def _on_redeem_submitted(self, timestamp: int, trade: Trade) -> None:
        trade.status = "redeem_pending"
        self._update_order(trade.redeem_order_id, status="submitted", response_ts_ns=timestamp)
        self.wallet_token_qty -= trade.token_qty
        self.redeem_pending_qty += trade.stock_qty
        self._state("redeem_submitted", trade, timestamp, 0.0)

    def _on_redeem_completed(self, timestamp: int, trade: Trade) -> None:
        trade.status = "completed"
        self.stock_position_qty += trade.stock_qty
        self.redeem_pending_qty -= trade.stock_qty
        self.cumulative_gross_pnl += trade.gross_pnl_usd or 0.0
        self.cumulative_total_cost += trade.total_cost_usd or 0.0
        self.cumulative_realized_net_pnl += trade.net_pnl_usd or 0.0
        self.locked_net_by_trade.pop(trade.trade_id, None)
        self._refresh_locked_pnl()
        self._update_order(
            trade.redeem_order_id,
            completed_ts_ns=timestamp,
            status="completed",
            filled_qty=trade.token_qty,
            underlying_qty_received=trade.stock_qty,
        )
        self.reserved_short_margin_by_trade.pop(trade.trade_id, None)
        self._finalize(trade)
        self._state(
            "redeem_completed",
            trade,
            timestamp,
            trade.stock_short_proceeds_usd - (trade.total_cost_usd or 0.0),
        )

    def _on_emergency_cover(self, timestamp: int, trade: Trade) -> None:
        market = self.latest_market
        if market is None or not self._stock_data_eligible():
            trade.status = "unresolved_end_of_data"
            trade.failure_reason = "cover_data_unavailable"
            self._update_order(
                trade.cover_order_id,
                completed_ts_ns=timestamp,
                status="unresolved",
                failure_reason=trade.failure_reason,
            )
            self.reserved_token_cost_by_trade.pop(trade.trade_id, None)
            self._finalize(trade)
            self._state("unresolved_end_of_data", trade, timestamp, 0.0)
            return
        cover_price = market["ask"] * (1 + float(self.config.stock_execution["cover_slippage_bps"]) / 10_000)
        cover_cost = cover_price * trade.stock_qty
        trade.gross_pnl_usd = trade.stock_short_proceeds_usd - cover_cost
        trade.total_cost_usd = trade.stock_short_proceeds_usd * float(self.config.costs["total_cost_deduction_bps"]) / 10_000
        trade.net_pnl_usd = trade.gross_pnl_usd - trade.total_cost_usd
        self._update_order(
            trade.cover_order_id,
            reference_market_ask=market["ask"],
            completed_ts_ns=timestamp,
            status="filled",
            filled_qty=trade.stock_qty,
            fill_price=cover_price,
            notional_usd=cover_cost,
        )
        self.stock_position_qty += trade.stock_qty
        self.unhedged_short_qty -= trade.stock_qty
        self.cumulative_gross_pnl += trade.gross_pnl_usd
        self.cumulative_total_cost += trade.total_cost_usd
        self.cumulative_realized_net_pnl += trade.net_pnl_usd
        self.locked_net_by_trade.pop(trade.trade_id, None)
        self._refresh_locked_pnl()
        self.reserved_short_margin_by_trade.pop(trade.trade_id, None)
        self._finalize(trade)
        self._state(
            "emergency_covered",
            trade,
            timestamp,
            trade.stock_short_proceeds_usd - cover_cost - trade.total_cost_usd,
        )

    def _state(self, event_type: str, trade: Optional[Trade], timestamp: int, cash_flow: float) -> None:
        self.cash_balance_usd += cash_flow
        equity_balance_usd = self.initial_capital_usd + self.cumulative_locked_net_pnl
        if not self.config.output["save_state_series"]:
            return
        self.state_changes.append(
            {
                "state_ts_ns": timestamp,
                "event_type": event_type,
                "trade_id": trade.trade_id if trade is not None else None,
                "stock_position_qty": self.stock_position_qty,
                "wallet_token_qty": self.wallet_token_qty,
                "redeem_pending_qty": self.redeem_pending_qty,
                "unhedged_short_qty": self.unhedged_short_qty,
                "open_trade_count": self.open_trade_count,
                "cash_flow_usd": cash_flow,
                "cash_balance_usd": self.cash_balance_usd,
                "reserved_token_cost_usd": self.reserved_token_cost_usd,
                "reserved_short_margin_usd": self.reserved_short_margin_usd,
                "total_reserved_capital_usd": self.total_reserved_capital_usd,
                "available_cash_usd": self.available_cash_usd,
                "equity_balance_usd": equity_balance_usd,
                "initial_capital_usd": self.initial_capital_usd,
                "cumulative_gross_pnl_usd": self.cumulative_gross_pnl,
                "cumulative_total_cost_usd": self.cumulative_total_cost,
                "cumulative_locked_net_pnl_usd": self.cumulative_locked_net_pnl,
                "cumulative_realized_net_pnl_usd": self.cumulative_realized_net_pnl,
            }
        )
        if self.config.output["save_debug_trace"]:
            self.debug_trace.append(
                {
                    "timestamp_ns": timestamp,
                    "event_type": event_type,
                    "trade_id": trade.trade_id if trade is not None else None,
                    "quote_row_id": trade.quote_row_id if trade is not None else None,
                    "trade_status": trade.status if trade is not None else "run_started",
                }
            )

    def _finalize(self, trade: Trade) -> None:
        if trade.finalized:
            return
        if trade.status == "stock_rejected":
            trade.gross_pnl_usd = 0.0
            trade.total_cost_usd = 0.0
            trade.net_pnl_usd = 0.0
        trade.finalized = True
        self.final_trades.append(trade.to_row())
        self.active_trade_ids.discard(trade.trade_id)
        self.reserved_token_cost_by_trade.pop(trade.trade_id, None)
        self.open_trade_count = len(self.active_trade_ids)

    def _finalize_open_at_end(self, last_ts_ns: int) -> None:
        for trade_id in list(self.active_trade_ids):
            trade = self.trades_by_id[trade_id]
            if trade.finalized:
                continue
            # An unfinished stock/Token leg remains represented in inventory;
            # only its pre-trade cash reservation is released at simulation end.
            trade.status = "unresolved_end_of_data"
            trade.failure_reason = "end_of_data"
            self.reserved_token_cost_by_trade.pop(trade.trade_id, None)
            if trade.stock_fill_qty <= 0:
                self.reserved_short_margin_by_trade.pop(trade.trade_id, None)
            self._state("unresolved_end_of_data", trade, last_ts_ns, 0.0)
            self._finalize(trade)

    def _summary(self) -> Dict[str, Any]:
        statuses = Counter(row["status"] for row in self.final_trades)
        completed = [row for row in self.final_trades if row["status"] == "completed"]
        daily: Dict[str, Dict[str, Any]] = {}
        for row in self.final_trades:
            timestamp = row["redeem_completed_ts_ns"] or row["stock_arrival_ts_ns"]
            day = datetime.fromtimestamp(timestamp / 1_000_000_000, tz=timezone.utc).date().isoformat()
            bucket = daily.setdefault(
                day,
                {"trades_total": 0, "trades_completed": 0, "gross_pnl_usd": 0.0, "total_cost_usd": 0.0, "net_pnl_usd": 0.0},
            )
            bucket["trades_total"] += 1
            if row["status"] == "completed":
                bucket["trades_completed"] += 1
                bucket["gross_pnl_usd"] += row["gross_pnl_usd"] or 0.0
                bucket["total_cost_usd"] += row["total_cost_usd"] or 0.0
                bucket["net_pnl_usd"] += row["net_pnl_usd"] or 0.0
        return {
            "schema_version": 1,
            "trades_total": len(self.final_trades),
            "trades_completed": len(completed),
            "status_counts": dict(sorted(statuses.items())),
            "gross_pnl_usd": self.cumulative_gross_pnl,
            "total_cost_usd": self.cumulative_total_cost,
            "net_pnl_usd": self.cumulative_realized_net_pnl,
            "initial_capital_usd": self.initial_capital_usd,
            "final_cash_balance_usd": self.cash_balance_usd,
            "final_reserved_token_cost_usd": self.reserved_token_cost_usd,
            "final_reserved_short_margin_usd": self.reserved_short_margin_usd,
            "final_available_cash_usd": self.available_cash_usd,
            "final_equity_balance_usd": self.initial_capital_usd + self.cumulative_locked_net_pnl,
            "completed_win_rate": (
                sum(1 for row in completed if (row["net_pnl_usd"] or 0.0) > 0) / len(completed)
                if completed
                else None
            ),
            "daily": daily,
        }

    @property
    def _quote_row_ids(self) -> List[str]:
        return self.__quote_row_ids

    @_quote_row_ids.setter
    def _quote_row_ids(self, values: List[str]) -> None:
        self.__quote_row_ids = values

    def set_quote_row_ids(self, source_row_ids: Sequence[str]) -> None:
        self._quote_row_ids = list(source_row_ids)


def replay(table: pa.Table, config: BacktestConfig) -> ReplayResult:
    """Run a normalized Arrow table through the fast approximate state machine."""

    engine = ReplayEngine(config)
    engine.set_quote_row_ids(table.column("source_row_id").to_pylist())
    return engine.run(table)
