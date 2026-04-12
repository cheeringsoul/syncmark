package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"sync"
	"syscall"

	"github.com/ymy/syncmark/collector/internal/cex"
	"github.com/ymy/syncmark/collector/internal/chain"
	"github.com/ymy/syncmark/collector/internal/config"
	"github.com/ymy/syncmark/collector/internal/macro"
	"github.com/ymy/syncmark/collector/internal/stream"
	"github.com/ymy/syncmark/collector/internal/telegram"
)

func main() {
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo})))

	cfgPath := "configs/collector.yaml"
	if p := os.Getenv("COLLECTOR_CONFIG"); p != "" {
		cfgPath = p
	}

	cfg, err := config.Load(cfgPath)
	if err != nil {
		slog.Error("load config", "error", err)
		os.Exit(1)
	}

	pub := stream.NewPublisher(cfg.Redis)
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	if err := pub.Ping(ctx); err != nil {
		slog.Error("redis ping", "error", err)
		os.Exit(1)
	}
	slog.Info("redis connected", "addr", cfg.Redis.Addr)

	var wg sync.WaitGroup

	// Telegram listener.
	wg.Add(1)
	go func() {
		defer wg.Done()
		listener := telegram.NewListener(cfg.Telegram, pub)
		if err := listener.Start(ctx); err != nil {
			slog.Error("telegram listener", "error", err)
		}
	}()

	// CEX market data.
	wg.Add(1)
	go func() {
		defer wg.Done()
		mgr := cex.NewManager(cfg.CEX, pub)
		if err := mgr.Start(ctx); err != nil {
			slog.Error("cex manager", "error", err)
		}
	}()

	// On-chain monitor.
	wg.Add(1)
	go func() {
		defer wg.Done()
		mon, err := chain.NewMonitor(cfg.Chain, pub)
		if err != nil {
			slog.Error("chain monitor init", "error", err)
			return
		}
		if err := mon.Start(ctx); err != nil {
			slog.Error("chain monitor", "error", err)
		}
	}()

	// Macro economic data.
	wg.Add(1)
	go func() {
		defer wg.Done()
		sched := macro.NewScheduler(cfg.Macro, pub)
		if err := sched.Start(ctx); err != nil {
			slog.Error("macro scheduler", "error", err)
		}
	}()

	slog.Info("collector started, all modules running")
	wg.Wait()
	pub.Close()
	slog.Info("collector stopped")
}
