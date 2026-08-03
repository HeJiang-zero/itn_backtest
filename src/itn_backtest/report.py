"""Persist replay artifacts in a compact, reproducible run directory."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pyarrow as pa
import pyarrow.parquet as pq

from .config import BacktestConfig
from .charts import write_performance_chart
from .engine import ReplayResult
from .artifact_names import (
    DEBUG_TRACE,
    INPUT_DATA_MANIFEST,
    OPPORTUNITY_SERIES,
    ORDER_DETAILS,
    PERFORMANCE_CHART,
    PORTFOLIO_STATE_SERIES,
    RESOLVED_CONFIG,
    RUN_METADATA,
    SUMMARY,
    TRADE_DETAILS,
)


def _empty_table(columns: Iterable[str]) -> pa.Table:
    return pa.table({name: pa.array([], type=pa.string()) for name in columns})


def _write_rows(path: Path, rows: List[Dict[str, Any]], empty_columns: Iterable[str]) -> None:
    table = pa.Table.from_pylist(rows) if rows else _empty_table(empty_columns)
    pq.write_table(table, path, compression="zstd")


def write_run(
    result: ReplayResult,
    config: BacktestConfig,
    runs_dir: Path,
    data_manifest_hash: str,
    run_id: Optional[str] = None,
    data_manifest: Optional[Dict[str, Any]] = None,
    run_kind: str = "backtest",
) -> Path:
    """Write all configured output artifacts and return the run directory."""

    if run_id is None:
        run_id = "backtest_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ") + "_" + config.config_hash[:8]
    target = Path(runs_dir) / run_id
    target.mkdir(parents=True, exist_ok=False)

    (target / RESOLVED_CONFIG).write_text(config.resolved_yaml(), encoding="utf-8")
    run_metadata = {
        "run_id": run_id,
        "schema_version": 1,
        "run_kind": run_kind,
        "config_hash": config.config_hash,
        "data_manifest_hash": data_manifest_hash,
        "inventory_model": "simplified_redeem_success",
    }
    (target / RUN_METADATA).write_text(json.dumps(run_metadata, indent=2, sort_keys=True), encoding="utf-8")
    manifest_output = dict(data_manifest or {})
    manifest_output["sha256"] = data_manifest_hash
    (target / INPUT_DATA_MANIFEST).write_text(json.dumps(manifest_output, indent=2, sort_keys=True), encoding="utf-8")

    trades = [dict(row, **run_metadata) for row in result.trades]
    _write_rows(
        target / TRADE_DETAILS,
        trades,
        ["run_id", "schema_version", "config_hash", "data_manifest_hash", "trade_id", "status"],
    )
    orders = [dict(row, **run_metadata) for row in result.orders]
    _write_rows(
        target / ORDER_DETAILS,
        orders,
        ["run_id", "schema_version", "config_hash", "data_manifest_hash", "order_id", "trade_id", "status"],
    )
    if config.output["save_opportunity_series"]:
        opportunities = [dict(row, **run_metadata) for row in result.opportunities]
        _write_rows(
            target / OPPORTUNITY_SERIES,
            opportunities,
            ["run_id", "schema_version", "config_hash", "data_manifest_hash", "decision_ts_ns", "skip_reason"],
        )
    if config.output["save_state_series"]:
        states = [dict(row, **run_metadata) for row in result.state_changes]
        _write_rows(
            target / PORTFOLIO_STATE_SERIES,
            states,
            ["run_id", "schema_version", "config_hash", "data_manifest_hash", "state_ts_ns", "event_type"],
        )
        if config.output["generate_charts"]:
            write_performance_chart(states, target / PERFORMANCE_CHART)
    if config.output["save_debug_trace"]:
        trace = [dict(row, **run_metadata) for row in result.debug_trace]
        _write_rows(
            target / DEBUG_TRACE,
            trace,
            ["run_id", "schema_version", "config_hash", "data_manifest_hash", "timestamp_ns", "event_type"],
        )

    summary = dict(result.summary)
    summary.update(run_metadata)
    (target / SUMMARY).write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return target
