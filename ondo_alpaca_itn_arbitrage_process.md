# Ondo × Alpaca ITN 无库存套利流程

> 适用前提：你们是 Alpaca ITN 的机构 AP，并且 Ondo 已为你们开通相应的私有 in-kind mint/redeem 通道。  
> 文中的 `issuer=ondo`、接口参数、赎回地址等属于逻辑占位，实际以公司拿到的 integration spec 为准。

---

# 二、共同的开盘前准备

这些工作必须在监控价差之前完成。

## 1. Alpaca 账户检查

策略服务器读取：

```text
账户状态
AAPL 持仓
购买力
做空权限
borrow 状态
交易时段
未完成订单
ITN/AP 授权状态
```

确认：

```text
Alpaca 账户已和 Ondo AP 账户绑定
AAPL 支持 ITN mint/redeem
目标链支持 AAPLon
测试 Fireblocks 地址已白名单
```

## 2. Fireblocks 账户检查

读取：

```text
USDC/USDon 余额
AAPLon 余额
Gas 余额
目标链地址
交易策略是否允许自动签名
是否有人工审批
```

短周期套利不能依赖人工审批。Fireblocks 策略至少要允许：

```text
调用 Ondo 指定合约
向 Ondo 赎回地址转 AAPLon
接收 AAPLon
接收 USDC/USDon
支付 Gas
```

## 3. 获取资产映射

系统启动时加载：

```text
underlying_symbol = AAPL
token_symbol      = AAPLon
issuer            = 私有 Ondo issuer code
network           = 测试网络
wallet_address    = Fireblocks 地址
redemption_wallet = Ondo 提供的赎回地址
multiplier        = 每枚 AAPLon 对应的 AAPL 数量
```

不要永久假设：

```text
1 AAPLon = 1 AAPL
```

应以发行方提供的转换数量或 multiplier 为准。

定义：

```text
q = AAPLon 数量
m = 每枚 AAPLon 对应的 AAPL 数量
Q = q × m = 等效 AAPL 数量
```

## 4. 建立行情连接

### 股票端

使用 Alpaca 实时 Market Data WebSocket，持续保存：

```text
stock_bid
stock_ask
stock_bid_size
stock_ask_size
stock_exchange_timestamp
stock_received_timestamp
```

### Token 端

使用 Ondo：

```text
Soft Buy RFQ
Soft Sell RFQ
市场状态
资产交易状态
报价时间戳
```

普通资产价格只适合展示，实际交易判断应使用 Soft RFQ。Soft RFQ 本身不可上链，只作为非约束性价格参考。

---

# 三、套利方向一：AAPLon 折价

## 经济关系

Token 便宜、股票贵：

```text
用 Ondo RFQ 买 AAPLon 的成本
<
通过 ITN 赎回后卖出 AAPL 的收入
```

完整路径：

```text
买入 AAPLon
+
临时做空等效 AAPL
        ↓
通过 ITN 把 AAPLon 赎回为 AAPL
        ↓
到账股票自动抵消空头
```

这不是长期库存，只是在 ITN 处理期间做临时对冲。

## 折价套利详细时间线

### T−∞：持续监控

策略服务器同时取得：

来自 Alpaca：

```text
AAPL bid
AAPL bid size
行情时间戳
borrow 状态
```

来自 Ondo：

```text
AAPLon Buy Soft RFQ
对应 token 数量
需要支付的 USDC/USDon
报价响应时间
```

假设：

```text
q = 100 AAPLon
m = 1
Q = 100 AAPL

AAPL bid = $200.00
Ondo Buy Soft RFQ 总成本 = $19,950
```

初步边际：

```text
股票卖空收入 = 100 × $200.00 = $20,000

毛边际
= $20,000 - $19,950
= $50
```

然后扣除：

```text
股票滑点

Ondo RFQ spread
链上 Gas
ITN 费用
稳定币成本
失败风险缓冲
```

触发公式：

```text
expected_edge
=
stock_bid × Q
- token_buy_soft_total
- estimated_all_costs
```

只有：

```text
expected_edge ≥ discovery_threshold
```

才进入下一步。

建议初始检查：

```text
股票行情年龄 ≤ 500ms
Ondo Soft RFQ 响应 ≤ 2s
股票 bid size 足以覆盖 Q
Fireblocks USDC 和 Gas 充足
AAPL 可以做空
Ondo 和 ITN 状态正常
```

这些是工程参数，不是官方 SLA。

### T0：向 Ondo 申请正式 Buy RFQ

策略服务器向 Ondo API 账户请求正式 Buy attestation：

```text
symbol = AAPLon
side = buy
amount = q
wallet = Fireblocks 地址
duration = short/测试配置
```

Ondo 返回：

```text
正式 token 数量
正式 USDC 成本
attestation ID
signature
expiration
合约调用参数
```

系统检查：

```text
报价 side 正确
数量正确
钱包正确
expiration 剩余时间充分
正式价格仍有利润
```

建议：

```text
RFQ API 等待上限：2 秒
剩余有效期不足内部安全值：放弃
```

### T+约 0.2～2 秒：根据正式 RFQ 计算股票最低卖价

计算：

```text
minimum_stock_sell_price
=
(
    formal_token_buy_cost
  + total_expected_cost
  + minimum_required_profit
) / Q
```

例如：

```text
正式买 token 成本 = $19,955
总费用            = $15
最低利润要求      = $20
股票数量          = 100

股票最低卖价
= ($19,955 + $15 + $20) / 100
= $199.90
```

只有最新 AAPL bid 不低于 $199.90，才继续。

### T+约 0.5～3 秒：Alpaca 临时做空 AAPL

策略服务器向 Alpaca AP 账户提交：

```text
Sell Short AAPL
qty = Q
type = limit
limit_price ≥ minimum_stock_sell_price
TIF = FOK 或严格 IOC
client_order_id = opportunity_id
```

等待：

```text
filled
rejected
canceled
partially_filled
```

建议：

```text
目标成交响应：200ms～1 秒
超过 2 秒无确定状态：取消并查询最终状态
```

结果处理：

- **全部成交**：立即执行 Ondo Buy RFQ。
- **完全未成交**：不执行 token 买入。
- **部分成交**：取消剩余部分，并立即买回已成交空头；不要按完整数量执行 token。
- **状态未知**：暂停此标的，主动查询订单状态。

股票腿先执行，是因为股票订单可以使用严格限价/FOK 控制；若先买 token 而股票做空失败，会留下裸多 token。

### T+约 1～4 秒：Fireblocks 执行 Ondo Buy RFQ

策略服务器通过 Ondo 正式 attestation 构造链上买入交易：

```text
USDC/USDon → AAPLon
```

Fireblocks 完成：

```text
策略校验
自动审批
签名
广播
```

等待：

```text
Fireblocks 状态已广播
链上交易确认
USDC 余额减少
AAPLon 余额增加 q
```

只有以下两个条件都成立才认为 token 买入成功：

```text
链上 receipt 成功
AAPLon 可用余额增加 q
```

如果 Ondo 交易因报价过期或其他原因失败：

```text
立即在 Alpaca 买回 Q 股 AAPL
结束机会
记录临时裸空时间和损失
```

### T+链上确认后：发起 ITN Redeem

现在 Fireblocks 已有 q 个 AAPLon。

根据你们私有集成要求执行其中一种：

```text
A. 将 AAPLon 发送至 Ondo 指定 redemption wallet
B. 调用 Ondo 专用 redeem 合约
C. 调用 Ondo 私有 ITN redemption API 后再转 token
```

记录：

```text
t_redeem_submit
链上 tx_hash
t_token_transfer_confirmed
issuer_request_id
```

### T+Redeem 确认后：Ondo 通知 Alpaca

这一步通常由 Ondo 系统自动完成，不是你们直接调用 Alpaca 的 issuer callback。

Ondo 向 Alpaca 提交：

```text
issuer_request_id
underlying_symbol = AAPL
token_symbol = AAPLon
qty = Q
network
原 Fireblocks wallet
token redeem tx_hash
你们的 Alpaca/Ondo 关联账户 ID
```

### T+等待 ITN 完成：Alpaca 把 AAPL 划入 AP 账户

Alpaca 执行：

```text
Ondo 的 Alpaca 发行方账户
        ↓ journal Q 股 AAPL
你们的 Alpaca AP 账户
```

策略服务器监控：

```text
GET tokenization requests
GET tokenization request by ID
Alpaca 持仓更新
账户活动/journal 状态
```

状态：

```text
pending
completed
rejected
```

建议测试轮询：

```text
0～10 秒：每 500ms
10～60 秒：每 1 秒
1～10 分钟：每 5 秒
超过 10 分钟：标记 stuck，进入异常处理
```

最终以公司 API 限流规则为准。

### ITN 完成：股票自动抵消空头

原先 Alpaca：

```text
AAPL position = -100
```

ITN journal 进入：

```text
+100 AAPL
```

结果：

```text
AAPL 净仓位 = 0
```

通常不再需要单独提交 `buy to cover`，因为进入账户的股票会与空头净额合并。测试环境必须确认 Alpaca 的实际持仓和 journal 记账方式。

最终闭环：

```text
Fireblocks：
AAPLon = 0
USDC 减少

Alpaca：
AAPL 仓位 = 0
股票做空产生现金收入
```

最终利润：

```text
PnL_discount
=
股票做空实际收入
- Ondo 买 token 实际成本
- 股票费用
- 临时借券费用
- Ondo RFQ 费用
- 链上 Gas
- ITN 费用
- 稳定币成本
```

---

# 四、套利方向二：AAPLon 溢价

## 经济关系

Token 贵、股票便宜：

```text
Ondo RFQ 卖出 AAPLon 所得
>
买入 AAPL 并通过 ITN mint 的成本
```

完整路径：

```text
USD 现金
  ↓ Alpaca 买 AAPL
AAPL
  ↓ Alpaca ITN Mint
AAPLon
  ↓ Ondo Sell RFQ
USDC/USDon
```

这条路线不再需要提前持有 token，也不需要 token 借贷。

但仍然有一个核心问题：

> 从买入股票到 ITN mint 完成期间，最初看到的 Token Sell RFQ 可能过期或价格变化。

所以它只有在以下任一条件成立时才能接近锁价套利：

1. ITN mint 的实测完成时间明显短于 Ondo 正式 RFQ 有效期。
2. Ondo 允许你们在尚未持有 token 时预取 Sell attestation。
3. 私有 ITN 协议提供 RFQ reservation 或报价延长机制。
4. 你们另有临时 token 借贷。

否则，它仍然是带 mint 等待风险的转换交易。

## 溢价套利详细时间线

### T−∞：持续监控

策略服务器取得：

来自 Alpaca：

```text
AAPL ask
AAPL ask size
行情时间戳
购买力
```

来自 Ondo：

```text
AAPLon Sell Soft RFQ
报价数量
预计收到的 USDC/USDon
```

假设：

```text
q = 100 AAPLon
Q = 100 AAPL

AAPL ask = $200.00
Ondo Sell Soft RFQ 所得 = $20,060
```

初始边际：

```text
stock_cost = 100 × $200 = $20,000

gross_edge
= $20,060 - $20,000
= $60
```

扣除：

```text
股票费用和滑点
ITN 费用
RFQ spread
链上 Gas
资金成本
mint 等待风险缓冲
```

触发公式：

```text
expected_edge
=
token_sell_soft_proceeds
- stock_ask × Q
- estimated_all_costs
```

### T0：尝试获取正式 Sell RFQ

如果 Ondo 测试环境允许没有 token 余额时申请正式 Sell attestation：

策略服务器向 Ondo API 请求：

```text
symbol = AAPLon
side = sell
tokenAmount = q
wallet = Fireblocks 地址
```

返回：

```text
正式卖出所得
signature
expiration
合约参数
```

然后计算可用于全过程的时间预算：

```text
available_time
=
expiration
- current_time
- chain_execution_buffer
```

必须满足：

```text
available_time
>
股票成交时间
+ Alpaca ITN mint 时间
+ token 钱包同步时间
+ Fireblocks 签名广播时间
+ 安全缓冲
```

如果 Ondo 不允许无余额申请正式 Sell RFQ，那么 T0 只能使用 Soft Quote；必须在 AAPLon 到账后重新申请正式 Sell RFQ。这种情况下初始利润无法锁定。

### T+约 0.2～2 秒：根据正式 RFQ 计算股票最高买价

```text
maximum_stock_buy_price
=
(
    formal_token_sell_proceeds
  - total_expected_cost
  - minimum_required_profit
) / Q
```

例如：

```text
正式卖 token 所得 = $20,055
预计总费用        = $15
最低利润          = $20
Q                 = 100 股

最高股票买价
= ($20,055 - $15 - $20) / 100
= $200.20
```

只有最新股票 ask ≤ $200.20 才继续。

### T+约 0.5～3 秒：Alpaca 买入 AAPL

策略服务器向 Alpaca AP 账户提交：

```text
Buy AAPL
qty = Q
type = limit
limit_price ≤ maximum_stock_buy_price
TIF = FOK 或严格 IOC
client_order_id = opportunity_id
```

结果处理：

- **全部成交**：立即发起 ITN mint。
- **没有成交**：结束机会，不使用 RFQ。
- **部分成交**：立即卖回已成交股票，不做完整 mint。
- **状态不明**：暂停并查询。

### T+股票成交后：发起 Alpaca ITN Mint

策略服务器向 Alpaca AP 接口提交逻辑请求：

```json
{
  "underlying_symbol": "AAPL",
  "qty": "100",
  "issuer": "<Ondo私有issuer code>",
  "network": "<测试网络>",
  "wallet_address": "<Fireblocks地址>",
  "client_request_id": "<opportunity_id>"
}
```

并使用唯一：

```text
Idempotency-Key
```

Mint 请求返回 `pending` 并不代表 token 已到账。

### T+Mint 请求后：Alpaca 与 Ondo 内部处理

系统内部顺序是：

```text
1. Alpaca 验证 AP 资格
2. Alpaca 验证 AAPL 持仓 ≥ Q
3. Alpaca 调用 Ondo 的 mint 验证接口
4. Ondo 验证 AP 账户、钱包和网络
5. Alpaca 把 Q 股 AAPL journal 到 Ondo 的 Alpaca 账户
6. Alpaca 向 Ondo 确认股票 journal 完成
7. Ondo 在链上 mint q 个 AAPLon
8. Ondo 发送 AAPLon 到 Fireblocks
9. Ondo 向 Alpaca 回调 mint 完成
10. Alpaca tokenization request 变为 completed
```

### T+等待 Mint 完成：双重确认

策略服务器监控：

```text
Alpaca tokenization_request.status
Fireblocks AAPLon balance
链上 token Transfer 事件
```

必须同时满足：

```text
Alpaca 状态 = completed
Fireblocks 可用 AAPLon 增加 q
```

只看到 `pending`，不能执行卖出。

测试期间记录：

```text
t_stock_filled
t_mint_submitted
t_alpaca_journal_completed
t_token_tx_created
t_token_chain_confirmed
t_fireblocks_balance_updated
t_mint_completed
```

不要事先假设 ITN 是 1 秒、5 秒或 30 秒。应通过测试账户测出：

```text
mint_latency_p50
mint_latency_p90
mint_latency_p95
mint_latency_p99
```

### AAPLon 到账后：检查原 RFQ 是否仍有效

#### 情况 A：原正式 Sell RFQ 仍有效

检查：

```text
current_time
<
expiration - safety_buffer
```

如果仍有足够时间，Fireblocks 向 Ondo 合约执行：

```text
AAPLon → USDC/USDon
```

等待：

```text
AAPLon 余额减少
USDC/USDon 余额增加
链上 receipt 成功
```

完成套利。

#### 情况 B：原 RFQ 已经过期

必须重新向 Ondo 请求：

```text
新的 Sell Soft Quote
新的正式 Sell Attestation
```

重新计算：

```text
current_exit_edge
=
new_token_sell_proceeds
- actual_stock_purchase_cost
- actual_all_costs
```

如果仍然盈利，执行新的 Sell RFQ。

如果已经不盈利，则有两个退出选项：

```text
选项 1：仍卖出 AAPLon，接受小额亏损并结束风险

选项 2：把 AAPLon 通过 ITN redeem 回 AAPL，
        等 AAPL 回到 Alpaca 后卖掉股票
```

第二种路径更慢，而且仍有价格风险，不能为了等待价差回来而无限持仓。

### 溢价套利完成

最终：

```text
Alpaca：
AAPL 仓位 = 0
股票已被 ITN 划给 Ondo

Fireblocks：
AAPLon = 0
USDC/USDon 增加
```

利润：

```text
PnL_premium
=
Ondo 卖 token 实际所得
- Alpaca 买股票实际成本
- 股票费用
- ITN 费用
- 链上 Gas
- RFQ 费用
- 资金成本
```

---

# 五、两条路径的本质区别

## Token 折价：更容易锁价

推荐顺序：

```text
1. 获取 Ondo 正式 Buy RFQ
2. 做空 AAPL
3. 执行 RFQ 买 AAPLon
4. AAPLon 通过 ITN redeem 为 AAPL
5. 到账 AAPL 抵消空头
```

从步骤 3 完成开始，持仓是：

```text
多 AAPLon
空等效 AAPL
```

因此 ITN 等待期间 Delta 接近中性。

主要风险是：

```text
股票做空成功但 Ondo 买入失败
Token redemption 失败或延迟
借券费与召回风险
转换比例差异
```

## Token 溢价：仍有 Mint 时间风险

顺序：

```text
1. 看到 Ondo Sell RFQ
2. 买入 AAPL
3. ITN mint AAPLon
4. AAPLon 到账
5. 执行 Ondo Sell RFQ
```

等待期间是：

```text
多 AAPL
```

所以如果正式 RFQ 无法覆盖整个 mint 时间，这个方向仍然没有完全锁价。

ITN 解决的是：

> 你们不需要长期持有 AAPLon 库存，也可以用 AAPL 创造 AAPLon。

但 ITN 本身不保证：

> T0 看到的 Ondo 卖出价格会等到 token 到账。

---

# 六、实时回测应该怎么模拟

## 折价方向

实时影子流程：

```text
T0：
记录 AAPL bid
记录 Ondo Buy Soft RFQ

T0+正式报价延迟：
模拟取得正式 Buy 报价

T0+股票执行延迟：
记录当时真实 bid，模拟 Sell Short

T0+链上买 token 延迟：
等待对应时间

T0+ITN redeem 延迟：
等实测/假设的 redeem 完成时间

最终：
用最初股票卖空价格
减去 token 买入成本和所有费用
```

因为股票先做空，ITN 等待期间主要是配对仓位。

## 溢价方向

实时影子流程：

```text
T0：
记录 AAPL ask
记录 Ondo Sell Soft RFQ

T0+股票执行延迟：
记录真实 ask，模拟买入 AAPL

T0+ITN mint 延迟：
等待 1s/5s/15s/30s/60s 等情景

每个完成时间点：
重新请求或记录 Ondo Sell Soft RFQ

最终：
使用 mint 完成时的新 RFQ，而不是 T0 旧 RFQ
```

必须输出：

```text
T0 理论利润
Mint 完成时实际可退出利润
因 ITN 等待损失的利润
原 RFQ 仍有效的比例
重新报价后仍盈利的比例
```

---

# 七、建议的初始超时设置

下面只是测试参数：

| 阶段 | 初始目标 | 异常处理 |
|---|---:|---|
| 股票行情年龄 | ≤500ms | 超过 1 秒不触发 |
| Ondo Soft RFQ | ≤1 秒 | 超过 2 秒放弃 |
| Ondo 正式 RFQ | ≤1 秒 | 超过 2 秒重新评估 |
| 股票 FOK 结果 | ≤1 秒 | 超过 2 秒取消/查询 |
| Fireblocks 自动签名 | ≤1 秒 | 超过内部预算放弃 |
| 链上 RFQ 确认 | 实际测量 | 超时则检查 receipt |
| ITN mint/redeem | 实际测量 | 记录 p50/p95/p99 |
| Fireblocks 余额同步 | ≤5 秒 | 超时主动读取链上余额 |
| ITN pending | 60 秒告警 | 10 分钟标记 stuck |

最核心的两个统计量是：

```text
P(
  ITN mint 完成
  <
  Ondo Sell RFQ 到期时间 - 安全缓冲
)
```

以及：

```text
P(
  Ondo Buy 成功后
  ITN redeem 最终成功
)
```

---

# 八、最终修正后的两条时间线

## AAPLon 折价

```text
Alpaca 行情：
读取 AAPL bid
        ↓
Ondo：
获取 Buy Soft RFQ
        ↓
策略服务器：
判断 token 便宜
        ↓
Ondo：
申请正式 Buy RFQ
        ↓
Alpaca AP 账户：
做空等效 AAPL
        ↓ 全部成交
Fireblocks：
用 USDC 执行 Ondo RFQ 买 AAPLon
        ↓ AAPLon 到账
Fireblocks/Ondo：
将 AAPLon 提交 ITN redeem
        ↓
Ondo：
销毁 AAPLon 并通知 Alpaca
        ↓
Alpaca：
将等效 AAPL 划入 AP 账户
        ↓
进入的 AAPL 抵消原股票空头
        ↓
仓位归零，计算利润
```

## AAPLon 溢价

```text
Alpaca 行情：
读取 AAPL ask
        ↓
Ondo：
获取 Sell Soft/正式 RFQ
        ↓
策略服务器：
判断 token 昂贵
        ↓
Alpaca AP 账户：
买入等效 AAPL
        ↓ 全部成交
Alpaca ITN：
提交 stock → AAPLon mint
        ↓
Alpaca：
将 AAPL 划至 Ondo 账户
        ↓
Ondo：
mint AAPLon 到 Fireblocks
        ↓
Fireblocks：
确认 AAPLon 到账
        ↓
Ondo：
若原 Sell RFQ 仍有效则执行；
否则重新报价并重新判断利润
        ↓
Fireblocks：
卖 AAPLon，收到 USDC/USDon
        ↓
仓位归零，计算利润
```
