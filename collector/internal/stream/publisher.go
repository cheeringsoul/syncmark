package stream

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/redis/go-redis/v9"
	"github.com/ymy/syncmark/collector/internal/config"
)

// Stream names used by all collectors.
const (
	TelegramRawMessages = "telegram:raw_messages"
	CEXKlines           = "cex:klines"
	CEXLargeOrders      = "cex:large_orders"
	ChainWhaleTransfers = "chain:whale_transfers"
	ChainSmartMoney     = "chain:smart_money"
	MacroEconomicEvents = "macro:economic_events"
)

// Publisher wraps a Redis client for stream and cache operations.
type Publisher struct {
	rdb *redis.Client
}

// NewPublisher creates a Publisher connected to Redis.
func NewPublisher(cfg config.RedisConfig) *Publisher {
	rdb := redis.NewClient(&redis.Options{
		Addr:     cfg.Addr,
		Password: cfg.Password,
		DB:       cfg.DB,
	})
	return &Publisher{rdb: rdb}
}

// Publish adds a JSON-encoded message to the given Redis Stream.
//
// @bodhi.intent Publish structured event to Redis Stream
// @bodhi.writes redis:stream(data) via XADD
// @bodhi.on_fail marshal_error → return error
// @bodhi.on_fail xadd_error → return error
func (p *Publisher) Publish(ctx context.Context, stream string, data any) error {
	payload, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("marshal: %w", err)
	}
	return p.rdb.XAdd(ctx, &redis.XAddArgs{
		Stream: stream,
		Values: map[string]interface{}{"data": string(payload)},
	}).Err()
}

// SetHash writes fields to a Redis Hash key.
//
// @bodhi.intent Write key-value fields to Redis Hash for cache
// @bodhi.writes redis:hash(fields) via HSET
func (p *Publisher) SetHash(ctx context.Context, key string, fields map[string]interface{}) error {
	return p.rdb.HSet(ctx, key, fields).Err()
}

// SetHashFromJSON marshals data to flat JSON fields and writes to a Redis Hash.
//
// @bodhi.intent Serialize struct to Redis Hash fields
// @bodhi.writes redis:hash(fields) via HSET
func (p *Publisher) SetHashFromJSON(ctx context.Context, key string, data any) error {
	raw, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("marshal: %w", err)
	}
	var fields map[string]interface{}
	if err := json.Unmarshal(raw, &fields); err != nil {
		return fmt.Errorf("unmarshal to map: %w", err)
	}
	return p.rdb.HSet(ctx, key, fields).Err()
}

// Ping checks Redis connectivity.
func (p *Publisher) Ping(ctx context.Context) error {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	return p.rdb.Ping(ctx).Err()
}

// Close shuts down the Redis connection.
func (p *Publisher) Close() error {
	return p.rdb.Close()
}

// PublishWithRetry attempts to publish with retries on failure.
//
// @bodhi.intent Publish event with retry on transient failure
// @bodhi.writes redis:stream(data) via XADD
// @bodhi.on_fail xadd_error → retry maxRetries → return error
func (p *Publisher) PublishWithRetry(ctx context.Context, streamName string, data any, maxRetries int) error {
	var lastErr error
	for i := 0; i <= maxRetries; i++ {
		if err := p.Publish(ctx, streamName, data); err != nil {
			lastErr = err
			slog.Warn("stream publish failed, retrying",
				"stream", streamName, "attempt", i+1, "error", err)
			time.Sleep(time.Duration(i+1) * 500 * time.Millisecond)
			continue
		}
		return nil
	}
	return fmt.Errorf("publish failed after %d retries: %w", maxRetries, lastErr)
}
