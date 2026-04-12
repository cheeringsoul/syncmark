package chain

import (
	"context"
	"log/slog"
	"sync"

	"github.com/ymy/syncmark/collector/internal/config"
	"github.com/ymy/syncmark/collector/internal/stream"
)

// Monitor orchestrates on-chain watchers for all supported chains.
type Monitor struct {
	cfg       config.ChainConfig
	publisher *stream.Publisher
	labels    *LabelStore
}

// NewMonitor creates a chain monitor.
func NewMonitor(cfg config.ChainConfig, pub *stream.Publisher) (*Monitor, error) {
	labels, err := NewLabelStore(cfg.LabelsFile)
	if err != nil {
		return nil, err
	}
	return &Monitor{cfg: cfg, publisher: pub, labels: labels}, nil
}

// Start launches ETH and SOL watchers in parallel.
//
// @bodhi.intent Initialize ETH and SOL chain watchers, load address labels, start monitoring
// @bodhi.reads config(chain.ethereum.rpc_ws, chain.solana.rpc_ws, chain.labels_file)
// @bodhi.calls Start
// @bodhi.calls Start
func (m *Monitor) Start(ctx context.Context) error {
	ethWatcher := NewEthWatcher(m.cfg.Ethereum, m.publisher, m.labels)
	solWatcher := NewSolWatcher(m.cfg.Solana, m.publisher, m.labels)

	var wg sync.WaitGroup
	errCh := make(chan error, 2)

	wg.Add(2)
	go func() {
		defer wg.Done()
		if err := ethWatcher.Start(ctx); err != nil {
			slog.Error("eth watcher exited", "error", err)
			errCh <- err
		}
	}()
	go func() {
		defer wg.Done()
		if err := solWatcher.Start(ctx); err != nil {
			slog.Error("sol watcher exited", "error", err)
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
