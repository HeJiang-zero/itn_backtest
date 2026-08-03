# ITN Redeem Backtest

这是根据 [回测设计](redeem_direction_backtest_design.md) 实现的快速近似回测框架：使用历史可执行 Buy RFQ、股票 L1 bid/size、固定延迟和固定 15bps 总成本，回放 Token 折价后 redeem 的套利路径。

## 运行

首次安装开发依赖：

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -e '.[dev]'
```

```bash
.venv/bin/itn-backtest prepare
.venv/bin/itn-backtest run
```

或一次完成：

```bash
.venv/bin/itn-backtest all
```

快速参数扫描会复用 Parquet 缓存，默认只保存交易表和汇总（避免重复写大体积机会序列）：

```bash
.venv/bin/itn-backtest sweep --field strategy.minimum_net_profit_bps --values 0,5,10
```

为某个 sweep 同时保存曲线数据时加 `--save-series`。

可修改的参数在 [configs/redeem_backtest.yaml](configs/redeem_backtest.yaml)，中文字段说明在 [参数手册](redeem_backtest_parameters.md)。

普通回测输出位于 `runs/backtests/<run_id>/`；参数扫描输出位于 `runs/parameter_sweeps/<run_id>/`。主要文件为 `trade_details.parquet`、`order_details.parquet`、`opportunity_series.parquet`、`portfolio_state_series.parquet`、`pnl_inventory_balance.png`、`summary.json`、`resolved_config.yaml` 与 `run_metadata.json`。`run_metadata.json` 的 `run_kind` 用于区分普通回测和参数扫描；开发验证应使用临时目录或 `runs/validation/`。
# itn_backtest
