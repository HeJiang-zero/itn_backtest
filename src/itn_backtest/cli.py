"""Command-line interface for data preparation and replay."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import yaml

from .config import load_config
from .engine import replay
from .prepare_data import load_curated, load_manifest, manifest_hash, prepare_data
from .report import write_run


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fast ITN redeem-arbitrage backtest")
    parser.add_argument("command", choices=["prepare", "run", "all", "sweep"])
    parser.add_argument("--config", type=Path, default=Path("configs/redeem_backtest.yaml"))
    parser.add_argument("--input", type=Path, default=Path("data"), help="Raw CSV directory")
    parser.add_argument("--curated", type=Path, default=Path("data/curated"), help="Parquet cache directory")
    parser.add_argument(
        "--runs",
        type=Path,
        default=None,
        help="Override output root (defaults: runs/backtests or runs/parameter_sweeps)",
    )
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--field", type=str, default=None, help="Dotted config field for sweep, e.g. strategy.minimum_net_profit_bps")
    parser.add_argument("--values", type=str, default=None, help="Comma-separated YAML values for sweep, e.g. 15,20,25")
    parser.add_argument("--save-series", action="store_true", help="For sweep, also save opportunity and state series")
    return parser


def _nested_override(field: str, value: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    current = result
    parts = field.split(".")
    if not all(parts):
        raise ValueError("--field must be a dotted path")
    for part in parts[:-1]:
        current[part] = {}
        current = current[part]
    current[parts[-1]] = value
    return result


def _check_manifest(manifest: Dict[str, Any], config) -> None:
    if manifest["rfq_source_mode"] != config.data["rfq_source_mode"]:
        raise ValueError(
            "Curated data was prepared with rfq_source_mode=%s, but config requests %s. "
            "Run `itn-backtest prepare` first."
            % (manifest["rfq_source_mode"], config.data["rfq_source_mode"])
        )
    if manifest["underlying_symbol"] != config.universe["underlying_symbol"]:
        raise ValueError(
            "Curated data was prepared for %s, but config requests %s. Run `itn-backtest prepare` first."
            % (manifest["underlying_symbol"], config.universe["underlying_symbol"])
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    config = load_config(args.config)
    if args.runs is not None:
        runs_dir = args.runs
    elif args.command == "sweep":
        runs_dir = Path("runs/parameter_sweeps")
    else:
        runs_dir = Path("runs/backtests")
    if args.command in {"prepare", "all"}:
        manifest = prepare_data(args.input, args.curated, config)
        print("Prepared %d rows in %s" % (manifest["rows"], args.curated))
    if args.command in {"run", "all", "sweep"}:
        manifest = load_manifest(args.curated)
        _check_manifest(manifest, config)
        table = load_curated(args.curated)
        if args.command == "sweep":
            if not args.field or not args.values:
                raise ValueError("sweep requires both --field and --values")
            for ordinal, raw_value in enumerate(args.values.split(","), start=1):
                value = yaml.safe_load(raw_value)
                overrides = _nested_override(args.field, value)
                if not args.save_series:
                    overrides.setdefault("output", {})["save_opportunity_series"] = False
                    overrides.setdefault("output", {})["save_state_series"] = False
                sweep_config = load_config(args.config, overrides=overrides)
                _check_manifest(manifest, sweep_config)
                result = replay(table, sweep_config)
                prefix = args.run_id or "sweep"
                run_id = "%s_%s_%02d" % (prefix, args.field.replace(".", "-"), ordinal)
                run_path = write_run(
                    result,
                    sweep_config,
                    runs_dir,
                    manifest_hash(args.curated),
                    run_id,
                    manifest,
                    run_kind="parameter_sweep",
                )
                print("Sweep %s=%r: %s (completed=%s, net=%.6f)" % (
                    args.field, value, run_path, result.summary["trades_completed"], result.summary["net_pnl_usd"]
                ))
        else:
            result = replay(table, config)
            run_path = write_run(
                result,
                config,
                runs_dir,
                manifest_hash(args.curated),
                args.run_id,
                manifest,
                run_kind="backtest",
            )
            print("Run complete: %s" % run_path)
            print("Completed trades: %s; net PnL: %.6f" % (result.summary["trades_completed"], result.summary["net_pnl_usd"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
