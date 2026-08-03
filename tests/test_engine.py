import pyarrow as pa

from itn_backtest.config import load_config
from itn_backtest.engine import replay


def _table(rows):
    return pa.Table.from_pylist(rows)


def _row(timestamp, row_id, price, bid, ask=None, bid_size=100):
    return {
        "source_row_id": row_id,
        "request_ts_ns": timestamp,
        "received_ts_ns": timestamp,
        "rtt_ms": 1.0,
        "symbol": "AAPL",
        "token_symbol": "AAPLx",
        "rfq_price_usd": price,
        "bid": bid,
        "ask": ask if ask is not None else bid + 0.01,
        "bid_size": bid_size,
        "ask_size": 100.0,
        "stock_quote_age_s": 0.0,
        "stock_quote_stale": False,
        "secs_since_price_change": 0.0,
    }


def _zero_latency_config():
    return load_config(
        overrides={
            "latency_ms": {
                "strategy_compute": 0,
                "alpaca_submit": 0,
                "exchange_route": 0,
                "stock_fill_report": 0,
                "rfq_submit": 0,
                "fireblocks_policy": 0,
                "fireblocks_sign": 0,
                "tx_broadcast": 0,
                "chain_confirm": 0,
                "redeem_submit": 0,
                "redeem_chain_confirm": 0,
                "issuer_process": 0,
                "alpaca_journal": 0,
                "emergency_cover_submit": 0,
                "emergency_cover_route": 0,
            },
            "rfq": {"expiry_safety_buffer_ms": 0, "ttl_seconds": 0.15},
        }
    )


def test_completed_trade_records_final_cost_once():
    result = replay(_table([_row(1_000_000_000, "one", 100.0, 101.0)]), _zero_latency_config())
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade["status"] == "completed"
    assert trade["stock_short_proceeds_usd"] == 1010.0
    assert trade["token_buy_cost_usd"] == 1000.0
    assert trade["gross_pnl_usd"] == 10.0
    assert trade["total_cost_usd"] == 1.515
    assert trade["net_pnl_usd"] == 8.485
    assert result.state_changes[-1]["cumulative_realized_net_pnl_usd"] == 8.485
    assert result.state_changes[0]["event_type"] == "run_started"
    assert result.state_changes[0]["cash_balance_usd"] == 20_000.0
    stock_fill_state = next(row for row in result.state_changes if row["event_type"] == "stock_filled")
    assert stock_fill_state["cash_balance_usd"] == 20_000.0
    assert stock_fill_state["reserved_short_margin_usd"] == 1515.0
    assert stock_fill_state["available_cash_usd"] == 17_485.0
    assert result.state_changes[-1]["cash_balance_usd"] == 20_008.485
    assert result.state_changes[-1]["equity_balance_usd"] == 20_008.485
    assert [order["order_type"] for order in result.orders] == [
        "stock_sell_short",
        "rfq_buy_token",
        "itn_redeem",
    ]
    assert all(order["status"] in {"filled", "completed"} for order in result.orders)


def test_quote_cannot_be_used_twice():
    result = replay(
        _table(
            [
                _row(1_000_000_000, "one", 99.0, 100.0),
                _row(2_000_000_000, "two", 100.0, 100.0),
            ]
        ),
        _zero_latency_config(),
    )
    assert len(result.trades) == 1
    assert result.trades[0]["quote_row_id"] == "one"
    assert result.opportunities[1]["best_quote_row_id"] == "two"


def test_stock_fill_uses_bid_at_arrival_not_signal_bid():
    config = load_config(
        overrides={
            "latency_ms": {
                "strategy_compute": 100,
                "alpaca_submit": 0,
                "exchange_route": 0,
                "stock_fill_report": 0,
                "rfq_submit": 0,
                "fireblocks_policy": 0,
                "fireblocks_sign": 0,
                "tx_broadcast": 0,
                "chain_confirm": 0,
                "redeem_submit": 0,
                "redeem_chain_confirm": 0,
                "issuer_process": 0,
                "alpaca_journal": 0,
                "emergency_cover_submit": 0,
                "emergency_cover_route": 0,
            },
            "rfq": {"expiry_safety_buffer_ms": 0, "ttl_seconds": 0.15},
        }
    )
    result = replay(
        _table(
            [
                _row(1_000_000_000, "one", 99.0, 100.0),
                _row(1_050_000_000, "two", 100.0, 98.0),
                _row(1_200_000_000, "three", 100.0, 98.0),
            ]
        ),
        config,
    )
    assert len(result.trades) == 1
    assert result.trades[0]["status"] == "stock_rejected"
    assert result.trades[0]["failure_reason"] == "stock_limit_not_met"


def test_multiple_profitable_quotes_can_open_concurrently():
    config = _zero_latency_config()
    config = load_config(
        overrides={
            "latency_ms": {**config.latency_ms, "strategy_compute": 100},
            "rfq": {"expiry_safety_buffer_ms": 0},
        }
    )
    result = replay(
        _table(
            [
                _row(1_000_000_000, "one", 99.0, 100.0, bid_size=20),
                _row(1_010_000_000, "two", 99.0, 100.0, bid_size=20),
                _row(1_200_000_000, "three", 101.0, 100.0, bid_size=20),
            ]
        ),
        config,
    )
    assert len(result.trades) == 2
    assert {trade["quote_row_id"] for trade in result.trades} == {"one", "two"}
    assert all(trade["status"] == "completed" for trade in result.trades)
    assert result.state_changes[-1]["open_trade_count"] == 0
    assert result.state_changes[-1]["stock_position_qty"] == 0


def test_concurrent_orders_cannot_reuse_one_bid_size():
    config = _zero_latency_config()
    config = load_config(
        overrides={
            "latency_ms": {**config.latency_ms, "strategy_compute": 100},
            "rfq": {"expiry_safety_buffer_ms": 0, "ttl_seconds": 0.15},
        }
    )
    result = replay(
        _table(
            [
                _row(1_000_000_000, "one", 99.0, 100.0, bid_size=10),
                _row(1_010_000_000, "two", 99.0, 100.0, bid_size=10),
                _row(1_200_000_000, "three", 101.0, 100.0, bid_size=10),
            ]
        ),
        config,
    )
    assert sorted(trade["status"] for trade in result.trades) == ["completed", "stock_rejected"]
    rejected = next(trade for trade in result.trades if trade["status"] == "stock_rejected")
    assert rejected["failure_reason"] == "insufficient_bid_size"


def test_edge_must_strictly_exceed_total_cost():
    # At 100 USD stock price, 99.85 is exactly 15 bps below and must not trade.
    result = replay(
        _table([_row(1_000_000_000, "exactly_cost", 99.85, 100.0)]),
        _zero_latency_config(),
    )
    assert result.trades == []
    assert result.opportunities[0]["skip_reason"] == "edge_below_required_profit"


def test_stock_arrival_at_exact_cost_boundary_is_rejected():
    config = load_config(
        overrides={
            "latency_ms": {**_zero_latency_config().latency_ms, "strategy_compute": 100},
            "rfq": {"expiry_safety_buffer_ms": 0},
        }
    )
    limit = 99.0 / (1 - 15 / 10_000)
    result = replay(
        _table(
            [
                _row(1_000_000_000, "one", 99.0, 100.0),
                _row(1_100_000_000, "two", 101.0, limit),
            ]
        ),
        config,
    )
    assert result.trades[0]["status"] == "stock_rejected"
    assert result.trades[0]["failure_reason"] == "stock_limit_not_met"


def test_token_cost_and_short_margin_both_limit_concurrent_trades():
    config = load_config(
        overrides={
            "capital": {"initial_capital_usd": 3_000.0, "short_margin_ratio": 1.5},
            "latency_ms": {**_zero_latency_config().latency_ms, "strategy_compute": 100},
            "rfq": {"expiry_safety_buffer_ms": 0},
        }
    )
    result = replay(
        _table(
            [
                _row(1_000_000_000, "one", 99.0, 100.0),
                _row(1_010_000_000, "two", 99.0, 100.0),
                _row(1_020_000_000, "three", 101.0, 100.0),
            ]
        ),
        config,
    )
    assert len(result.trades) == 1
    assert result.opportunities[1]["skip_reason"] == "capital_insufficient"
    assert result.opportunities[1]["reserved_token_cost_usd"] == 990.0
    assert result.opportunities[1]["available_cash_usd"] == 510.0
