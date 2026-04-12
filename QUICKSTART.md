# SyncMark Quick Start

## Prerequisites

| Component  | Version | Purpose                      |
|------------|---------|------------------------------|
| Redis      | 7+      | Stream message queue + cache |
| PostgreSQL | 15+     | Analyzer persistence         |
| Go         | 1.21+   | Collector service            |
| Python     | 3.11+   | Analyzer service             |

## 1. Infrastructure

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine

docker run -d --name postgres -p 5432:5432 \
  -e POSTGRES_USER=syncmark \
  -e POSTGRES_PASSWORD=syncmark \
  -e POSTGRES_DB=syncmark \
  postgres:15-alpine
```

## 2. Configuration

### Collector

Edit `collector/configs/collector.yaml`:

- `telegram.app_id` / `app_hash` / `phone` — get from [my.telegram.org](https://my.telegram.org)
- `chain.ethereum.rpc_ws` — replace with your Alchemy/Infura WebSocket URL
- `chain.solana.rpc_ws` — replace if using a private RPC
- `cex.symbols` — adjust trading pairs as needed

### Analyzer

Set the Anthropic API key:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Optionally edit `analyzer/configs/analyzer.yaml` to change database DSN, Redis URL, thresholds, etc.

## 3. Start Collector (Go)

```bash
cd collector
go mod tidy
go run ./cmd/collector/
```

Runs 4 modules in parallel:

- **Telegram Listener** — MTProto channel message subscription
- **CEX Manager** — Binance + OKX WebSocket (ticker, kline, large order detection)
- **Chain Monitor** — ETH + SOL whale transfers and smart money tracking
- **Macro Scheduler** — Economic calendar sync, publish polling, dashboard refresh

All data is published to Redis Streams.

> **Note:** Telegram requires interactive verification code on first login — the terminal will prompt you.

## 4. Start Analyzer (Python)

```bash
cd analyzer
pip install -e .
syncmark-analyzer
```

Or run directly:

```bash
python -m analyzer.main
```

Runs:

- 4 Redis Stream consumers (telegram, macro, large order, whale) with consumer groups + DLQ
- FastAPI server on `0.0.0.0:8081`
- AI Q&A endpoint: `POST /analyze/ask`

## 5. Verify

### Swagger UI

```
http://localhost:8081/docs
```

### AI Q&A

```bash
curl -X POST http://localhost:8081/analyze/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "BTC 最近有什么大额转账?"}'
```

### Manual Test Data

If you want to test the analyzer without running the collector, push test data directly to Redis Streams:

```bash
# Telegram message
redis-cli XADD telegram:raw_messages '*' \
  channel_id 123 channel_name test message_id 1 \
  text "BTC突破10万美元" media_type none telegram_date "2026-04-12T00:00:00Z"

# Large order
redis-cli XADD cex:large_orders '*' \
  exchange binance symbol BTCUSDT side buy \
  price 100000 quantity 15 value_usd 1500000 \
  timestamp "2026-04-12T00:00:00Z"

# Whale transfer
redis-cli XADD chain:whale_transfers '*' \
  chain ethereum tx_hash 0xabc123 \
  from_address 0xdead from_label "Whale A" \
  to_address 0xbeef to_label "Binance" \
  token ETH amount 5000 value_usd 15000000 \
  timestamp "2026-04-12T00:00:00Z"

# Economic event
redis-cli XADD macro:economic_events '*' \
  event_id nfp-2026-04 name "Non-Farm Payrolls" \
  country US importance high \
  scheduled_at "2026-04-12T12:30:00Z" \
  previous 150K forecast 160K actual "" \
  status scheduled
```

## Architecture

```
Telegram ─┐
Binance  ─┤                              ┌─ news_analyzed ────┐
OKX      ─┤  collector   Redis Streams   │  economic_analyzed │  api-server
ETH Node ─┼──(Go)────►  ═══════════  ►───┤  large_order_alert ├──►  (WS push)
SOL Node ─┤              analyzer(Py)    │  whale_alert ──────┘
Macro API ─┘              + Claude AI    │
                                         └─ POST /analyze/ask (sync Q&A)
```
