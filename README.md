# SyncMark

Crypto intelligence platform that aggregates real-time data from multiple sources — Telegram channels, centralized exchanges, on-chain activity, and macroeconomic indicators — processes it through AI analysis, and delivers actionable insights to iOS clients via REST API and WebSocket.

## Architecture

```
┌─────────────── Collector (Go) ────────────────┐
│                                                │
│  Telegram MTProto ──┐                          │
│  Binance WebSocket ─┤                          │
│  OKX WebSocket ─────┤──→ Redis Stream          │
│  On-chain RPC ──────┤                          │
│  Macro Data ────────┘                          │
│                                                │
└────────────────────┬───────────────────────────┘
                     │
                     ▼
┌─────────────── Analyzer (Python) ─────────────┐
│                                                │
│  Redis Stream → Clean/Aggregate → AI Analysis  │
│  → Write DB / Push Notification                │
│                                                │
└────────────────────┬───────────────────────────┘
                     │
                     ▼
┌─────────────── API Server (Go) ───────────────┐
│                                                │
│  REST API — News, Calendar, Market, Chain      │
│  WebSocket — Tickers, News, Large Orders       │
│                                                │
└────────────────────┬───────────────────────────┘
                     │
                     ▼
               iOS App (SwiftUI)
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Collector | Go, gotd/td, gorilla/websocket, go-ethereum |
| Analyzer | Python, FastAPI, SQLAlchemy, Claude/OpenAI API |
| API Server | Go, Gin, gorilla/websocket |
| Message Queue | Redis Stream |
| Database | PostgreSQL |
| Cache | Redis |
| Push | APNs |

## Data Sources

- **Telegram** — Channel/group messages via MTProto
- **CEX** — Binance & OKX real-time tickers, K-lines, depth, trades, funding rates
- **On-chain** — Whale transfers, exchange flows, gas, DeFi TVL, smart money (Ethereum, Solana)
- **Macro** — Economic calendar, USD index, 10Y treasury yield, Fear & Greed index, CME FedWatch

## Getting Started

```bash
# Clone
git clone git@github.com:cheeringsoul/syncmark.git
cd syncmark

# Start infrastructure
docker compose up -d redis postgres

# Run services (see each service's README for details)
```

## Project Structure

```
syncmark/
├── collector/          # Go — data collection service
├── analyzer/           # Python — AI analysis service
├── api-server/         # Go — REST & WebSocket API
├── .bodhi/             # Bodhi DSL metadata
├── docs/               # Requirements & design docs
└── deploy/             # Docker & deployment configs
```

## License

Private — All rights reserved.
