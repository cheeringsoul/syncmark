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

const okxWSPublic = "wss://ws.okx.com:8443/ws/v5/public"

// OkxWS manages an OKX WebSocket connection.
type OkxWS struct {
	cfg       config.CEXConfig
	publisher *stream.Publisher
}

func NewOkxWS(cfg config.CEXConfig, pub *stream.Publisher) *OkxWS {
	return &OkxWS{cfg: cfg, publisher: pub}
}

// Connect establishes the OKX WebSocket and subscribes to market data channels.
//
// @bodhi.intent Connect to OKX WebSocket, subscribe to ticker/kline/trade channels
// @bodhi.reads config(cex.symbols, cex.kline_intervals)
// @bodhi.calls handleTicker
// @bodhi.calls handleKline
// @bodhi.calls handleTrade
// @bodhi.on_fail ws_disconnect → reconnect with backoff
func (o *OkxWS) Connect(ctx context.Context) error {
	for {
		if err := o.connectAndListen(ctx); err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			slog.Warn("okx ws disconnected, reconnecting", "error", err)
			time.Sleep(3 * time.Second)
			continue
		}
		return nil
	}
}

func (o *OkxWS) connectAndListen(ctx context.Context) error {
	conn, _, err := websocket.DefaultDialer.DialContext(ctx, okxWSPublic, nil)
	if err != nil {
		return fmt.Errorf("dial: %w", err)
	}
	defer conn.Close()

	if err := o.subscribe(conn); err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}

	slog.Info("okx ws connected", "symbols", o.cfg.Symbols)

	// OKX requires ping every 30s.
	go o.keepAlive(ctx, conn)

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

		// OKX sends "pong" as plain text.
		if string(data) == "pong" {
			continue
		}

		var msg struct {
			Arg struct {
				Channel string `json:"channel"`
				InstID  string `json:"instId"`
			} `json:"arg"`
			Data []json.RawMessage `json:"data"`
		}
		if err := json.Unmarshal(data, &msg); err != nil {
			continue
		}

		if len(msg.Data) == 0 {
			continue
		}

		for _, d := range msg.Data {
			switch {
			case msg.Arg.Channel == "tickers":
				o.handleTicker(ctx, msg.Arg.InstID, d)
			case strings.HasPrefix(msg.Arg.Channel, "candle"):
				interval := strings.TrimPrefix(msg.Arg.Channel, "candle")
				o.handleKline(ctx, msg.Arg.InstID, interval, d)
			case msg.Arg.Channel == "trades":
				o.handleTrade(ctx, msg.Arg.InstID, d)
			}
		}
	}
}

func (o *OkxWS) subscribe(conn *websocket.Conn) error {
	var args []map[string]string
	for _, sym := range o.cfg.Symbols {
		instID := o.toOkxInstID(sym)
		args = append(args, map[string]string{"channel": "tickers", "instId": instID})
		args = append(args, map[string]string{"channel": "trades", "instId": instID})
		for _, interval := range o.cfg.KlineIntervals {
			args = append(args, map[string]string{"channel": "candle" + o.toOkxInterval(interval), "instId": instID})
		}
	}

	sub := map[string]interface{}{
		"op":   "subscribe",
		"args": args,
	}
	return conn.WriteJSON(sub)
}

func (o *OkxWS) keepAlive(ctx context.Context, conn *websocket.Conn) {
	ticker := time.NewTicker(25 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := conn.WriteMessage(websocket.TextMessage, []byte("ping")); err != nil {
				return
			}
		}
	}
}

// toOkxInstID converts "BTCUSDT" to "BTC-USDT".
func (o *OkxWS) toOkxInstID(symbol string) string {
	if strings.HasSuffix(symbol, "USDT") {
		base := strings.TrimSuffix(symbol, "USDT")
		return base + "-USDT"
	}
	return symbol
}

// toOkxInterval converts Binance-style intervals to OKX format.
func (o *OkxWS) toOkxInterval(interval string) string {
	switch interval {
	case "1m":
		return "1m"
	case "5m":
		return "5m"
	case "15m":
		return "15m"
	case "1h":
		return "1H"
	case "4h":
		return "4H"
	case "1d":
		return "1D"
	default:
		return interval
	}
}

// handleTicker processes an OKX ticker update and caches it in Redis.
//
// @bodhi.intent Process OKX ticker update, write to Redis cache
// @bodhi.reads ws.message(symbol, price, change_24h, volume_24h, high_24h, low_24h)
// @bodhi.writes redis:ticker:okx:{symbol}(price, change_24h, volume_24h, high_24h, low_24h, updated_at) via SET
func (o *OkxWS) handleTicker(ctx context.Context, instID string, data json.RawMessage) {
	var raw struct {
		Last      string `json:"last"`
		Open24h   string `json:"open24h"`
		High24h   string `json:"high24h"`
		Low24h    string `json:"low24h"`
		VolCcy24h string `json:"volCcy24h"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		slog.Warn("okx ticker unmarshal", "error", err)
		return
	}

	last := parseFloat(raw.Last)
	open := parseFloat(raw.Open24h)
	var changePct float64
	if open > 0 {
		changePct = (last - open) / open * 100
	}

	symbol := strings.ReplaceAll(instID, "-", "")
	ticker := model.Ticker{
		Exchange:  "okx",
		Symbol:    symbol,
		Price:     raw.Last,
		Change24h: fmt.Sprintf("%.2f%%", changePct),
		Volume24h: raw.VolCcy24h,
		High24h:   raw.High24h,
		Low24h:    raw.Low24h,
		UpdatedAt: time.Now(),
	}

	key := fmt.Sprintf("ticker:okx:%s", symbol)
	if err := o.publisher.SetHashFromJSON(ctx, key, ticker); err != nil {
		slog.Warn("okx ticker cache write", "symbol", symbol, "error", err)
	}
}

// handleKline processes an OKX kline candle and publishes to Redis Stream.
//
// @bodhi.intent Process OKX kline candle, publish to stream
// @bodhi.reads ws.message(symbol, interval, open, high, low, close, volume, open_time, close_time)
// @bodhi.emits cex_kline(exchange, symbol, interval, open, high, low, close, volume, quote_volume, open_time, close_time) to redis:cex:klines
func (o *OkxWS) handleKline(ctx context.Context, instID string, interval string, data json.RawMessage) {
	// OKX candle data is an array: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
	var raw []string
	if err := json.Unmarshal(data, &raw); err != nil {
		slog.Warn("okx kline unmarshal", "error", err)
		return
	}
	if len(raw) < 9 {
		return
	}

	// Only publish confirmed candles.
	if raw[8] != "1" {
		return
	}

	ts := parseInt64(raw[0])
	symbol := strings.ReplaceAll(instID, "-", "")

	kline := model.Kline{
		Exchange:    "okx",
		Symbol:      symbol,
		Interval:    interval,
		Open:        raw[1],
		High:        raw[2],
		Low:         raw[3],
		Close:       raw[4],
		Volume:      raw[5],
		QuoteVolume: raw[7],
		OpenTime:    time.UnixMilli(ts),
		CloseTime:   time.UnixMilli(ts), // OKX doesn't provide close_time separately
	}

	if err := o.publisher.Publish(ctx, stream.CEXKlines, kline); err != nil {
		slog.Warn("okx kline publish", "symbol", symbol, "error", err)
	}
}

// handleTrade processes an OKX trade and detects large orders.
//
// @bodhi.intent Process OKX trade, detect large orders
// @bodhi.reads ws.message(symbol, price, quantity, side, timestamp)
// @bodhi.reads config(cex.large_order_threshold_usd)
// @bodhi.emits cex_large_order(exchange, symbol, side, price, quantity, value_usd, timestamp) to redis:cex:large_orders
func (o *OkxWS) handleTrade(ctx context.Context, instID string, data json.RawMessage) {
	var raw struct {
		Price string `json:"px"`
		Size  string `json:"sz"`
		Side  string `json:"side"`
		TS    string `json:"ts"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		slog.Warn("okx trade unmarshal", "error", err)
		return
	}

	price := parseFloat(raw.Price)
	qty := parseFloat(raw.Size)
	valueUSD := price * qty

	if valueUSD < o.cfg.LargeOrderThresholdUSD {
		return
	}

	symbol := strings.ReplaceAll(instID, "-", "")
	ts := parseInt64(raw.TS)

	order := model.LargeOrder{
		Exchange:  "okx",
		Symbol:    symbol,
		Side:      raw.Side,
		Price:     price,
		Quantity:  qty,
		ValueUSD:  valueUSD,
		Timestamp: time.UnixMilli(ts),
	}

	if err := o.publisher.Publish(ctx, stream.CEXLargeOrders, order); err != nil {
		slog.Warn("okx large order publish", "symbol", symbol, "error", err)
	}

	slog.Info("large order detected",
		"exchange", "okx", "symbol", symbol,
		"side", raw.Side, "value_usd", valueUSD)
}

func parseInt64(s string) int64 {
	var v int64
	fmt.Sscanf(s, "%d", &v)
	return v
}
