"""One-time CSV normalization into compact Parquet files."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .config import BacktestConfig
from .artifact_names import INPUT_DATA_MANIFEST


CURATED_SCHEMA = pa.schema(
    [
        ("source_row_id", pa.string()),
        ("request_ts_ns", pa.int64()),
        ("received_ts_ns", pa.int64()),
        ("rtt_ms", pa.float64()),
        ("symbol", pa.string()),
        ("token_symbol", pa.string()),
        ("rfq_price_usd", pa.float64()),
        ("bid", pa.float64()),
        ("ask", pa.float64()),
        ("bid_size", pa.float64()),
        ("ask_size", pa.float64()),
        ("stock_quote_age_s", pa.float64()),
        ("stock_quote_stale", pa.bool_()),
        ("secs_since_price_change", pa.float64()),
    ]
)


def _timestamp_ns(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    utc = parsed.astimezone(timezone.utc)
    seconds = int(utc.timestamp())
    return seconds * 1_000_000_000 + utc.microsecond * 1_000


def _float(value: Any) -> float:
    if value is None or str(value).strip() == "":
        return float("nan")
    return float(value)


def _bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_source(path: Path, config: BacktestConfig) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    total_rows = 0
    accepted_rows = 0
    rejected_status = 0
    rejected_symbol = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for line_number, raw in enumerate(reader, start=2):
            total_rows += 1
            if raw.get("HTTP Status") != str(config.data["require_http_status"]):
                rejected_status += 1
                continue
            if raw.get("Symbol") != config.universe["underlying_symbol"]:
                rejected_symbol += 1
                continue
            try:
                request_ts_ns = _timestamp_ns(raw["Req Sent (UTC)"])
                received_ts_ns = _timestamp_ns(raw["Resp Recv (UTC)"])
                rfq_price = _float(raw["xStocks Price (USD)"])
                bid = _float(raw["Bid"])
                ask = _float(raw["Ask"])
            except (KeyError, ValueError):
                continue
            if not (rfq_price == rfq_price and bid == bid and ask == ask):
                continue
            rows.append(
                {
                    "source_row_id": "%s:%d" % (path.name, line_number),
                    "request_ts_ns": request_ts_ns,
                    "received_ts_ns": received_ts_ns,
                    "rtt_ms": _float(raw.get("RTT (ms)")),
                    "symbol": raw["Symbol"],
                    "token_symbol": raw.get("xStock Symbol", ""),
                    "rfq_price_usd": rfq_price,
                    "bid": bid,
                    "ask": ask,
                    "bid_size": _float(raw.get("BIDSIZE")),
                    "ask_size": _float(raw.get("ASKSIZE")),
                    "stock_quote_age_s": _float(raw.get("Quote Age (s)")),
                    "stock_quote_stale": _bool(raw.get("Quote Stale")),
                    "secs_since_price_change": _float(raw.get("Secs Since Price Change")),
                }
            )
            accepted_rows += 1
    rows.sort(key=lambda item: item["received_ts_ns"])
    info = {
        "file": path.name,
        "sha256": _sha256(path),
        "total_rows": total_rows,
        "accepted_rows": accepted_rows,
        "rejected_http_status": rejected_status,
        "rejected_symbol": rejected_symbol,
        "first_received_ts_ns": rows[0]["received_ts_ns"] if rows else None,
        "last_received_ts_ns": rows[-1]["received_ts_ns"] if rows else None,
    }
    return rows, info


def _resample_last_per_second(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sampled: List[Dict[str, Any]] = []
    current_second = None
    latest = None
    for row in rows:
        second = row["received_ts_ns"] // 1_000_000_000
        if current_second is not None and second != current_second and latest is not None:
            sampled.append(latest)
        current_second = second
        latest = row
    if latest is not None:
        sampled.append(latest)
    return sampled


def prepare_data(input_dir: Path, curated_dir: Path, config: BacktestConfig) -> Dict[str, Any]:
    """Normalize raw logs and write one Parquet file per source day.

    The source CSVs remain untouched. Existing curated files are replaced only for
    the same source filename, making preparation idempotent for a given input.
    """

    input_dir = Path(input_dir)
    curated_dir = Path(curated_dir)
    curated_dir.mkdir(parents=True, exist_ok=True)
    sources = sorted(input_dir.glob("xstocks_log_*.csv"))
    if not sources:
        raise FileNotFoundError("No xstocks_log_*.csv files found in %s" % input_dir)

    source_infos: List[Dict[str, Any]] = []
    total_rows = 0
    for source in sources:
        rows, info = _read_source(source, config)
        if config.data["rfq_source_mode"] == "baseline_1hz":
            rows = _resample_last_per_second(rows)
            info["accepted_rows_after_sampling"] = len(rows)
        table = pa.Table.from_pylist(rows, schema=CURATED_SCHEMA)
        target = curated_dir / (source.stem + ".parquet")
        pq.write_table(table, target, compression="zstd")
        info["parquet_file"] = target.name
        source_infos.append(info)
        total_rows += len(rows)

    manifest = {
        "schema_version": 1,
        "underlying_symbol": config.universe["underlying_symbol"],
        "rfq_source_mode": config.data["rfq_source_mode"],
        "rows": total_rows,
        "sources": source_infos,
    }
    manifest_path = curated_dir / INPUT_DATA_MANIFEST
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def load_curated(curated_dir: Path) -> pa.Table:
    """Load and time-sort all normalized source files into one Arrow table."""

    files = sorted(Path(curated_dir).glob("xstocks_log_*.parquet"))
    if not files:
        raise FileNotFoundError("No curated Parquet files found in %s" % curated_dir)
    tables = [pq.ParquetFile(path).read() for path in files]
    table = pa.concat_tables(tables)
    order = pc.sort_indices(table, sort_keys=[("received_ts_ns", "ascending")])
    return pc.take(table, order)


def manifest_hash(curated_dir: Path) -> str:
    path = Path(curated_dir) / INPUT_DATA_MANIFEST
    if not path.exists():
        raise FileNotFoundError("Missing data manifest: %s" % path)
    return _sha256(path)


def load_manifest(curated_dir: Path) -> Dict[str, Any]:
    path = Path(curated_dir) / INPUT_DATA_MANIFEST
    if not path.exists():
        raise FileNotFoundError("Missing data manifest: %s" % path)
    return json.loads(path.read_text(encoding="utf-8"))
