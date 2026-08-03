# Redeem 回测参数手册（唯一配置入口）

## 使用规则

这是 Token 折价 / redeem 方向回测的**唯一参数配置说明入口**。实际运行时只修改 [configs/redeem_backtest.yaml](configs/redeem_backtest.yaml) 这一份 YAML；参数含义以本页中文说明为准，策略代码、Notebook 和其他 Markdown 均不得另行写死参数值。

参数名在代码中使用英文 `snake_case`，便于 YAML/Python 读取；每个参数都在本页有中文名称、单位、默认值、作用和修改建议。所有时间均为毫秒（`ms`）或秒（`s`），数据时间戳均为 UTC。

当前版本只做 **Token 折价**：每条原始响应中的 `xStocks Price (USD)` 都是可执行的、全额的 Token Buy RFQ。每次决策会从低价到高价检查所有 30 秒内有效且未被占用的 RFQ；每条报价只要扣除统一成本后仍为正利润、且共享可用资金足够，就独立尝试套利。Token 与股票固定 1:1；默认每笔买 10 Token 并卖空 10 股，但可并发多笔。

---

## 可编辑配置

```yaml
# ===== 1. 标的、数量与运行模式 =====
universe:
  underlying_symbol: "AAPL"       # 标的股票代码（中文：标的股票）
  token_symbol: "AAPLx"           # 数据中的 Token 代码（中文：Token 代码）
  token_multiplier: 1.0            # 1 Token 对应的股票数量（中文：兑换比例）
  token_qty_per_trade: 10.0        # 每笔买入 Token 数量（中文：单笔 Token 数量）

data:
  rfq_source_mode: "raw_response" # baseline_1hz | raw_response（中文：RFQ 采样模式）
  max_token_price_age_s: null      # null=不因价格未变化而过滤（中文：Token 价格新鲜度上限）
  max_stock_quote_age_s: 0.5       # 股票行情允许的最大年龄（中文：股票行情新鲜度上限）
  require_http_status: 200         # 只接受此 HTTP 状态（中文：可用 HTTP 状态）

runtime:
  engine_mode: "fast"             # 固定使用快速线性扫描（中文：回测引擎模式）

capital:
  initial_capital_usd: 20000.0     # 回测初始现金本金（中文：初始本金）
  short_margin_ratio: 1.5          # 空头保证金比例（中文：空头保证金比例）

output:
  save_opportunity_series: true    # 保存每个可评估时刻的 edge（中文：机会序列开关）
  save_state_series: true          # 保存仓位/现金状态变化（中文：状态序列开关）
  save_debug_trace: false          # 保存逐事件排错轨迹，文件较大（中文：详细调试输出）
  generate_charts: true            # 生成收益、库存、余额组合图（中文：生成图表）

# ===== 2. RFQ 生命周期 =====
rfq:
  ttl_seconds: 30.0                # 从 Resp Recv 起算的锁价有效期（中文：RFQ 锁价时长）
  available_from: "response_receive_time" # 固定使用收到响应的时刻（中文：RFQ 可用起点）
  expiry_gate: "confirmation"     # broadcast | confirmation（中文：RFQ 到期判定点）
  expiry_safety_buffer_ms: 500     # 到期前额外保留的安全时间（中文：RFQ 到期安全缓冲）
  one_time_use: true               # 一条 RFQ 仅能被一笔交易使用（中文：RFQ 一次性使用）

# ===== 3. 策略与股票成交 =====
strategy:
  minimum_net_profit_bps: 0.0      # 扣除总成本后额外要求的最低利润（中文：最低净利润目标）
  max_open_trades: null             # null=不设人为上限（中文：最大并发交易数）
  reserve_quote_before_short: true  # 卖空前先占用该 RFQ（中文：卖空前锁定 RFQ）

stock_execution:
  fill_policy: "top_of_book_fok"  # 首版固定：L1 顶档全额成交或失败（中文：股票成交模型）
  use_protective_sell_limit: true  # FOK/IOC 最低卖价保护（中文：卖空保护限价）
  require_bid_size: true           # BIDSIZE 必须不小于股票数量（中文：校验买一挂单量）
  short_slippage_bps: 0.0          # 卖空成交价从 bid 向下调整（中文：卖空滑点）
  cover_slippage_bps: 2.0          # 失败回补价在 ask 基础上向上调整（中文：回补滑点）

# ===== 4. 唯一的成本扣减参数 =====
costs:
  total_cost_deduction_bps: 15.0   # 平仓时一次性扣除的总成本（中文：总成本扣减）

# ===== 5. 各阶段延迟（均为 ms） =====
latency_ms:
  strategy_compute: 10             # 策略从收到行情到决定下单（中文：策略计算延迟）
  alpaca_submit: 20                # 向 Alpaca API 提交订单（中文：股票订单提交延迟）
  exchange_route: 30               # Alpaca 至交易场所路由（中文：股票订单路由延迟）
  stock_fill_report: 50            # 获得股票成交回报（中文：股票成交回报延迟）
  rfq_submit: 20                   # 提交已锁 RFQ 的执行请求（中文：RFQ 执行提交延迟）
  fireblocks_policy: 0             # Fireblocks policy/审批等待（中文：Fireblocks 策略审批延迟）
  fireblocks_sign: 500             # Fireblocks 签名（中文：Fireblocks 签名延迟）
  tx_broadcast: 100                # 已签名交易广播至链（中文：链上交易广播延迟）
  chain_confirm: 1000              # Buy RFQ 链上确认并收到 Token（中文：Token 买入链上确认延迟）
  redeem_submit: 100               # 发起 redeem（中文：Redeem 提交延迟）
  redeem_chain_confirm: 1000       # redeem 链上确认（中文：Redeem 链上确认延迟）
  issuer_process: 1000             # 发行方处理并通知 Alpaca（中文：发行方处理延迟）
  alpaca_journal: 1000             # Alpaca 股票 journal 到账（中文：股票到账延迟）
  emergency_cover_submit: 50       # RFQ 失败后提交回补单（中文：紧急回补提交延迟）
  emergency_cover_route: 50        # 紧急回补单到市场（中文：紧急回补路由延迟）
```

---

## 参数中文索引与修改说明

### 1. 标的、数量与数据

| 代码参数 | 中文名称 | 单位 | 默认值 | 作用与修改规则 |
|---|---|---:|---:|---|
| `underlying_symbol` | 标的股票 | 代码 | `AAPL` | 只回放此股票的行。更换标的前必须确认数据和 Token 映射。 |
| `token_symbol` | Token 代码 | 代码 | `AAPLx` | 当前是 CSV 中的名称；应以正式 ITN 可交易资产名替换。 |
| `token_multiplier` | 兑换比例 | 股票/Token | `1.0` | 已确认恒定 1:1，故每笔股票数量 `Q = token_qty_per_trade`。 |
| `token_qty_per_trade` | 单笔 Token 数量 | Token | `10` | 已确认每笔固定买 10 Token，同时卖空 10 股。 |
| `rfq_source_mode` | RFQ 采样模式 | 枚举 | `raw_response` | 已确认每条原始响应都是可执行 RFQ，生产式历史回放应使用 `raw_response`。`baseline_1hz` 只保留作“如果以后改为每秒询价一次”的敏感性模式。 |
| `max_token_price_age_s` | Token 价格新鲜度上限 | s / `null` | `null` | 已确认每条响应本身都是新的可执行 RFQ，故默认不因 `Secs Since Price Change` 过滤。仅在后来确认该字段会使 RFQ 无效时才设秒数上限。 |
| `max_stock_quote_age_s` | 股票行情新鲜度上限 | s | `0.5` | 使用 CSV `Quote Age (s)` 过滤。行情过老时不触发/不成交。 |
| `require_http_status` | 可用 HTTP 状态 | 状态码 | `200` | 非此状态的记录只用于观察空洞，不产生 RFQ 或股票快照。 |
| `engine_mode` | 回测引擎模式 | 枚举 | `fast` | 当前只实现快速线性扫描，不为每条行情生成 Python Event 对象。 |
| `initial_capital_usd` | 初始本金 | USD | `20,000` | 共享简化现金池的起始余额。只有 `现金余额 − Token 成本冻结 − 空头保证金冻结` 足够才可再开新单。 |
| `short_margin_ratio` | 空头保证金比例 | 倍数 | `1.5` | 每笔空头冻结 `实际卖空名义金额 × 此比例`。开仓信号时按 signal bid 预留，到场成交后按实际成交额校准；直到 redeem 股票到账平仓或应急回补后才释放。卖空所得在空头存续期间不计入可用余额。 |
| `save_opportunity_series` | 机会序列开关 | 布尔 | `true` | 保存每个可评估时刻的最佳 RFQ、edge、触发判断和 QuoteBook 状态；用于 edge 曲线和机会统计。约 36 万行，使用 Parquet，适合默认保留。 |
| `save_state_series` | 状态序列开关 | 布尔 | `true` | 仅在股票成交、Token 到账、redeem 提交/完成等状态变化时写行；用于 PnL 和库存阶梯曲线，文件很小。 |
| `save_debug_trace` | 详细调试输出 | 布尔 | `false` | 排查特定交易时才开启；不建议在大规模参数 sweep 时保存。 |
| `generate_charts` | 生成图表 | 布尔 | `true` | 每次普通 run 生成一张 PNG：上方收益曲线，中间库存曲线，下方现金/权益余额曲线。参数 sweep 默认关闭状态序列时不会生成图。 |

### 2. RFQ 生命周期

| 代码参数 | 中文名称 | 单位 | 默认值 | 作用与修改规则 |
|---|---|---:|---:|---|
| `ttl_seconds` | RFQ 锁价时长 | s | `30` | 已确认从 `Resp Recv` 起锁定 30 秒，故 `expires_at = Resp Recv + 30 秒`。 |
| `available_from` | RFQ 可用起点 | 枚举 | `response_receive_time` | 当前固定为响应收到时，避免使用尚未收到的价格。若真实协议从服务端签发时算 TTL，也只改变到期计算，不能把 quote 提前用于决策。 |
| `expiry_gate` | RFQ 到期判定点 | 枚举 | `confirmation` | `broadcast`：广播完成前有效即可；`confirmation`：链上确认前必须有效，保守且当前默认。必须按正式协议修改。 |
| `expiry_safety_buffer_ms` | RFQ 到期安全缓冲 | ms | `500` | 引擎要求关键时刻早于 `expires_at - buffer`。网络/区块确认不稳定时调大。 |
| `one_time_use` | RFQ 一次性使用 | 布尔 | `true` | 真实 RFQ 通常一次性全额执行。除非协议明确支持分拆/剩余数量，否则不得改为 `false`。 |

### 3. 策略与成交

| 代码参数 | 中文名称 | 单位 | 默认值 | 作用与修改规则 |
|---|---|---:|---:|---|
| `minimum_net_profit_bps` | 最低净利润目标 | bps | `0` | 触发条件为 `gross_edge_bps > total_cost_deduction_bps + minimum_net_profit_bps`。默认 0 即扣完成本后只要盈利就交易；若希望每笔至少净赚 5bps，改为 `5`。 |
| `max_open_trades` | 最大并发交易数 | 笔 / `null` | `null` | `null` 表示只受可用资金、每条 RFQ 一次性使用和同一快照 BIDSIZE 限制；也可填正整数做人为风控上限。 |
| `reserve_quote_before_short` | 卖空前锁定 RFQ | 布尔 | `true` | 先将该 quote 标为 reserved，并冻结 Token 成本和预计空头保证金，避免同一 RFQ 或同一笔本金被多个信号复用。应保持 `true`。 |
| `fill_policy` | 股票成交模型 | 枚举 | `top_of_book_fok` | 首版仅支持按到达时 L1 bid 全额成交或失败；不模拟排队。 |
| `use_protective_sell_limit` | 卖空保护限价 | 布尔 | `true` | 订单仍是一次性 FOK/IOC，不会挂着等待。最低卖价为 `P_min = (P_token/Q)/(1-required_gross_edge_bps/10000)`，其中 `required_gross_edge_bps = 总成本 + 最低净利润目标`；若到场 bid 低于它，则不成交并释放 RFQ。 |
| `require_bid_size` | 校验买一挂单量 | 布尔 | `true` | 已确认 BIDSIZE 是真实可成交股数；同一行情快照下的并发订单会依次扣减可用 BIDSIZE，剩余不足 `Q` 的订单失败。 |
| `short_slippage_bps` | 卖空滑点 | bps | `0` | 卖空价格 = bid × `(1 - bps/10000)`。用于保守测试。 |
| `cover_slippage_bps` | 回补滑点 | bps | `2` | RFQ 失败后的回补价格 = ask × `(1 + bps/10000)`。此项是价格模型，不属于最后一次性的成本扣减。 |

### 4. 成本与 PnL

| 代码参数 | 中文名称 | 单位 | 默认值 | 作用与修改规则 |
|---|---|---:|---:|---|
| `total_cost_deduction_bps` | 总成本扣减 | bps | `15` | 已确认当前统一按 15bps 扣减。每笔已经闭合交易在最终 PnL 一次性扣除；分母是该笔实际股票卖空名义金额 `stock_short_proceeds`。这是当前唯一的费用参数。 |

成功交易：

\[
gross\_pnl = stock\_short\_proceeds - token\_buy\_cost
\]

\[
total\_cost = stock\_short\_proceeds\times\frac{total\_cost\_deduction\_bps}{10,000}
\]

\[
net\_pnl = gross\_pnl - total\_cost
\]

RFQ 失败的紧急回补交易也以一次性成本表示：

\[
net\_pnl = stock\_short\_proceeds - stock\_cover\_cost - total\_cost
\]

这不是精确的费用归因，而是便于先快速研究的总摩擦假设。报告必须同时给出 `gross_pnl`、`total_cost`、`net_pnl`，不得把成本隐藏在 token 价格或每个延迟步骤中。

### 5. 延迟参数

所有 `latency_ms` 的参数单位均为 **毫秒**；它们相加形成真实的下一事件时间。每一段分开保留，便于之后用实测 p50/p95 替换。

| 代码参数 | 中文名称 | 默认值 | 从何时开始 | 到何时结束 / 决定什么 |
|---|---|---:|---|---|
| `strategy_compute` | 策略计算延迟 | 10ms | 收到行情/RFQ，确认信号后 | 发出卖空请求。 |
| `alpaca_submit` | 股票订单提交延迟 | 20ms | 策略发单 | Alpaca 接受请求。 |
| `exchange_route` | 股票订单路由延迟 | 30ms | Alpaca 接单 | 订单到达市场；此时取 as-of bid/size 并判定 FOK。 |
| `stock_fill_report` | 股票成交回报延迟 | 50ms | 股票在市场成交 | 策略知道成交，可开始执行 RFQ。 |
| `rfq_submit` | RFQ 执行提交延迟 | 20ms | 股票成交回报收到 | 发出 RFQ/合约调用请求。 |
| `fireblocks_policy` | Fireblocks 策略审批延迟 | 0ms | RFQ 执行请求发出 | 自动审批/策略检查完成；若有人工审批，不能设为短周期套利可用。 |
| `fireblocks_sign` | Fireblocks 签名延迟 | 500ms | 策略审批结束 | 已签名交易可广播。 |
| `tx_broadcast` | 链上交易广播延迟 | 100ms | 签名完成 | 交易送达链/RPC。若 `expiry_gate=broadcast`，这是 RFQ 到期检查时点。 |
| `chain_confirm` | Token 买入链上确认延迟 | 1000ms | 广播完成 | receipt 成功且 Token 可用；若 `expiry_gate=confirmation`，这是 RFQ 到期检查时点。 |
| `redeem_submit` | Redeem 提交延迟 | 100ms | Token 到账 | 赎回请求/转账已提交。 |
| `redeem_chain_confirm` | Redeem 链上确认延迟 | 1000ms | redeem 提交 | Token 销毁/赎回链上确认。 |
| `issuer_process` | 发行方处理延迟 | 1000ms | redeem 链上确认 | Ondo/发行方处理并通知 Alpaca。 |
| `alpaca_journal` | 股票到账延迟 | 1000ms | 发行方通知完成 | 股票进入 Alpaca 并抵消空头，交易成功闭合。 |
| `emergency_cover_submit` | 紧急回补提交延迟 | 50ms | RFQ 失败/过期被发现 | 发出 buy-to-cover 请求。 |
| `emergency_cover_route` | 紧急回补路由延迟 | 50ms | 回补请求发出 | 回补订单到市场；使用 as-of ask。 |

建议首次敏感性矩阵只改三组总延迟，其他值维持默认，以便解释结果：

```text
股票卖空到达市场：strategy_compute + alpaca_submit + exchange_route
RFQ 关键到期时间：rfq_submit + fireblocks_policy + fireblocks_sign + tx_broadcast [+ chain_confirm]
Token 到股票平仓时间：redeem_submit + redeem_chain_confirm + issuer_process + alpaca_journal
```

---

## 修改后的回测判定顺序

```text
1. 在每个事件时刻，从低价到高价检查所有尚未到期/未占用的 RFQ。
2. 用该时刻已收到的 bid 计算每条报价的 `gross_edge_bps` 和保护限价 `P_min`。
3. 仅当 `gross_edge_bps > total_cost_deduction_bps + minimum_net_profit_bps`，且可用余额足够冻结 Token 成本时，才 reserve 该 quote 并提交一次性 FOK/IOC 卖空；持续检查下一条，直到没有合格报价或资金不足。
4. 在股票订单实际到场时，用当时最新已收到的 bid、保护限价及同一快照剩余 BIDSIZE 判断是否全额成交；成交后才按各段 latency_ms 推进 RFQ 执行。
5. RFQ 成功后继续 redeem；股票到账时结算。
6. 最终一次性扣除 total_cost_deduction_bps，输出 gross_pnl、total_cost、net_pnl。
7. RFQ 失败/过期则按 ask 回补，同样只在交易最终闭合时扣一次总成本。
```

注意第 2 步：历史数据无法在 `t0` 就知道“未来延迟后”的 bid。严谨实现应在订单实际到达市场的事件时刻，使用当时最新已收到的股票快照，再决定是否成交；不能拿 `t0` 的 bid 直接假定成交。
