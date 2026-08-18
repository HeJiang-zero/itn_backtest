# Ondo + xStocks API Key 实时测试清单与 UAT-00 方案

## 1. 当前结论

基于当前已经拿到的：

- Ondo API Key
- xStocks API Key

现在已经可以开始：

- API 鉴权与权限检查
- 资产、网络、交易限制检查
- Ondo Soft RFQ 实时采样
- xStocks Soft RFQ 实时采样
- RFQ 延迟、TTL、报价曲线测试
- Ondo / xStocks 报价横向比较
- AAPL Underlying + Token RFQ 的 Live Shadow Arbitrage
- 如果已有对应 entitlement / Registered Wallet，可进一步测试 Formal / Hard RFQ

但是，仅凭这两个 API Key，还不能证明以下完整闭环：

```text
Token Buy
→ Token 到钱包
→ Redeem
→ Issuer 检测
→ Alpaca ITN
→ AAPL Journal
→ Alpaca Position = 0
```

这一部分还需要：

- Registered / Whitelisted Wallet
- Fireblocks 或其他可签名钱包
- Stablecoin / Gas
- xStocks xPort / ITN entitlement
- Issuer Redemption Wallet
- Alpaca Broker Sandbox / AP Account
- Backed / xStocks Client 与 Alpaca AP Account Mapping

---

# 2. 当前可以直接测试的项目

| 测试 | Ondo Key | xStocks Key | 当前状态 |
|---|---:|---:|---|
| API 鉴权 | ✅ | ✅ | 可以 |
| Client / Account 权限 | ✅ | ✅ | 可以 |
| 支持资产 | ✅ | ✅ | 可以 |
| 支持网络 | ✅ | ✅ | 可以 |
| Token metadata | ✅ | ✅ | 可以 |
| Market / Asset 状态 | ✅ | ✅ | 可以 |
| Trading Limits | ✅ | ✅ | 可以 |
| Min / Max Order Size | ✅ | ✅ | 可以 |
| Soft Buy RFQ | ✅ | ✅ | 可以 |
| Soft Sell RFQ | ✅ | ✅ | 可以 |
| RFQ Request Latency | ✅ | ✅ | 可以 |
| 不同数量 RFQ 曲线 | ✅ | ✅ | 可以 |
| Buy / Sell Spread | ✅ | ✅ | 可以 |
| RFQ TTL / Expiration | ✅ | ✅ | 可以测返回值 |
| Ondo short / long duration | ✅ | — | 可以 |
| Formal / Hard RFQ | 条件支持 | 条件支持 | 取决于 entitlement |
| Soft → Hard 转换 | — | 条件支持 | 需要 Registered Wallet |
| Live Shadow Arbitrage | ✅ | ✅ | 可以 |
| 真正链上 Token Buy | ⚠️ | ⚠️ | 需要钱包 / 资金 / 签名 |
| Token Redeem → 股票 | ❌ | ❌ | 需要 xPort / ITN |
| Alpaca Journal | ❌ | ❌ | 需要 Alpaca Mapping |
| 完整套利闭环 | ❌ | ❌ | 需要全链路 |

---

# 3. Ondo API Key 当前建议测试

## 3.1 API 权限和 Trading Limits

首先确认：

```text
AAPLon Buy 是否可用
AAPLon Sell 是否可用
最大 Token 数量
最大 Notional
剩余 Attestation 次数
市场是否开放
是否 paused / limited
```

建议记录：

```text
ondo_client_id
timestamp

symbol
side

trading_enabled
max_tokens
max_notional
remaining_attestations

market_status
limit_reason
```

这一步的目的不是看套利，而是确认：

> 当前 Ondo API Key 到底拥有哪一级交易权限。

---

## 3.2 Ondo Soft RFQ 实时采样

针对 AAPLon：

```text
Buy Soft RFQ
Sell Soft RFQ
```

建议测试数量：

```text
1
5
10
25
50
100
```

每次保存：

```text
request_at
response_at
latency_ms

symbol
side
qty

price
total_cost_or_proceeds

duration
chain
underlying
```

最终统计：

```text
RFQ latency p50
RFQ latency p95
RFQ latency p99

Buy price by size
Sell price by size

Buy/Sell spread bps
Size impact bps
```

---

# 4. Ondo short duration vs long duration

建议在相同时间、相同数量下同时测试：

```text
AAPLon
side = Buy
qty = 10

duration = short
duration = long
```

记录：

```text
short_price
long_price

short_expiration
long_expiration

short_ttl
long_ttl

long_short_price_difference_bps
```

最终需要回答：

```text
更长 TTL 带来的报价成本是多少？
```

套利策略应该根据实测：

```text
额外报价成本
vs
额外执行时间
```

选择 short / long，而不是固定写死。

---

# 5. Ondo Formal Attestation 测试

如果当前 API Client 已有正式 Attestation 权限，可以进一步测试。

第一阶段可以：

```text
申请正式 RFQ / Attestation
但先不上链执行
```

记录：

```text
attestation_id
request_at
response_at

formal_price
token_amount

expiration
ttl_ms

signature_available
asset_address
```

并且将前面的 Soft Quote 与 Formal Quote 做关联：

```text
soft_price
formal_price

soft_to_formal_latency_ms
soft_to_formal_price_change_bps
```

这个测试非常重要，因为它可以替换回测中的固定假设：

```text
RFQ TTL = 30 秒
```

真实系统应该使用：

```text
API 返回的 expiration
-
内部 safety buffer
```

---

# 6. xStocks API Key 当前建议测试

## 6.1 Asset Configuration

首先查询 AAPLx 当前资产配置。

重点获取：

```text
identifier = AAPLx

minOrderFiatValue
maxOrderFiatValue
executionTimeoutSeconds

isTradingHalted

network
tokenDeployment
```

正式测试不要长期写死：

```text
Token Qty = 10
RFQ TTL = 30s
```

而应该使用实时资产配置。

建议定期保存：

```text
timestamp
identifier

network
token_contract
decimals

min_order_value
max_order_value

execution_timeout_seconds
is_trading_halted
```

---

# 7. xStocks Soft RFQ 实时采样

测试：

```text
AAPLx Buy Soft RFQ
AAPLx Sell Soft RFQ
```

数量建议：

```text
1
5
10
25
50
100
```

每次记录：

```text
soft_quote_id

request_at
response_at
latency_ms

side
quantity
price
cash_amount

created_at
expires_at
ttl_ms

network
```

最终统计：

```text
RFQ latency p50 / p95 / p99

RFQ TTL
Buy/Sell spread

Size → Price 曲线

Soft Quote expiry rate
```

---

# 8. xStocks Soft → Hard RFQ 测试

如果已经具备：

```text
Registered Wallet
paymentWalletIdentifier
receivingWalletIdentifier
```

就建议马上测：

```text
T0         Soft Quote
T0 + 100ms Convert to Hard
T0 + 500ms Convert to Hard
T0 + 1s    Convert to Hard
T0 + 2s    Convert to Hard
...
```

记录：

```text
soft_quote_id
hard_quote_id

soft_price
hard_price

conversion_requested_at
conversion_completed_at

conversion_latency_ms

soft_expiration
hard_expiration

remaining_execution_window_ms

conversion_result
```

需要得到：

```text
Soft → Hard conversion success rate

expired rate

price preserved rate

remaining execution time p50
remaining execution time p95
```

这个指标直接影响套利执行顺序。

---

# 9. Ondo vs xStocks 实时横向比较

建议建立统一 Collector：

```text
                    AAPL
                     │
          ┌──────────┴──────────┐
          │                     │
      Ondo AAPLon          xStocks AAPLx
          │                     │
      Buy / Sell            Buy / Sell
```

每个采样周期同时抓：

```text
Ondo AAPLon Buy Soft
Ondo AAPLon Sell Soft

xStocks AAPLx Buy Soft
xStocks AAPLx Sell Soft

AAPL Bid
AAPL Ask
AAPL Bid Size
AAPL Ask Size
```

---

# 10. Live Shadow Arbitrage

这是当前最应该开始的测试。

不实际下单，只使用真实实时 RFQ + 股票实时行情。

## 10.1 Token 折价方向

逻辑：

```text
Token Buy 成本
<
Underlying 可卖空收入
```

计算：

```text
stock_short_notional
=
stock_bid × equivalent_stock_qty
```

```text
discount_gross_edge
=
stock_short_notional
-
token_buy_cost
```

```text
discount_gross_edge_bps
=
discount_gross_edge
/
stock_short_notional
× 10000
```

分别计算：

```text
Ondo Discount Edge
xStocks Discount Edge
```

---

# 11. Token 溢价方向

如果也想观察反方向：

```text
Token Sell Proceeds
>
Underlying Buy Cost
```

计算：

```text
stock_buy_notional
=
stock_ask × equivalent_stock_qty
```

```text
premium_gross_edge
=
token_sell_proceeds
-
stock_buy_notional
```

注意：

溢价方向后续会受到 Mint 时间影响，因此 Shadow Test 不能假定 T0 Sell RFQ 一定能等到 Token Mint 完成。

---

# 12. Shadow Test 必须记录 Edge Survival

只看 T0 Edge 没有意义。

每次 Opportunity 出现后，应继续观察：

```text
T0
T0 + 50ms
T0 + 100ms
T0 + 250ms
T0 + 500ms
T0 + 1s
```

保存：

```text
initial_edge_bps

edge_50ms
edge_100ms
edge_250ms
edge_500ms
edge_1000ms
```

最终统计：

```text
P(edge > threshold at T0)

P(edge > threshold after 50ms)
P(edge > threshold after 100ms)
P(edge > threshold after 250ms)
P(edge > threshold after 500ms)
P(edge > threshold after 1s)
```

例如策略要求：

```text
minimum edge = 15bps
```

则重点看：

```text
P(edge > 15bps after 100ms)
P(edge > 15bps after 500ms)
```

---

# 13. UAT-00：Realtime RFQ & Entitlement Test

建议在现有 UAT-01 前新增：

```text
UAT-00
Realtime RFQ & Entitlement Test
```

目标：

> 在不触碰真实股票 Short、Token Transfer 和 Redeem 的情况下，验证报价层是否真的存在可执行套利空间。

---

## 13.1 UAT-00 输入

```text
Ondo API
xStocks API
Alpaca / Stock Market Data
```

---

## 13.2 实时循环

```text
                 ┌─ Ondo AAPLon Buy Soft
                 ├─ Ondo AAPLon Sell Soft
Realtime Loop ───┼─ xStocks AAPLx Buy Soft
                 ├─ xStocks AAPLx Sell Soft
                 └─ AAPL Bid / Ask / Size
```

同时周期性读取：

```text
Ondo Trading Limits
Ondo Market Status

xStocks Asset Configuration
xStocks Trading Halt
xStocks Execution Timeout
```

---

# 14. UAT-00 输出字段

建议每次 RFQ 保存：

```yaml
timestamp:

underlying:
  symbol: AAPL
  bid:
  ask:
  bid_size:
  ask_size:
  received_at:

ondo:
  token: AAPLon

  buy:
    price:
    qty:
    latency_ms:
    expiration:
    ttl_ms:

  sell:
    price:
    qty:
    latency_ms:
    expiration:
    ttl_ms:

xstocks:
  token: AAPLx

  buy:
    soft_quote_id:
    price:
    qty:
    latency_ms:
    expiration:
    ttl_ms:

  sell:
    soft_quote_id:
    price:
    qty:
    latency_ms:
    expiration:
    ttl_ms:

edge:
  ondo_discount_bps:
  ondo_premium_bps:

  xstocks_discount_bps:
  xstocks_premium_bps:
```

---

# 15. UAT-00 最终必须产出的统计

## 15.1 RFQ Latency

分别统计：

```text
Ondo Buy RFQ p50 / p95 / p99
Ondo Sell RFQ p50 / p95 / p99

xStocks Buy RFQ p50 / p95 / p99
xStocks Sell RFQ p50 / p95 / p99
```

---

## 15.2 RFQ TTL

统计：

```text
Ondo TTL p50 / p95 / min
xStocks TTL p50 / p95 / min
```

---

## 15.3 Opportunity Count

例如：

```text
edge > 0bps

edge > 10bps

edge > 15bps

edge > 25bps

edge > 50bps

edge > 100bps
```

分别统计：

```text
Ondo
xStocks
```

---

## 15.4 Edge Survival

统计：

```text
Opportunity at T0

Still profitable at:
50ms
100ms
250ms
500ms
1s
```

---

## 15.5 Size Capacity

测试：

```text
1
5
10
25
50
100
```

得到：

```text
size
vs
edge
vs
RFQ spread
```

用于判断真正可交易容量。

---

# 16. 当前仅凭 API Key 不能完成的测试

## 16.1 真正 xChange Token Buy

还需要：

```text
Registered Wallet

Stablecoin Balance

Native Gas

Wallet Signing

Contract Execution
```

Hard RFQ 成功：

```text
≠
```

Token 已到账。

---

## 16.2 AAPLx Redeem → AAPL

完整流程是：

```text
W_AP_TEST
   │
   │ AAPLx
   ▼
Issuer Redemption Wallet
   ↓
Issuer
   ↓
Alpaca ITN
   ↓
Issuer Alpaca Account
   ↓
Journal AAPL
   ↓
ALPACA_AP_TEST
```

所以还需要：

```text
xPort / ITN entitlement

Registered Wallet

Issuer Redemption Wallet

Backed / xStocks Client
↕
Alpaca AP Account Mapping
```

---

# 17. 后续 UAT 推进顺序

建议顺序：

```text
UAT-00
Realtime RFQ & Entitlement
↓
UAT-01
Wallet Connectivity
↓
UAT-02
Token Receive
↓
UAT-03
Redeem Only
↓
UAT-04
Short + Redeem
↓
UAT-05
xChange Buy + Redeem
↓
UAT-06
Full Arbitrage
```

---

# 18. UAT-01：Wallet Connectivity

需要 Fireblocks / 测试 Wallet。

测试：

```text
Whitelist
Policy
Sign
Broadcast
Confirm
```

目的：

```text
证明 W_AP_TEST 可以正常做链上操作。
```

---

# 19. UAT-02：Token Receive

测试：

```text
xChange / Test Funding
→
W_AP_TEST
```

确认：

```text
AAPLx Balance
Token Contract
Decimals
Network
```

---

# 20. UAT-03：Redeem Only

不 Short 股票。

测试：

```text
W_AP_TEST
AAPLx
   ↓
Issuer Redemption Wallet
   ↓
Issuer
   ↓
Alpaca
   ↓
ALPACA_AP_TEST
+AAPL
```

这是完整 UAT 里最关键的一次测试。

---

# 21. UAT-04：Short + Redeem

先：

```text
ALPACA_AP_TEST
Short AAPL
```

再：

```text
Redeem 等量 AAPLx
```

最终验证：

```text
AAPL Position = 0
```

---

# 22. UAT-05：xChange Buy + Redeem

测试：

```text
USDC
↓
AAPLx
↓
Redeem
↓
AAPL
```

但暂时不自动 Short。

---

# 23. UAT-06：完整套利

最终：

```text
Realtime Edge
↓
Hard RFQ
↓
Short AAPL
↓
Short Fully Filled
↓
Execute Token Buy
↓
Token Confirm
↓
Token Received
↓
Redeem
↓
Issuer Processing
↓
Alpaca ITN
↓
AAPL Journal
↓
Position = 0
```

---

# 24. 完整 UAT 最重要的两个风险窗口

## 24.1 股票裸空窗口

```text
Short Filled
→
Token Buy Confirmed
```

统计：

```text
p50
p95
p99
max
```

这是整个折价套利最重要的执行风险之一。

---

## 24.2 Redeem Settlement Window

```text
Redeem Submitted
→
Underlying Position Observed
```

同样统计：

```text
p50
p95
p99
max
```

期间虽然经济上可能接近对冲，但仍然占用：

```text
Margin
Borrow
Position
Settlement Capacity
```

---

# 25. 当前阶段的 Go / No-Go 判断

第一阶段不要急着做完整套利。

先跑 UAT-00。

如果结果是：

```text
真实 RFQ 基本不存在可用 Edge
```

或者：

```text
T0 有 Edge
但 100~500ms 后大部分消失
```

那么：

```text
暂时没有必要优先投入完整 ITN / Redeem 自动化。
```

反过来，如果数据显示：

```text
初始 Edge 经常 > 25~50bps

并且：

100ms / 250ms / 500ms 后
仍然高于总成本
```

那么下一步应马上推进：

```text
Registered Wallet
↓
Hard RFQ
↓
小额 xChange Buy
↓
Redeem Only
↓
Short + Redeem
↓
完整套利
```

---

# 26. 当前最推荐马上实施的 5 项

按优先级：

```text
1. Ondo / xStocks API entitlement 检查

2. Ondo + xStocks Soft RFQ Collector

3. RFQ Latency / TTL / Size Curve 测量

4. 接 AAPL L1 做 Live Shadow Arbitrage

5. 有 Registered Wallet 后测试 Formal / Hard RFQ
```

---

# 27. 当前阶段最终要回答的 5 个问题

在开始真实套利之前，必须先用实时测试回答：

```text
1. Ondo 和 xStocks 哪家出现折价机会更多？

2. 哪家的真实 RFQ Edge 更大？

3. RFQ 的 p95 / p99 延迟是多少？

4. 机会在 100ms / 500ms 后还能剩多少？

5. 不同数量下真正可交易的容量有多大？
```

只有这 5 个问题有了真实数据，才值得继续推进完整的：

```text
RFQ
→
Short
→
Token Buy
→
Redeem
→
Alpaca Journal
→
Position = 0
```
