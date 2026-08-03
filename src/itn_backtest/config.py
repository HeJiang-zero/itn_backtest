"""Configuration loading and validation for the backtest."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


DEFAULTS: Dict[str, Any] = {
    "universe": {
        "underlying_symbol": "AAPL",
        "token_symbol": "AAPLx",
        "token_multiplier": 1.0,
        "token_qty_per_trade": 10.0,
    },
    "data": {
        "rfq_source_mode": "raw_response",
        "max_token_price_age_s": None,
        "max_stock_quote_age_s": 0.5,
        "require_http_status": 200,
    },
    "runtime": {"engine_mode": "fast"},
    "capital": {
        "initial_capital_usd": 20_000.0,
        "short_margin_ratio": 1.5,
    },
    "output": {
        "save_opportunity_series": True,
        "save_state_series": True,
        "save_debug_trace": False,
        "generate_charts": True,
    },
    "rfq": {
        "ttl_seconds": 30.0,
        "available_from": "response_receive_time",
        "expiry_gate": "confirmation",
        "expiry_safety_buffer_ms": 500,
        "one_time_use": True,
    },
    "strategy": {
        # A trade must exceed the total cost plus this additional net-profit target.
        "minimum_net_profit_bps": 0.0,
        # null means no artificial count cap; capital and BIDSIZE remain binding.
        "max_open_trades": None,
        "reserve_quote_before_short": True,
    },
    "stock_execution": {
        "fill_policy": "top_of_book_fok",
        "use_protective_sell_limit": True,
        "require_bid_size": True,
        "short_slippage_bps": 0.0,
        "cover_slippage_bps": 2.0,
    },
    "costs": {"total_cost_deduction_bps": 15.0},
    "latency_ms": {
        "strategy_compute": 10,
        "alpaca_submit": 20,
        "exchange_route": 30,
        "stock_fill_report": 50,
        "rfq_submit": 20,
        "fireblocks_policy": 0,
        "fireblocks_sign": 500,
        "tx_broadcast": 100,
        "chain_confirm": 1000,
        "redeem_submit": 100,
        "redeem_chain_confirm": 1000,
        "issuer_process": 1000,
        "alpaca_journal": 1000,
        "emergency_cover_submit": 50,
        "emergency_cover_route": 50,
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass(frozen=True)
class BacktestConfig:
    """Validated configuration with convenience methods for timeline calculations."""

    raw: Dict[str, Any]

    @property
    def universe(self) -> Dict[str, Any]:
        return self.raw["universe"]

    @property
    def data(self) -> Dict[str, Any]:
        return self.raw["data"]

    @property
    def output(self) -> Dict[str, Any]:
        return self.raw["output"]

    @property
    def capital(self) -> Dict[str, Any]:
        return self.raw["capital"]

    @property
    def rfq(self) -> Dict[str, Any]:
        return self.raw["rfq"]

    @property
    def strategy(self) -> Dict[str, Any]:
        return self.raw["strategy"]

    @property
    def stock_execution(self) -> Dict[str, Any]:
        return self.raw["stock_execution"]

    @property
    def costs(self) -> Dict[str, Any]:
        return self.raw["costs"]

    @property
    def latency_ms(self) -> Dict[str, Any]:
        return self.raw["latency_ms"]

    @property
    def config_hash(self) -> str:
        encoded = json.dumps(self.raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def token_qty(self) -> float:
        return float(self.universe["token_qty_per_trade"])

    @property
    def stock_qty(self) -> float:
        return self.token_qty * float(self.universe["token_multiplier"])

    @property
    def quote_ttl_ns(self) -> int:
        return int(float(self.rfq["ttl_seconds"]) * 1_000_000_000)

    @property
    def expiry_buffer_ns(self) -> int:
        return int(self.rfq["expiry_safety_buffer_ms"]) * 1_000_000

    @property
    def stock_arrival_delay_ns(self) -> int:
        return int(
            (self.latency_ms["strategy_compute"]
             + self.latency_ms["alpaca_submit"]
             + self.latency_ms["exchange_route"])
            * 1_000_000
        )

    @property
    def stock_report_delay_ns(self) -> int:
        return int(self.latency_ms["stock_fill_report"] * 1_000_000)

    @property
    def rfq_execution_delay_ns(self) -> int:
        keys = ["rfq_submit", "fireblocks_policy", "fireblocks_sign", "tx_broadcast"]
        if self.rfq["expiry_gate"] == "confirmation":
            keys.append("chain_confirm")
        return int(sum(self.latency_ms[key] for key in keys) * 1_000_000)

    @property
    def token_received_delay_ns(self) -> int:
        return int(
            (self.latency_ms["rfq_submit"]
             + self.latency_ms["fireblocks_policy"]
             + self.latency_ms["fireblocks_sign"]
             + self.latency_ms["tx_broadcast"]
             + self.latency_ms["chain_confirm"])
            * 1_000_000
        )

    @property
    def redeem_submit_delay_ns(self) -> int:
        return int(self.latency_ms["redeem_submit"] * 1_000_000)

    @property
    def redeem_complete_delay_ns(self) -> int:
        keys = ["redeem_submit", "redeem_chain_confirm", "issuer_process", "alpaca_journal"]
        return int(sum(self.latency_ms[key] for key in keys) * 1_000_000)

    @property
    def emergency_cover_delay_ns(self) -> int:
        return int(
            (self.latency_ms["emergency_cover_submit"]
             + self.latency_ms["emergency_cover_route"])
            * 1_000_000
        )

    @property
    def required_gross_edge_bps(self) -> float:
        """Gross edge needed to cover the unified cost and profit target."""

        return float(self.costs["total_cost_deduction_bps"]) + float(
            self.strategy["minimum_net_profit_bps"]
        )

    def resolved_yaml(self) -> str:
        return yaml.safe_dump(self.raw, allow_unicode=True, sort_keys=False)


def _validate(config: Dict[str, Any]) -> None:
    if config["data"]["rfq_source_mode"] not in {"raw_response", "baseline_1hz"}:
        raise ValueError("data.rfq_source_mode must be raw_response or baseline_1hz")
    if config["rfq"]["expiry_gate"] not in {"broadcast", "confirmation"}:
        raise ValueError("rfq.expiry_gate must be broadcast or confirmation")
    if float(config["universe"]["token_multiplier"]) <= 0:
        raise ValueError("universe.token_multiplier must be positive")
    if float(config["universe"]["token_qty_per_trade"]) <= 0:
        raise ValueError("universe.token_qty_per_trade must be positive")
    if float(config["rfq"]["ttl_seconds"]) <= 0:
        raise ValueError("rfq.ttl_seconds must be positive")
    max_open = config["strategy"]["max_open_trades"]
    if max_open is not None and int(max_open) <= 0:
        raise ValueError("strategy.max_open_trades must be null or a positive integer")
    if float(config["strategy"]["minimum_net_profit_bps"]) < 0:
        raise ValueError("strategy.minimum_net_profit_bps must be non-negative")
    if float(config["costs"]["total_cost_deduction_bps"]) < 0:
        raise ValueError("costs.total_cost_deduction_bps must be non-negative")
    if float(config["capital"]["initial_capital_usd"]) < 0:
        raise ValueError("capital.initial_capital_usd must be non-negative")
    if float(config["capital"]["short_margin_ratio"]) < 1:
        raise ValueError("capital.short_margin_ratio must be at least 1")
    for name, value in config["latency_ms"].items():
        if float(value) < 0:
            raise ValueError("latency_ms.%s must be non-negative" % name)


def load_config(path: Optional[Path] = None, overrides: Optional[Dict[str, Any]] = None) -> BacktestConfig:
    """Load YAML configuration, merge defaults, validate, and return a frozen config."""

    loaded: Dict[str, Any] = {}
    if path is not None:
        with Path(path).open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
    merged = _deep_merge(DEFAULTS, loaded)
    if overrides:
        merged = _deep_merge(merged, overrides)
    _validate(merged)
    return BacktestConfig(raw=merged)
