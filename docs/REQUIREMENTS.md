# SyncMark — 后端需求文档

## 项目概述

SyncMark 是一个加密货币综合信息平台，聚合多源实时数据（Telegram、CEX 行情、链上数据、宏观经济指标），通过 AI 分析后提供给 iOS
客户端。

## 系统架构

```
┌─────────────── 数据采集层 (Go) ───────────────┐
│                                                │
│  Telegram MTProto ──┐                          │
│  Binance WebSocket ─┤                          │
│  OKX WebSocket ─────┤──→ Redis Stream          │
│  链上数据 RPC ───────┤                          │
│  经济指标抓取 ───────┘                          │
│                                                │
└────────────────────┬───────────────────────────┘
                     │
                     ▼
┌─────────────── 分析层 (Python) ────────────────┐
│                                                │
│  消费 Redis Stream → 清洗/聚合 → AI 分析       │
│  → 结果写入 DB / 推送通知                      │
│                                                │
└────────────────────┬───────────────────────────┘
                     │
                     ▼
┌─────────────── API 层 (Go) ───────────────────┐
│                                                │
│  REST API — 历史数据、AI 解读、经济日历        │
│  WebSocket — 实时行情、快讯推送、大单监控      │
│                                                │
└────────────────────┬───────────────────────────┘
                     │
                     ▼
               iOS App (SwiftUI)
```

## 技术选型

| 层      | 技术           | 说明                      |
|--------|--------------|-------------------------|
| 数据采集   | Go           | 长连接稳定，并发模型适合多数据源        |
| AI 分析  | Python       | LLM SDK 生态成熟            |
| API 服务 | Go           | 与采集层同语言，统一部署            |
| 消息队列   | Redis Stream | 轻量，初期够用，后期可换 NATS/Kafka |
| 主数据库   | PostgreSQL   | 结构化存储（新闻、指标、分析结果）       |
| 缓存     | Redis        | 实时行情、热数据缓存              |
| 推送     | APNs         | iOS 远程推送                |

## 模块一：Telegram 消息监听

### 功能需求

- 通过 MTProto 协议以用户账号身份监听指定群组/频道
- 支持配置监听目标列表（群组 ID / 频道 username）
- 实时接收文本消息、图片、文件等内容
- 断线自动重连，session 持久化

### 技术方案

- Go 库：`gotd/td`（完整 MTProto 实现）
- 消息写入 Redis Stream `telegram:messages`

### 数据结构

```json
{
  "source": "telegram",
  "channel_id": -1001234567890,
  "channel_name": "CryptoNews",
  "message_id": 12345,
  "text": "消息内容",
  "media_type": "photo|video|document|none",
  "media_url": "...",
  "timestamp": "2026-04-10T14:32:00Z"
}
```

## 模块二：CEX 实时行情

### 功能需求

- 监听 Binance、OKX WebSocket 行情数据
- 支持的数据类型：
    - **Ticker** — 实时价格、24h 涨跌幅、成交量
    - **K 线** — 1m/5m/15m/1h/4h/1d
    - **深度** — 买卖盘口 Top 20
    - **成交** — 逐笔成交（用于大单监控）
    - **资金费率** — 合约资金费率
- 多所价差计算（同币种跨交易所价格对比）
- 大单检测（单笔成交超过阈值自动标记）

### 技术方案

- Go 库：`gorilla/websocket`
- 每个交易所一个 WebSocket 管理器，内部按订阅 topic 复用连接
- Ticker 数据写入 Redis（覆盖写，保留最新）
- 大单事件写入 Redis Stream `cex:large_orders`
- K 线数据写入 PostgreSQL

### 数据结构

**Ticker（Redis Hash）**

```
key: ticker:{exchange}:{symbol}
fields:
  price: "67432.50"
  change_24h: "+2.4%"
  volume_24h: "12345.67"
  high_24h: "68000.00"
  low_24h: "65800.00"
  updated_at: "2026-04-10T14:32:00Z"
```

**大单事件**

```json
{
  "source": "binance",
  "symbol": "BTCUSDT",
  "side": "sell",
  "price": 67432.5,
  "quantity": 31.2,
  "value_usd": 2103894,
  "timestamp": "2026-04-10T14:32:00Z"
}
```

**多所价差**

```json
{
  "symbol": "BTCUSDT",
  "prices": {
    "binance": 67432.50,
    "okx": 67445.00
  },
  "max_spread": 12.50,
  "spread_pct": 0.019,
  "is_abnormal": false,
  "timestamp": "2026-04-10T14:32:00Z"
}
```

## 模块三：链上数据监听

### 功能需求

- **巨鲸追踪** — 监控标记地址的大额转账
- **交易所流入流出** — 监控交易所热钱包的 Token 流动
- **Gas 费 & 网络状态** — ETH Gas、活跃地址数、待处理交易
- **DeFi 数据** — TVL、DEX 交易量、稳定币流动
- **聪明钱追踪** — 标记地址的买卖动向

### 支持链

- 初期：Ethereum、Solana
- 后续可扩展：BSC、Arbitrum、Base

### 技术方案

- EVM 链：Go `go-ethereum` 库，WebSocket 订阅 logs + pending tx
- Solana：RPC WebSocket 订阅
- DeFi 聚合数据：接入 DefiLlama API
- 地址标签库：自建 + 接入 Arkham / Nansen 公开标签

### 数据结构

**巨鲸转账事件**

```json
{
  "chain": "ethereum",
  "tx_hash": "0xabc...",
  "from": "0x1a2b...3c4d",
  "from_label": "Jump Trading",
  "to": "0x5e6f...7g8h",
  "to_label": "Binance Hot Wallet",
  "token": "ETH",
  "amount": 5000,
  "value_usd": 15680000,
  "timestamp": "2026-04-10T14:20:00Z"
}
```

## 模块四：宏观经济指标

### 功能需求

- **经济日历** — CPI、非农、利率决议、PMI 等重要经济数据的发布时间
- **实时数据更新** — 数据公布后自动抓取实际值
- **关键指标仪表盘** — 美元指数、10Y 美债收益率、恐贪指数、CME 降息概率
- **数据公布提醒** — 重要数据公布前推送通知

### 数据源

- 经济日历：Investing.com / TradingEconomics / 金十数据 爬虫或 API
- 美元指数/美债：交易所 API 或财经数据接口
- 恐贪指数：Alternative.me API
- CME 降息概率：CME FedWatch 数据

### 技术方案

- Go 定时任务抓取经济日历（每日更新）
- 数据公布窗口期加密轮询（如 CPI 公布前后 5 分钟，每 10 秒检查）
- 指标仪表盘数据写入 Redis，定时刷新
- 经济日历存入 PostgreSQL

### 数据结构

**经济事件**

```json
{
  "event_id": "us_cpi_202604",
  "name": "美国 CPI (月率)",
  "country": "US",
  "importance": "high",
  "scheduled_at": "2026-04-10T20:30:00Z",
  "previous": "0.4%",
  "forecast": "0.3%",
  "actual": "0.2%",
  "status": "published",
  "ai_analysis": "通胀降温，利好风险资产..."
}
```

## 模块五：AI 分析层

### 功能需求

- **快讯 AI 解读** — 每条 Telegram 快讯自动生成一句话解读 + 多空标签 + 关联币种
- **经济指标解读** — 数据公布后自动生成影响分析
- **综合问答** — 用户提问时综合多源数据给出分析
- **技术面点评** — 基于 K 线数据给出技术分析观点

### 技术方案

- Python 消费 Redis Stream，调用 Claude API / OpenAI API
- 分析结果写入 PostgreSQL，关联原始消息 ID
- 综合问答：Python 服务暴露 HTTP API，Go API 层转发

### 分析流程

```
Telegram 消息 → 分类（是否为快讯）→ 提取关键信息
  → AI 生成解读（多空判断 + 影响币种 + 一句话总结）
  → 写入 DB → 推送到客户端

经济数据公布 → 提取实际值 vs 预期值
  → AI 生成影响分析（对加密市场的影响）
  → 写入 DB → 推送到客户端

用户提问 → 聚合相关数据（行情/链上/新闻/指标）
  → 组装 Prompt → AI 生成综合分析
  → 返回客户端
```

### AI Prompt 策略

- 快讯解读：限制 100 字内，结构化输出（JSON）
- 指标解读：限制 200 字内，必须包含对加密市场的影响判断
- 综合问答：上下文注入最近 24h 关键数据，限制 500 字内

## 模块六：API 层

### REST API

| 接口                        | 方法   | 说明                 |
|---------------------------|------|--------------------|
| `/api/news`               | GET  | 快讯列表（分页、筛选）        |
| `/api/news/:id`           | GET  | 快讯详情 + AI 解读       |
| `/api/calendar`           | GET  | 经济日历               |
| `/api/calendar/dashboard` | GET  | 关键指标仪表盘            |
| `/api/market/tickers`     | GET  | 所有 Ticker 快照       |
| `/api/market/:symbol`     | GET  | 单币种详情（K线、深度）       |
| `/api/market/spread`      | GET  | 多所价差               |
| `/api/chain/whales`       | GET  | 巨鲸转账记录             |
| `/api/chain/overview`     | GET  | 链上概览（Gas、TVL、活跃地址） |
| `/api/chain/smart-money`  | GET  | 聪明钱动向              |
| `/api/ai/ask`             | POST | AI 综合问答            |

### WebSocket

| Channel                     | 说明           |
|-----------------------------|--------------|
| `ws://host/ws/tickers`      | 实时 Ticker 推送 |
| `ws://host/ws/news`         | 实时快讯推送       |
| `ws://host/ws/large-orders` | 大单监控推送       |
| `ws://host/ws/whales`       | 巨鲸转账推送       |

## 非功能需求

### 性能

- Ticker 推送延迟 < 500ms（从交易所到客户端）
- 快讯 AI 解读延迟 < 10s（从消息到解读完成）
- API 响应时间 P99 < 200ms（非 AI 接口）

### 可靠性

- 所有 WebSocket 连接支持断线自动重连
- Telegram session 持久化，重启不丢失登录状态
- 采集服务挂掉后自动恢复，消息队列保证不丢数据

### 部署

- 初期：单机 Docker Compose（Go 服务 + Python 服务 + Redis + PostgreSQL）
- 后期：按模块拆分，独立扩缩容

### 监控

- 各数据源连接状态监控
- 消息队列堆积告警
- AI 分析延迟和失败率监控
- 交易所 WebSocket 断连次数统计
