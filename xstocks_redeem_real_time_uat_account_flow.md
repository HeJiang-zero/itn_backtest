# xStocks Redeem 套利真实测试环境与账户/地址流程设计

> 本文用于把当前回测/影子执行模型进一步落成真实测试环境（UAT / Sandbox）中的账户、钱包、地址、订单和 Redeem 流程。
>
> 核心目标：
>
> **低价买入 xStock Token → Alpaca 卖空对应股票 → Token 到钱包 → Token Redeem 成股票 → 股票进入同一个 Alpaca 测试账户 → 抵消空头。**
>
> 本文重点说明：
>
> - 需要哪些测试账号；
> - 需要哪些链上地址；
> - 每个账号/地址由谁控制；
> - Token Buy 时资产从哪里到哪里；
> - Redeem 时 Token 从哪里发到哪里；
> - 股票最终如何进入 Alpaca；
> - 我们应监听哪些状态；
> - 如何把当前回测模型中的抽象状态映射成真实测试流程。

---

# 1. 真实测试环境总体拓扑

建议第一版测试环境尽量保持简单：

- 一个策略主体；
- 一个 Alpaca AP 测试账户；
- 一个 Fireblocks 测试 Workspace；
- 一个 Fireblocks 主 Vault；
- 一个主要测试钱包地址；
- 一个 xStocks / Backed 测试 Client；
- 一个 Issuer 提供的 Redemption Wallet。

整体拓扑：

```text
                       我们的套利服务
                            │
            ┌───────────────┼─────────────────┐
            │               │                 │
            ▼               ▼                 ▼
    xStocks / Backed     Alpaca Broker      Fireblocks
      Test/UAT API        Sandbox API      Sandbox Workspace
            │               │                 │
            │               │                 │
      xChange RFQ           │             W_AP_TEST
            │               │          我们控制的钱包
            │               │                 │
            │               │        USDC / AAPLx / Gas
            │               │                 │
            └───────────────┼─────────────────┘
                            │
                         Arbitrage
                            │
              ┌─────────────┴─────────────┐
              │                           │
          买 AAPLx                    Short AAPL
              │                           │
              ▼                           ▼
         W_AP_TEST                ALPACA_AP_TEST
          +10 AAPLx                   -10 AAPL
              │
              │ send AAPLx
              ▼
      ISSUER_REDEEM_ADDRESS
         xStocks / Backed
              │
              │ issuer detects tx
              │ notifies Alpaca ITN
              ▼
       Issuer Alpaca Account
              │
              │ JNLS / ITN journal
              ▼
        ALPACA_AP_TEST
           +10 AAPL
              │
              ▼
       -10 + 10 = 0 AAPL
              │
              ▼
          Trade Completed
```

这就是当前回测模型：

```text
stock short
    ↓
token buy
    ↓
token received
    ↓
redeem
    ↓
issuer process
    ↓
alpaca journal
    ↓
short position = 0
```

在真实测试环境中的具体实现。

---

# 2. 需要哪些测试账号

建议至少建立以下逻辑账户。

| 逻辑名称 | 谁控制 | 类型 | 主要用途 |
|---|---|---|---|
| `BACKED_CLIENT_TEST` | 我们 | xStocks / Backed 测试 Client / AP 账号 | RFQ、Registered Wallet、xChange、xPort / ITN 身份 |
| `ALPACA_AP_TEST` | 我们 | Alpaca Broker Sandbox Account | 卖空 AAPL、最终接收 Redeem 后的 AAPL |
| `FIREBLOCKS_TEST_WORKSPACE` | 我们 | Fireblocks Sandbox Workspace | 钱包托管、交易审批、签名、广播 |
| `FB_VAULT_ARB_01` | 我们 | Fireblocks Vault Account | 存放 USDC、AAPLx、Gas |
| `W_AP_TEST` | 我们 | Vault 对应链上地址 | 支付 USDC、接收 AAPLx、发起 Redeem |
| `XSTOCKS_XCHANGE` | Backed / Issuer | xChange Atomic RFQ Settlement | USDC 与 AAPLx 的原子交换 |
| `XSTOCKS_REDEEM_TEST` | Backed / Issuer | xPort / ITN Redemption Address | 接收我们 Redeem 的 AAPLx |
| `ISSUER_ALPACA_ACCOUNT` | Issuer | Issuer 在 Alpaca 的证券账户 | Redeem 后股票从该账户 Journal 给 AP |

---

# 3. 一个最重要的设计原则：股票账户必须尽量统一

第一版真实测试中，建议：

```text
卖空 AAPL 的账户
=
Redeem 后接收 AAPL 的账户
=
ALPACA_AP_TEST
```

也就是说：

```text
ALPACA_AP_TEST

开始：
AAPL = 0

卖空后：
AAPL = -10

Redeem 股票到账：
AAPL = -10 + 10 = 0
```

不要一开始设计成：

```text
TRADING_ACCOUNT
AAPL = -10

TOKENIZATION_ACCOUNT
AAPL = +10
```

虽然公司整体净仓位为 0，但两个独立账户都没有真正闭环，后续还需要额外 Journal 或 Position Transfer。

因此，最干净的 UAT 架构是：

```text
同一个 Alpaca AP Sandbox Account
同时承担：
1. Short 股票
2. 接收 Redeem 后的 Underlying 股票
```

---

# 4. Fireblocks 主测试钱包：W_AP_TEST

第一版建议把以下三个功能全部放在同一个链上钱包：

```text
W_AP_TEST
```

它同时承担：

## 4.1 Payment Wallet

用来支付：

```text
USDC / 其他支持 Stablecoin
```

参与 xChange Buy RFQ。

---

## 4.2 Receiving Wallet

用来接收：

```text
AAPLx
```

也就是 xChange Buy 成功后 Token 最终进入的地址。

---

## 4.3 Redeem Origin Wallet

之后再从同一个地址：

```text
W_AP_TEST
```

把 AAPLx 发送到 Issuer 指定的：

```text
XSTOCKS_REDEEM_TEST
```

触发 Redeem。

---

# 5. 为什么第一版 Payment / Receiving / Redeem Wallet 最好统一

xChange RFQ 本身可以区分：

```text
paymentWalletIdentifier
receivingWalletIdentifier
```

第一阶段可以直接配置：

```text
paymentWalletIdentifier   = W_AP_TEST
receivingWalletIdentifier = W_AP_TEST
```

这样：

```text
USDC:
W_AP_TEST
   ↓
xChange

AAPLx:
xChange
   ↓
W_AP_TEST
```

后续 Redeem：

```text
AAPLx:
W_AP_TEST
   ↓
XSTOCKS_REDEEM_TEST
```

这样能够减少：

- 多钱包余额同步；
- 多地址 whitelist；
- Fireblocks Policy 数量；
- 资金归集；
- Token 在内部钱包之间的额外 transfer；
- Gas 费用；
- 对账复杂度。

---

# 6. W_AP_TEST 必须同时在两个体系中建立身份

这个钱包并不是生成一个地址就可以直接参与 Redeem。

需要同时完成：

## 6.1 xStocks / Backed 侧

将：

```text
W_AP_TEST
```

注册为：

```text
Registered / Whitelisted Wallet
```

并和：

```text
BACKED_CLIENT_TEST
```

建立绑定关系。

逻辑：

```text
W_AP_TEST
    ↓
BACKED_CLIENT_TEST
    ↓
AP / Client Identity
```

---

## 6.2 Fireblocks 侧

`W_AP_TEST` 本身属于：

```text
FB_VAULT_ARB_01
```

由：

```text
FIREBLOCKS_TEST_WORKSPACE
```

控制。

而 Issuer 给我们的：

```text
XSTOCKS_REDEEM_TEST
```

不是我们的钱包。

因此在 Fireblocks 中应把它设置为：

```text
External Wallet
```

并执行 whitelist。

---

# 7. Fireblocks 第一版配置

建议创建：

```text
Workspace:
FIREBLOCKS_TEST_WORKSPACE

Vault:
FB_VAULT_ARB_01

Wallet:
W_AP_TEST
```

Vault 中只放和测试相关的资产：

```text
Native Gas Asset
Stablecoin
AAPLx
```

例如：

```text
ETH / SOL / ARB
USDC
AAPLx
```

具体资产取决于最终测试 Network。

需要 whitelist：

```text
XSTOCKS_REDEEM_TEST
```

如果 xChange 需要直接调用合约，还应根据 Network 和 Fireblocks Policy 配置：

```text
xChange Contract
```

对应的：

```text
Contract Wallet / Contract Call Policy
```

---

# 8. 真正的实时测试完整流程

---

# 8.1 Step 0：实时接收股票和 Token 市场信息

实时系统持续接收：

```text
AAPL Bid / Ask
AAPL Bid Size / Ask Size
AAPLx RFQ / Indicative Quote
```

策略计算：

```text
股票 Short 可获得的价格
-
Token Buy 成本
-
全部费用
=
预计净 Edge
```

只有：

```text
net_edge > minimum_required_profit
```

才考虑交易。

---

# 8.2 Step 1：查询当前 xStocks Asset Configuration

正式环境不要再长期写死：

```text
Token Qty = 10
RFQ TTL = 30s
```

应实时查询资产配置。

例如逻辑：

```text
GET /api/v2/trades/xchange/assets/AAPLx
```

需要获得：

```text
minOrderFiatValue
maxOrderFiatValue
executionTimeoutSeconds
isTradingHalted
network
token deployment
```

然后检查：

```text
当前交易数量是否达到 minimum；
当前资产是否 halted；
当前 Network 是否支持；
当前 RFQ Timeout 是多少。
```

---

# 8.3 Step 2：请求正式 Hard RFQ

逻辑请求：

```text
POST /api/v2/trades/xchange/rfq
```

示例参数：

```text
identifier = AAPLx
side       = Buy
quantity   = Q
network    = TEST_NETWORK

paymentWalletIdentifier   = W_AP_TEST
receivingWalletIdentifier = W_AP_TEST
```

需要保存服务器返回的：

```text
quote_id
price
quantity
network
expiration
executionTimeout
signature
signaturePayload
contract
tokenDeployment
```

从这一刻开始，系统创建：

```text
trade_id
```

并把：

```text
xstocks_quote_id
```

挂在这笔 Trade 上。

---

# 9. RFQ 状态不要再只用 active / reserved

回测模型可以使用：

```text
active
reserved
used
expired
```

真实测试建议扩展成：

```text
rfq_received
    ↓
rfq_accepted
    ↓
rfq_pending_execution
    ↓
rfq_tx_created
    ↓
rfq_tx_signed
    ↓
rfq_tx_broadcast
    ↓
rfq_tx_confirmed
```

失败状态至少包括：

```text
rfq_expired
rfq_rejected
rfq_sign_failed
rfq_broadcast_failed
rfq_chain_failed
rfq_unknown
```

---

# 10. Step 3：Alpaca 卖空股票

绑定：

```text
ALPACA_AP_TEST
```

比如：

```text
account_id = AP_ACCOUNT_ID_TEST
```

向这个账户发送：

```text
SELL / SHORT AAPL
qty = Q
```

开始：

```text
AAPL = 0
```

卖空 10 股之后：

```text
AAPL = -10
```

应记录：

```text
alpaca_account_id
alpaca_order_id
client_order_id
symbol
side
qty
submitted_at
filled_at
filled_qty
filled_avg_price
status
```

只有：

```text
filled_qty == Q
```

之后才继续真正执行 Token Buy。

---

# 11. 为什么股票腿应先成交

当前套利方向是：

```text
低价买 Token
+
高价 Short Stock
+
Token Redeem 成 Stock
+
Stock 抵消 Short
```

真实执行时主要风险之一是：

```text
股票已经 Short
但 Token Buy 失败
```

因此当前模型使用：

```text
先锁 RFQ
→ 再 Short Stock
→ Stock Fully Filled
→ 再执行 RFQ
```

这个顺序在 UAT 中仍然合理。

需要真实测量：

```text
Short Fill
→ Token Confirm
```

这段时间的裸空风险。

---

# 12. Step 4：执行 xChange Token Buy

股票全额成交之后：

```text
ALPACA_AP_TEST
AAPL = -Q
```

开始执行已锁定 RFQ。

资产流：

```text
W_AP_TEST
   │
   │ USDC
   ▼
xStocks / xChange
   │
   │ AAPLx
   ▼
W_AP_TEST
```

成功以后：

```text
W_AP_TEST
AAPLx = +Q

ALPACA_AP_TEST
AAPL = -Q
```

例如：

```text
W_AP_TEST
AAPLx = +10

ALPACA_AP_TEST
AAPL = -10
```

此时才真正形成：

```text
Token Long
+
Stock Short
```

配对仓位。

---

# 13. xChange Buy 应记录哪些字段

至少记录：

```text
trade_id

xstocks_quote_id
xstocks_price
xstocks_qty

fireblocks_transaction_id
buy_tx_hash

payment_wallet
receiving_wallet

stablecoin_asset
stablecoin_qty

token_symbol
token_contract
token_qty

tx_created_at
tx_signed_at
tx_broadcast_at
tx_confirmed_at

token_balance_observed_at
```

---

# 14. Step 5：真正的 Redeem 是什么

这是把回测变成真实系统时最重要的概念变化。

当前回测可以抽象成：

```text
redeem_submit
    ↓
redeem_chain_confirm
    ↓
issuer_process
    ↓
alpaca_journal
```

真实环境里，作为 AP：

**不是我们调用 Alpaca 的一个 `/redeem` API。**

真正的 Redeem Trigger 是：

```text
从 W_AP_TEST
把 AAPLx
发送到 Issuer 指定的 Redemption Wallet
```

即：

```text
FROM:
W_AP_TEST

ASSET:
AAPLx

QTY:
Q

TO:
XSTOCKS_REDEEM_TEST
```

---

# 15. Redeem 真实资产流

假设：

```text
Q = 10
```

链上：

```text
W_AP_TEST
AAPLx = 10
   │
   │ transfer 10 AAPLx
   ▼
XSTOCKS_REDEEM_TEST
```

之后：

```text
W_AP_TEST
AAPLx = 0
```

此时只是：

```text
Redeem Submitted
```

还不能认为股票已经到账。

---

# 16. Redemption Wallet 不应写死

建议系统启动或定期查询 Issuer 提供的：

```text
In-Kind Sweeping Wallet
```

例如逻辑 API：

```text
/trades/inkind/sweeping-wallets
```

程序应保存：

```text
network
token_symbol
redemption_address
effective_from
last_verified_at
```

每次 Redeem 前再检查：

```text
当前 Network
+
Token
+
Redemption Address
```

是否匹配。

不要把：

```text
XSTOCKS_REDEEM_TEST
```

作为永久 hardcoded address。

---

# 17. Step 6：Issuer 检测链上 Redeem

Issuer 监控：

```text
XSTOCKS_REDEEM_TEST
```

发现：

```text
tx_hash = ...
from = W_AP_TEST
asset = AAPLx
qty = 10
```

之后识别：

```text
W_AP_TEST
    ↓
BACKED_CLIENT_TEST
    ↓
Alpaca AP Mapping
    ↓
AP_ACCOUNT_ID_TEST
```

因此 Issuer 才知道：

```text
这 10 股 AAPL
最终应该 Journal 到哪个 Alpaca Account。
```

---

# 18. 谁通知 Alpaca Redeem？

**Issuer 通知 Alpaca，不是我们。**

典型逻辑：

```text
Issuer
   │
   │ Redeem Callback
   ▼
Alpaca ITN
```

Issuer 侧会提交类似：

```text
AP Account / Client Identifier
issuer_request_id
network
qty
token_symbol
underlying_symbol
tx_hash
wallet_address
```

因此我们的策略系统不应假装自己是 Issuer 去调用 Redeem Callback。

我方系统的责任是：

```text
1. 发起链上 Token Transfer
2. 保存 tx_hash
3. 等待链上 confirmation
4. 轮询 / 监听 Alpaca ITN Request
5. 验证股票最终到账
```

---

# 19. Alpaca 如何知道股票给哪个账户

测试环境必须提前建立：

```text
BACKED_CLIENT_TEST
    ↕
ALPACA_AP_TEST
```

映射。

身份链：

```text
W_AP_TEST
     ↓
Backed Client ID
     ↓
AP / Authorized Participant Identity
     ↓
Alpaca AP Account
     ↓
AP_ACCOUNT_ID_TEST
```

所以需要向 Backed / Alpaca 双方确认：

```text
W_AP_TEST
是否已经注册给 BACKED_CLIENT_TEST；

BACKED_CLIENT_TEST
是否已经 mapping 到 AP_ACCOUNT_ID_TEST。
```

这是端到端 Redeem 能否成功的关键。

---

# 20. Step 7：Underlying 股票 Journal

Redeem 后并不是股票直接“从区块链进入 Alpaca”。

真实流程：

```text
Issuer Redemption Wallet
收到 AAPLx
        ↓
Issuer 确认 Token
        ↓
Issuer 通知 Alpaca ITN
        ↓
Issuer Alpaca Account
        │
        │ Journal AAPL
        ▼
ALPACA_AP_TEST
```

假设之前：

```text
ALPACA_AP_TEST
AAPL = -10
```

Journal：

```text
+10 AAPL
```

之后：

```text
AAPL = 0
```

套利完成。

---

# 21. 最终资金/资产状态

成功闭环：

## 链上钱包

```text
W_AP_TEST

USDC:
减少 Token Buy 成本

AAPLx:
0
```

因为：

```text
Buy 后 +10
Redeem 时 -10
```

---

## Alpaca

```text
ALPACA_AP_TEST

AAPL:
0
```

因为：

```text
Short:
-10

Redeem Journal:
+10
```

---

## 策略利润

经济上：

```text
Stock Short Proceeds
-
Token Buy Cost
-
Fees
-
Gas
-
Borrow Cost
-
Stablecoin Cost
=
Net PnL
```

---

# 22. 我方应该监听什么来判断 Redeem 完成

不能仅仅判断：

```text
redeem_tx_hash confirmed
```

因为这只能证明：

```text
Token 已经送到 Issuer
```

不能证明：

```text
股票已经 Journal 到 Alpaca。
```

应该同时监听 Alpaca Tokenization Requests。

例如：

```text
GET /v1/accounts/{account_id}/tokenization/requests
```

关注：

```text
tokenization_request_id
type
status
underlying_symbol
token_symbol
qty
network
wallet_address
tx_hash
```

状态可能包括：

```text
pending
completed
rejected
```

---

# 23. 最严格的 Completed 条件

一笔套利真正标记：

```text
COMPLETED
```

建议必须满足两个条件：

```text
redeem_request.status == completed
```

并且：

```text
Alpaca AAPL Position
增加 Q 股
```

最终确认：

```text
position_after == expected_position
```

例如：

```text
Before Short:
0

After Short:
-10

After Redeem:
0
```

只有：

```text
AAPL == 0
```

才真正：

```text
PnL = REALIZED
Margin = RELEASED
Trade = COMPLETED
```

---

# 24. 一笔交易必须有统一 trade_id

真实系统里最重要的可观测性设计之一：

每次策略决定执行时立即创建：

```text
trade_id
```

例如：

```text
ARB-AAPLX-20260814-000001
```

下面所有 ID 都挂到这一个 Trade。

```text
trade_id
│
├── xstocks_quote_id
├── xstocks_soft_quote_id
│
├── alpaca_account_id
├── alpaca_short_order_id
├── alpaca_client_order_id
│
├── fireblocks_buy_tx_id
├── buy_tx_hash
│
├── payment_wallet
├── receiving_wallet
│
├── redemption_address
├── fireblocks_redeem_tx_id
├── redeem_tx_hash
│
├── issuer_request_id
├── alpaca_tokenization_request_id
│
└── final_position_check
```

这样出现问题时可以准确回答：

```text
这笔套利现在卡在哪一步？
```

---

# 25. 推荐的真实状态机

## 25.1 Opportunity

```text
opportunity_detected
```

---

## 25.2 RFQ

```text
rfq_requested
    ↓
rfq_received
    ↓
rfq_reserved
```

---

## 25.3 Stock

```text
short_order_created
    ↓
short_order_submitted
    ↓
short_order_filled
```

失败：

```text
short_rejected
short_partial_fill
short_cancelled
```

---

## 25.4 Token Buy

```text
token_buy_created
    ↓
token_buy_signed
    ↓
token_buy_broadcast
    ↓
token_buy_confirmed
    ↓
token_received
```

失败：

```text
rfq_expired
token_buy_sign_failed
token_buy_broadcast_failed
token_buy_chain_failed
token_buy_unknown
```

---

## 25.5 Redeem

```text
redeem_transfer_created
    ↓
redeem_transfer_signed
    ↓
redeem_tx_broadcast
    ↓
redeem_tx_confirmed
```

---

## 25.6 Issuer / Alpaca ITN

```text
issuer_redeem_detected
    ↓
alpaca_redeem_pending
    ↓
alpaca_redeem_completed
```

---

## 25.7 Final Settlement

```text
underlying_position_observed
    ↓
short_closed_by_journal
    ↓
trade_completed
```

---

# 26. Redeem 不应该只有一个 redeem_pending

真实测试中建议拆开：

```text
redeem_tx_pending
issuer_processing
alpaca_itn_pending
alpaca_journal_pending
completed
```

因为不同阶段的故障处理完全不同。

例如：

### Case A

```text
Redeem Tx 没上链
```

问题可能是：

```text
Fireblocks
Gas
Policy
Signature
RPC
```

---

### Case B

```text
Tx Confirmed
Issuer 没识别
```

问题可能是：

```text
Wrong Wallet
Wrong Token
Wrong Network
Wallet Mapping
Issuer Indexer
```

---

### Case C

```text
Issuer 已识别
Alpaca 仍 Pending
```

问题可能是：

```text
Issuer Callback
Alpaca ITN
Account Mapping
Journal
```

---

### Case D

```text
Alpaca Completed
但 Position 不正确
```

属于：

```text
Accounting / Reconciliation Incident
```

需要人工接管。

---

# 27. 真实测试必须记录的时间点

不要再依赖固定：

```text
500ms
1s
3.1s
4.83s
```

而应该记录真实事件时间。

建议：

```text
t0  opportunity_detected

t1  rfq_received

t2  short_order_submitted
t3  short_filled

t4  token_buy_tx_created
t5  token_buy_tx_broadcast
t6  token_buy_tx_confirmed
t7  token_balance_observed

t8  redeem_tx_created
t9  redeem_tx_broadcast
t10 redeem_tx_confirmed

t11 alpaca_redeem_pending_observed
t12 alpaca_redeem_completed

t13 underlying_position_observed
```

---

# 28. 最值得测量的两个风险窗口

## 28.1 股票裸空窗口

```text
short_filled
→
token_buy_confirmed
```

即：

```text
t3 → t6
```

这个窗口内：

```text
AAPL = -Q
AAPLx = 0
```

是整个策略最重要的短期执行风险。

---

## 28.2 Redeem Settlement Window

```text
redeem_tx_submitted
→
underlying_position_observed
```

即：

```text
t9 → t13
```

这个阶段虽然 Token Long + Stock Short 经济上已对冲，但：

```text
Margin
Borrow
Position
Settlement
```

仍然占用资源。

应分别统计：

```text
p50
p95
p99
max
```

---

# 29. 真实测试需要重点统计的 Latency

建议分别统计：

```text
RFQ Request → RFQ Received

Opportunity → Short Submit

Short Submit → Short Fill

Short Fill → Token Tx Broadcast

Token Tx Broadcast → Token Confirm

Token Confirm → Token Balance Observed

Token Received → Redeem Tx Broadcast

Redeem Broadcast → Redeem Confirm

Redeem Confirm → Alpaca Pending

Alpaca Pending → Alpaca Completed

Alpaca Completed → Position Observed
```

最终形成：

```text
Execution Latency Dashboard
```

---

# 30. Alpaca Sandbox 和 ITN 测试的关系

测试时应优先使用：

```text
Alpaca Broker Sandbox
```

而不是单纯独立的个人 Paper Account。

因为 Broker Sandbox 能：

```text
针对具体 account_id 下单
管理账户
测试 Journal
测试 Tokenization Requests
```

最理想情况是 Backed / xStocks UAT 能够直接把：

```text
BACKED_CLIENT_TEST
```

映射到：

```text
AP_ACCOUNT_ID_TEST
```

这样才能真正测试：

```text
AAPLx
→ Issuer
→ Alpaca ITN
→ AP Account
```

整个闭环。

---

# 31. 如果 Issuer UAT 暂时不能打通怎么办

如果 Backed / Issuer 暂时不能把测试 Redeem 真实连接到 Alpaca Sandbox，可以分两层测试。

## Layer 1：真实链上

真实测试：

```text
W_AP_TEST
→
XSTOCKS_REDEEM_TEST
```

验证：

```text
Token
Network
Wallet
tx_hash
confirmation
```

---

## Layer 2：证券侧仿真

在 Alpaca Broker Sandbox 中使用 Journal：

```text
Issuer Sandbox Account
→
ALPACA_AP_TEST
```

模拟：

```text
+Q AAPL
```

这样可以提前测试：

```text
Position Closing
Margin Release
PnL
Reconciliation
State Machine
```

但必须明确：

```text
这只是 Alpaca 侧 Settlement Simulation，
不等于真实 Issuer xPort 已经端到端打通。
```

---

# 32. 推荐的第一轮 UAT 顺序

不要第一天就启动完整自动套利机器人。

---

## UAT-01：Wallet Connectivity

验证：

```text
Fireblocks
→
External Wallet
```

测试：

```text
地址 whitelist
Policy
Sign
Broadcast
Confirm
```

---

## UAT-02：Token Receive

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

## UAT-03：Redeem Only

不做股票 Short。

直接：

```text
W_AP_TEST
AAPLx
   ↓
XSTOCKS_REDEEM_TEST
   ↓
Issuer
   ↓
Alpaca
   ↓
ALPACA_AP_TEST
+AAPL
```

这是最关键的一次测试。

---

## UAT-04：Short + Redeem

先：

```text
ALPACA_AP_TEST
Short 1 / 10 AAPL
```

再：

```text
Redeem 等量 AAPLx
```

最终确认：

```text
AAPL Position = 0
```

---

## UAT-05：xChange Buy + Redeem

测试：

```text
USDC
→
AAPLx
→
Redeem
→
AAPL
```

但不自动 Short。

---

## UAT-06：完整套利

最后才做：

```text
Realtime Edge
    ↓
RFQ
    ↓
Short
    ↓
xChange Buy
    ↓
Token Confirm
    ↓
Redeem
    ↓
Issuer
    ↓
Alpaca Journal
    ↓
Position = 0
```

---

# 33. 向 xStocks / Backed 必须确认的信息

需要拿到：

```text
Test / UAT Client ID
API Key / Authentication
xChange entitlement
xPort / ITN entitlement

Supported Test Network
Test Token Deployment

Registered Wallet API / Process
W_AP_TEST registration status

AAPLx Min Order
AAPLx Max Order
RFQ execution timeout

In-Kind Redemption Wallet

AP / Client
→
Alpaca Sandbox Account
Mapping

Redeem Request Status / Webhook
Issuer Callback Behavior
```

最关键的问题是：

```text
你们的 Test/UAT Client
能否和我们指定的 Alpaca Broker Sandbox AP Account
建立 ITN mapping？
```

---

# 34. 向 Alpaca 必须确认的信息

需要：

```text
Broker Sandbox Credentials

AP_ACCOUNT_ID_TEST

Trading API Access

AAPL Short Capability

ITN / Tokenization Enabled

Tokenization Request API

Backed Client / AP
→
Alpaca Account Mapping

Redeem 后 Underlying
是否 Journal 到这个同一个 Account
```

尤其确认：

```text
Short AAPL 的账户
是否就是 Redeem 股票最终进入的账户。
```

---

# 35. 向 Fireblocks 必须准备的信息

需要：

```text
Sandbox Workspace
API User
API Key
Co-signer / Signing Mode

Vault Account
W_AP_TEST

Stablecoin
AAPLx
Native Gas

Transaction Policy

Issuer Redemption Wallet Whitelist

xChange Contract Whitelist
（如适用）
```

---

# 36. 推荐配置结构

可以把测试配置做成：

```yaml
environment: uat

xstocks:
  client_id: BACKED_CLIENT_TEST
  api_base_url: ...
  api_key_env: XSTOCKS_API_KEY

  token:
    symbol: AAPLx
    underlying: AAPL

  network: TEST_NETWORK

  payment_wallet: W_AP_TEST
  receiving_wallet: W_AP_TEST

  redeem:
    sweeping_wallet_source: api
    static_address: null

alpaca:
  environment: sandbox
  account_id: AP_ACCOUNT_ID_TEST
  underlying_symbol: AAPL

fireblocks:
  environment: sandbox
  vault_account_id: FB_VAULT_ARB_01
  wallet_label: W_AP_TEST

  stablecoin: USDC
  token: AAPLx

strategy:
  token_qty: 10
  require_full_short_fill: true
  require_token_confirmation: true
  require_redeem_completed: true
  require_final_position_check: true
```

敏感信息不要写入配置文件：

```text
API Keys
Private Keys
Secret Keys
Signing Secrets
```

统一使用：

```text
Environment Variables
Secret Manager
```

---

# 37. Trade 数据结构建议

每笔套利至少保存：

```yaml
trade_id:

symbol:
token_symbol:
qty:

opportunity:
  detected_at:
  stock_bid:
  stock_ask:
  token_price:
  gross_edge_bps:
  expected_net_edge_bps:

xstocks:
  quote_id:
  price:
  expiration:
  network:

alpaca_short:
  account_id:
  order_id:
  submitted_at:
  filled_at:
  filled_qty:
  filled_avg_price:

token_buy:
  fireblocks_tx_id:
  tx_hash:
  wallet:
  broadcast_at:
  confirmed_at:
  token_received_at:

redeem:
  from_wallet:
  to_wallet:
  fireblocks_tx_id:
  tx_hash:
  broadcast_at:
  confirmed_at:

alpaca_redeem:
  tokenization_request_id:
  status:
  pending_at:
  completed_at:

final_position:
  expected:
  observed:
  checked_at:

pnl:
  stock_short_proceeds:
  token_cost:
  gas:
  borrow_cost:
  other_fees:
  gross_pnl:
  net_pnl:
```

---

# 38. 必须有的 Reconciliation

每笔 Trade 结束后至少做五项对账。

## 38.1 RFQ

```text
Quote Qty
=
Executed Token Qty
```

---

## 38.2 Token

```text
Token Received
=
Token Redeemed
```

---

## 38.3 Blockchain

```text
Redeem Tx
Asset / Qty / From / To / Network
全部正确
```

---

## 38.4 Alpaca

```text
Short Qty
=
Redeem Underlying Qty
```

---

## 38.5 Final Position

```text
Final Stock Position
=
Expected Position
```

套利闭环交易一般预期：

```text
0
```

---

# 39. 必须考虑的异常状态

真实系统不应继续假设 Redeem 永远成功。

至少支持：

```text
redeem_tx_failed

redeem_tx_confirmed_but_not_detected

issuer_processing_timeout

alpaca_redeem_rejected

alpaca_redeem_pending_too_long

journal_mismatch

underlying_qty_mismatch

final_position_mismatch

unknown_state
```

任何：

```text
unknown_state
```

都不应该自动重试链上转账，否则存在：

```text
Double Redeem
```

风险。

---

# 40. 幂等设计

所有外部操作必须有幂等保护。

至少：

```text
trade_id
quote_id
alpaca_client_order_id
fireblocks_transaction_id
redeem_tx_hash
issuer_request_id
tokenization_request_id
```

不能只依赖：

```text
status == timeout
```

就重新发送。

原则：

```text
Timeout ≠ Failure
```

尤其：

```text
Blockchain
Issuer
Alpaca Journal
```

三个系统之间可能出现：

```text
请求方超时
但对方已经成功执行
```

---

# 41. 真实环境最终完成判定

建议：

```text
IF

short_filled_qty == Q

AND

token_buy_confirmed == true

AND

redeem_tx_confirmed == true

AND

alpaca_redeem_status == completed

AND

final_underlying_position == expected_position

THEN

trade_status = completed
pnl_status   = realized
```

否则不能因为：

```text
Token 已经转给 Issuer
```

就提前记：

```text
Realized PnL
```

---

# 42. 测试完成后需要形成的监控

建议至少做：

```text
Open Trades

Unhedged Short Qty

Token Inventory

Redeem Pending Qty

Redeem Pending Age

Alpaca Short Position

Wallet Balance

Available Capital

RFQ Success Rate

Short Fill Rate

Token Buy Failure Rate

Redeem Completion Rate

Redeem p50 / p95 / p99

Final Position Mismatch Count

Realized PnL
```

最危险的 Dashboard 指标：

```text
Unhedged Short > 0

Redeem Pending Too Long

Final Position != Expected

Unknown State > 0
```

---

# 43. 最终测试环境的最简关系图

```text
              USDC
               │
               ▼
        ┌─────────────┐
        │  W_AP_TEST  │
        │ Fireblocks  │
        └──────┬──────┘
               │
         xChange Buy
               │
               ▼
           + AAPLx
               │
               │ Redeem
               ▼
   ┌───────────────────────┐
   │ XSTOCKS_REDEEM_TEST   │
   │ Issuer Redeem Wallet  │
   └───────────┬───────────┘
               │
               ▼
       xStocks / Issuer
               │
          Notify ITN
               ▼
   ┌───────────────────────┐
   │ ISSUER_ALPACA_ACCOUNT │
   └───────────┬───────────┘
               │
          Journal AAPL
               ▼
       ┌──────────────┐
       │ALPACA_AP_TEST│
       │   -10 AAPL   │
       │      +10     │
       │       = 0    │
       └──────────────┘
```

同时最开始：

```text
ALPACA_AP_TEST
      │
      └── Short AAPL
```

---

# 44. 我方真正控制的核心实体

整个 Redeem 流程中，我方最核心其实只有两个实体：

## 链上

```text
W_AP_TEST
```

负责：

```text
USDC payment
AAPLx receive
AAPLx redeem transfer
```

---

## 证券账户

```text
ALPACA_AP_TEST
```

负责：

```text
Short AAPL
Receive Redeemed AAPL
Close Short Position
```

---

中间：

```text
XSTOCKS_REDEEM_TEST
Issuer
Issuer Alpaca Account
Alpaca ITN
```

属于 Issuer / Infrastructure Settlement Rail。

---

# 45. 当前回测模型到真实测试模型的核心变化

当前回测：

```text
quote_reserved
    ↓
stock_filled
    ↓
rfq_buy_token
    ↓
token_received
    ↓
redeem_submitted
    ↓
redeem_completed
```

真实测试建议改成：

```text
opportunity_detected
    ↓
rfq_received
    ↓
rfq_reserved
    ↓
short_order_submitted
    ↓
short_filled
    ↓
token_buy_signed
    ↓
token_buy_broadcast
    ↓
token_buy_confirmed
    ↓
token_received
    ↓
redeem_transfer_signed
    ↓
redeem_tx_broadcast
    ↓
redeem_tx_confirmed
    ↓
issuer_redeem_detected
    ↓
alpaca_redeem_pending
    ↓
alpaca_redeem_completed
    ↓
underlying_position_observed
    ↓
trade_completed
```

---

# 46. 下一阶段实施目标

真实 UAT 的最终目标不是“跑出一个 completed”。

而是证明下面这条链每一环都可以被真实 ID 和真实回执验证：

```text
Realtime Quote
    ↓
xStocks Quote ID
    ↓
Alpaca Short Order ID
    ↓
Fireblocks Buy Transaction ID
    ↓
Buy TX Hash
    ↓
AAPLx Balance
    ↓
Fireblocks Redeem Transaction ID
    ↓
Redeem TX Hash
    ↓
Issuer / ITN Request
    ↓
Alpaca Tokenization Request ID
    ↓
AAPL Journal
    ↓
Final Position = 0
```

只有这条链完整跑通，才算真正从：

```text
Backtest / Shadow Execution
```

进入：

```text
End-to-End Real-Time UAT
```

---

# 47. 官方参考资料

以下为本设计中涉及的主要官方文档：

## Alpaca

Tokenization Guide for Authorized Participant：

https://docs.alpaca.markets/us/docs/tokenization-guide-for-authorized-participant

Broker Sandbox Create Order for Account：

https://docs.alpaca.markets/us/v1.1/reference/createorderforaccount

Tokenization Redeem Callback：

https://docs.alpaca.markets/reference/posttokenizationredeem

Get Tokenization Requests：

https://docs.alpaca.markets/us/reference/gettokenizationrequestsbroker

Tokenization Mint Broker：

https://docs.alpaca.markets/us/reference/posttokenizationmintbroker

---

## xStocks / Backed

Issuance and Redemption：

https://docs.xstocks.fi/docs/issuance-and-redemption

xChange Atomic RFQ：

https://docs.xstocks.fi/developers/xchange-atomic-rfq

Atomic RFQ / xChange：

https://docs.xstocks.fi/docs/issuance-and-redemption/atomic-rfq-xchange

In-Kind Flow / xPort：

https://docs.xstocks.fi/docs/issuance-and-redemption/in-kind-flow-xport

xStocks Changelog：

https://docs.xstocks.fi/changelog

---

## Fireblocks

Whitelisting Addresses：

https://developers.fireblocks.com/docs/whitelist-addresses

Create Vault Account：

https://developers.fireblocks.com/api-reference/vaults/create-a-new-vault-account

---

# 48. 一句话总结

第一版真实测试应围绕两个我方核心实体搭建：

```text
W_AP_TEST
+
ALPACA_AP_TEST
```

完整套利闭环：

```text
USDC
→
AAPLx

同时：

AAPL
→
Short

然后：

AAPLx
→
Issuer Redemption Wallet
→
Issuer
→
Alpaca ITN
→
AAPL Journal
→
ALPACA_AP_TEST

最终：

AAPL Position = 0
```

这才是当前 Token 折价 Redeem 套利模型在真实测试环境中的完整账户、地址和结算流程。
