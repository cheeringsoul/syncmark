package cex

import (
	"context"
	"log/slog"
	"sync"

	"github.com/ymy/syncmark/collector/internal/config"
	"github.com/ymy/syncmark/collector/internal/stream"
)

// Manager orchestrates all CEX WebSocket connections.
type Manager struct {
	cfg       config.CEXConfig
	publisher *stream.Publisher
}

// NewManager creates a CEX manager.
func NewManager(cfg config.CEXConfig, pub *stream.Publisher) *Manager {
	return &Manager{cfg: cfg, publisher: pub}
}

// Start launches Binance and OKX WebSocket connections in parallel.
//
// @bodhi.intent Initialize WebSocket connections to Binance and OKX, subscribe to market data streams
// @bodhi.reads config(cex.symbols, cex.kline_intervals, cex.large_order_threshold_usd)
// @bodhi.calls Connect
// @bodhi.calls Connect
func (m *Manager) Start(ctx context.Context) error {
	binance := NewBinanceWS(m.cfg, m.publisher)
	okx := NewOkxWS(m.cfg, m.publisher)

	var wg sync.WaitGroup
	errCh := make(chan error, 2)

	wg.Add(2)
	go func() {
		defer wg.Done()
		if err := binance.Connect(ctx); err != nil {
			slog.Error("binance ws exited", "error", err)
			errCh <- err
		}
	}()
	go func() {
		defer wg.Done()
		if err := okx.Connect(ctx); err != nil {
			slog.Error("okx ws exited", "error", err)
			errCh <- err
		}
	}()

	wg.Wait()
	close(errCh)

	for err := range errCh {
		if err != nil {
			return err
		}
	}
	return nil
}
