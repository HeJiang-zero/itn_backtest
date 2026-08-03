from pathlib import Path

import pyarrow as pa

from itn_backtest.config import load_config
from itn_backtest.engine import replay
from itn_backtest.report import write_run


def test_run_writes_orders_and_performance_chart(tmp_path: Path):
    table = pa.Table.from_pylist(
        [
            {
                "source_row_id": "one",
                "request_ts_ns": 1_000_000_000,
                "received_ts_ns": 1_000_000_000,
                "rtt_ms": 1.0,
                "symbol": "AAPL",
                "token_symbol": "AAPLx",
                "rfq_price_usd": 100.0,
                "bid": 101.0,
                "ask": 101.01,
                "bid_size": 100.0,
                "ask_size": 100.0,
                "stock_quote_age_s": 0.0,
                "stock_quote_stale": False,
                "secs_since_price_change": 0.0,
            }
        ]
    )
    config = load_config(
        overrides={
            "latency_ms": {name: 0 for name in load_config().latency_ms},
            "rfq": {"expiry_safety_buffer_ms": 0},
        }
    )
    result = replay(table, config)
    run_path = write_run(result, config, tmp_path, "manifest", "test-run")
    assert (run_path / "order_details.parquet").exists()
    assert (run_path / "pnl_inventory_balance.png").exists()
