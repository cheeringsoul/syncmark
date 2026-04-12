package chain

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/gorilla/websocket"

	"github.com/ymy/syncmark/collector/internal/config"
	"github.com/ymy/syncmark/collector/internal/model"
	"github.com/ymy/syncmark/collector/internal/stream"
)

// SolWatcher monitors Solana for whale transfers and smart money activity via RPC WebSocket.
type SolWatcher struct {
	cfg       config.ChainNodeConfig
	publisher *stream.Publisher
	labels    *LabelStore
}

func NewSolWatcher(cfg config.ChainNodeConfig, pub *stream.Publisher, labels *LabelStore) *SolWatcher {
	return &SolWatcher{cfg: cfg, publisher: pub, labels: labels}
}

// Start connects to Solana RPC WebSocket and subscribes to account notifications.
//
// @bodhi.intent Connect to Solana WebSocket, subscribe to tracked account changes for whale/smart money detection
// @bodhi.reads config(chain.solana.rpc_ws, chain.solana.whale_threshold_usd)
// @bodhi.calls handleTransfer
// @bodhi.calls handleSmartMoney
// @bodhi.on_fail rpc_error → reconnect with backoff
func (w *SolWatcher) Start(ctx context.Context) error {
	for {
		if err := w.connectAndWatch(ctx); err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			slog.Warn("sol watcher disconnected, reconnecting", "error", err)
			time.Sleep(5 * time.Second)
			continue
		}
		return nil
	}
}

func (w *SolWatcher) connectAndWatch(ctx context.Context) error {
	conn, _, err := websocket.DefaultDialer.DialContext(ctx, w.cfg.RPCWS, nil)
	if err != nil {
		return fmt.Errorf("dial sol: %w", err)
	}
	defer conn.Close()

	slog.Info("sol watcher connected", "rpc", w.cfg.RPCWS)

	// Subscribe to logs mentioning the Token Program (SPL transfers).
	subReq := map[string]interface{}{
		"jsonrpc": "2.0",
		"id":      1,
		"method":  "logsSubscribe",
		"params": []interface{}{
			map[string]interface{}{
				"mentions": []string{"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, // SPL Token Program
			},
			map[string]interface{}{
				"commitment": "confirmed",
			},
		},
	}
	if err := conn.WriteJSON(subReq); err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}

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

		var notification struct {
			Method string `json:"method"`
			Params struct {
				Result struct {
					Value struct {
						Signature string   `json:"signature"`
						Logs      []string `json:"logs"`
					} `json:"value"`
				} `json:"result"`
			} `json:"params"`
		}
		if err := json.Unmarshal(data, &notification); err != nil {
			continue
		}

		if notification.Method != "logsNotification" {
			continue
		}

		w.processLogs(ctx, notification.Params.Result.Value.Signature, notification.Params.Result.Value.Logs)
	}
}

func (w *SolWatcher) processLogs(ctx context.Context, signature string, logs []string) {
	// Parse SPL Transfer instructions from logs.
	// Solana logs contain "Transfer" instructions with source, destination, amount.
	for _, logLine := range logs {
		transfer := parseSPLTransferLog(logLine)
		if transfer == nil {
			continue
		}

		transfer.TxHash = signature

		if w.labels.IsSmartMoney(transfer.FromAddress) || w.labels.IsSmartMoney(transfer.ToAddress) {
			w.handleSmartMoney(ctx, transfer)
		}

		if transfer.ValueUSD >= w.cfg.WhaleThresholdUSD {
			w.handleTransfer(ctx, transfer)
		}
	}
}

// handleTransfer publishes a Solana whale transfer event.
//
// @bodhi.intent Process SOL large transfer, match labels, publish whale event
// @bodhi.reads sol.transaction(from, to, amount, token, signature, block_time)
// @bodhi.reads labels(address → label)
// @bodhi.reads config(chain.solana.whale_threshold_usd)
// @bodhi.emits chain_whale_transfer(chain, tx_hash, from_address, from_label, to_address, to_label, token, amount, value_usd, timestamp) to redis:chain:whale_transfers
func (w *SolWatcher) handleTransfer(ctx context.Context, t *solTransfer) {
	fromLabel := w.labels.Lookup(t.FromAddress)
	toLabel := w.labels.Lookup(t.ToAddress)

	transfer := model.WhaleTransfer{
		Chain:       "solana",
		TxHash:      t.TxHash,
		FromAddress: t.FromAddress,
		FromLabel:   fromLabel.Label,
		ToAddress:   t.ToAddress,
		ToLabel:     toLabel.Label,
		Token:       t.Token,
		Amount:      t.Amount,
		ValueUSD:    t.ValueUSD,
		Timestamp:   time.Now(),
	}

	if err := w.publisher.PublishWithRetry(ctx, stream.ChainWhaleTransfers, transfer, 3); err != nil {
		slog.Error("sol whale transfer publish", "tx", t.TxHash, "error", err)
	}
}

// handleSmartMoney publishes a Solana smart money activity event.
//
// @bodhi.intent Detect SOL smart money activity from tracked addresses
// @bodhi.reads sol.transaction(from, to, amount, token, signature, block_time)
// @bodhi.reads labels(address → label, is_smart_money)
// @bodhi.emits chain_smart_money(chain, address, label, action, token, amount, value_usd, tx_hash, timestamp) to redis:chain:smart_money
func (w *SolWatcher) handleSmartMoney(ctx context.Context, t *solTransfer) {
	var address, action string
	if w.labels.IsSmartMoney(t.FromAddress) {
		address = t.FromAddress
		action = "sell"
	} else {
		address = t.ToAddress
		action = "buy"
	}

	label := w.labels.Lookup(address)

	move := model.SmartMoneyMove{
		Chain:     "solana",
		Address:   address,
		Label:     label.Label,
		Action:    action,
		Token:     t.Token,
		Amount:    t.Amount,
		ValueUSD:  t.ValueUSD,
		TxHash:    t.TxHash,
		Timestamp: time.Now(),
	}

	if err := w.publisher.Publish(ctx, stream.ChainSmartMoney, move); err != nil {
		slog.Warn("sol smart money publish", "address", address, "error", err)
	}
}

type solTransfer struct {
	FromAddress string
	ToAddress   string
	Token       string
	Amount      float64
	ValueUSD    float64
	TxHash      string
}

// parseSPLTransferLog attempts to extract transfer info from a Solana log line.
// This is a simplified parser — production would use parsed transaction instructions.
func parseSPLTransferLog(logLine string) *solTransfer {
	// Solana program logs for SPL transfers contain patterns like:
	// "Program log: Transfer <amount> tokens from <src> to <dst>"
	// This is a placeholder — real implementation would parse instruction data.
	_ = logLine
	return nil
}
