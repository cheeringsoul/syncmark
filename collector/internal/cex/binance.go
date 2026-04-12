package cex

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/gorilla/websocket"

	"github.com/ymy/syncmark/collector/internal/config"
	"github.com/ymy/syncmark/collector/internal/model"
	"github.com/ymy/syncmark/collector/internal/stream"
)

const binanceWSBase = "wss://stream.binance.com:9443/stream?streams="

// BinanceWS manages a Binance WebSocket connection.
type BinanceWS struct {
	cfg       config.CEXConfig
	publisher *stream.Publisher
}

func NewBinanceWS(cfg config.CEXConfig, pub *stream.Publisher) *BinanceWS {
	return &BinanceWS{cfg: cfg, publisher: pub}
}

// Connect establishes the Binance combined stream WebSocket and dispatches messages.
//
// @bodhi.intent Connect to Binance WebSocket combined stream, dispatch ticker/kline/trade messages
// @bodhi.reads config(cex.symbols, cex.kline_intervals)
// @bodhi.calls handleTicker
// @bodhi.calls handleKline
// @bodhi.calls handleTrade
// @bodhi.on_fail ws_disconnect → reconnect with backoff
func (b *BinanceWS) Connect(ctx context.Context) error {
	url := b.buildStreamURL()

	for {
		if err := b.connectAndListen(ctx, url); err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			slog.Warn("binance ws disconnected, reconnecting", "error", err)
			time.Sleep(3 * time.Second)
			continue
		}
		return nil
	}
}

func (b *BinanceWS) buildStreamURL() string {
	var streams []string
	for _, sym := range b.cfg.Symbols {
		s := strings.ToLower(sym)
		streams = append(streams, s+"@ticker")
		streams = append(streams, s+"@aggTrade")
		for _, interval := range b.cfg.KlineIntervals {
			streams = append(streams, s+"@kline_"+interval)
		}
	}
	return binanceWSBase + strings.Join(streams, "/")
}

func (b *BinanceWS) connectAndListen(ctx context.Context, url string) error {
	conn, _, err := websocket.DefaultDialer.DialContext(ctx, url, nil)
	if err != nil {
		return fmt.Errorf("dial: %w", err)
	}
	defer conn.Close()

	slog.Info("binance ws connected", "symbols", b.cfg.Symbols)

	for {
		select {
		case <-ctx.Done():
			return nil
		default:
		}

		_, data, err := conn.ReadMessage()
		if err != nil {
			return fmt.Errorf("read: %w", err)
		}

		var wrapper struct {
			Stream string          `json:"stream"`
			Data   json.RawMessage `json:"data"`
		}
		if err := json.Unmarshal(data, &wrapper); err != nil {
			slog.Warn("binance unmarshal wrapper", "error", err)
			continue
		}

		switch {
		case strings.HasSuffix(wrapper.Stream, "@ticker"):
			b.handleTicker(ctx, wrapper.Data)
		case strings.Contains(wrapper.Stream, "@kline_"):
			b.handleKline(ctx, wrapper.Data)
		case strings.HasSuffix(wrapper.Stream, "@aggTrade"):
			b.handleTrade(ctx, wrapper.Data)
		}
	}
}

// handleTicker processes a Binance 24hr ticker update and caches it in Redis.
//
// @bodhi.intent Process Binance ticker update, write to Redis cache
// @bodhi.reads ws.message(symbol, price, change_24h, volume_24h, high_24h, low_24h)
// @bodhi.writes redis:ticker:binance:{symbol}(price, change_24h, volume_24h, high_24h, low_24h, updated_at) via SET
func (b *BinanceWS) handleTicker(ctx context.Context, data json.RawMessage) {
	var raw struct {
		Symbol    string `json:"s"`
		LastPrice string `json:"c"`
		PriceChg  string `json:"P"`
		Volume    string `json:"v"`
		High      string `json:"h"`
		Low       string `json:"l"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		slog.Warn("binance ticker unmarshal", "error", err)
		return
	}

	ticker := model.Ticker{
		Exchange:  "binance",
		Symbol:    raw.Symbol,
		Price:     raw.LastPrice,
		Change24h: raw.PriceChg + "%",
		Volume24h: raw.Volume,
		High24h:   raw.High,
		Low24h:    raw.Low,
		UpdatedAt: time.Now(),
	}

	key := fmt.Sprintf("ticker:binance:%s", raw.Symbol)
	if err := b.publisher.SetHashFromJSON(ctx, key, ticker); err != nil {
		slog.Warn("binance ticker cache write", "symbol", raw.Symbol, "error", err)
	}
}

// handleKline processes a Binance kline candle and publishes to Redis Stream.
//
// @bodhi.intent Process Binance kline candle, publish to stream for DB persistence
// @bodhi.reads ws.message(symbol, interval, open, high, low, close, volume, open_time, close_time)
// @bodhi.emits cex_kline(exchange, symbol, interval, open, high, low, close, volume, quote_volume, open_time, close_time) to redis:cex:klines
func (b *BinanceWS) handleKline(ctx context.Context, data json.RawMessage) {
	var raw struct {
		Symbol string `json:"s"`
		Kline  struct {
			Interval    string `json:"i"`
			Open        string `json:"o"`
			High        string `json:"h"`
			Low         string `json:"l"`
			Close       string `json:"c"`
			Volume      string `json:"v"`
			QuoteVolume string `json:"q"`
			OpenTime    int64  `json:"t"`
			CloseTime   int64  `json:"T"`
			IsClosed    bool   `json:"x"`
		} `json:"k"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		slog.Warn("binance kline unmarshal", "error", err)
		return
	}

	// Only publish closed candles.
	if !raw.Kline.IsClosed {
		return
	}

	kline := model.Kline{
		Exchange:    "binance",
		Symbol:      raw.Symbol,
		Interval:    raw.Kline.Interval,
		Open:        raw.Kline.Open,
		High:        raw.Kline.High,
		Low:         raw.Kline.Low,
		Close:       raw.Kline.Close,
		Volume:      raw.Kline.Volume,
		QuoteVolume: raw.Kline.QuoteVolume,
		OpenTime:    time.UnixMilli(raw.Kline.OpenTime),
		CloseTime:   time.UnixMilli(raw.Kline.CloseTime),
	}

	if err := b.publisher.Publish(ctx, stream.CEXKlines, kline); err != nil {
		slog.Warn("binance kline publish", "symbol", raw.Symbol, "error", err)
	}
}

// handleTrade processes a Binance aggregate trade and detects large orders.
//
// @bodhi.intent Process Binance trade, detect large orders by USD threshold
// @bodhi.reads ws.message(symbol, price, quantity, side, timestamp)
// @bodhi.reads config(cex.large_order_threshold_usd)
// @bodhi.emits cex_large_order(exchange, symbol, side, price, quantity, value_usd, timestamp) to redis:cex:large_orders
// @bodhi.on_fail threshold_check → skip (not large enough)
func (b *BinanceWS) handleTrade(ctx context.Context, data json.RawMessage) {
	var raw struct {
		Symbol   string `json:"s"`
		Price    string `json:"p"`
		Quantity string `json:"q"`
		IsBuyer  bool   `json:"m"` // true = seller is maker → taker is buyer
		Time     int64  `json:"T"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		slog.Warn("binance trade unmarshal", "error", err)
		return
	}

	price := parseFloat(raw.Price)
	qty := parseFloat(raw.Quantity)
	valueUSD := price * qty

	if valueUSD < b.cfg.LargeOrderThresholdUSD {
		return
	}

	side := "sell"
	if raw.IsBuyer {
		side = "buy"
	}

	order := model.LargeOrder{
		Exchange:  "binance",
		Symbol:    raw.Symbol,
		Side:      side,
		Price:     price,
		Quantity:  qty,
		ValueUSD:  valueUSD,
		Timestamp: time.UnixMilli(raw.Time),
	}

	if err := b.publisher.Publish(ctx, stream.CEXLargeOrders, order); err != nil {
		slog.Warn("binance large order publish", "symbol", raw.Symbol, "error", err)
	}

	slog.Info("large order detected",
		"exchange", "binance", "symbol", raw.Symbol,
		"side", side, "value_usd", valueUSD)
}
