package chain

import (
	"context"
	"fmt"
	"log/slog"
	"math"
	"math/big"
	"strings"
	"time"

	"github.com/ethereum/go-ethereum"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/ethclient"

	"github.com/ymy/syncmark/collector/internal/config"
	"github.com/ymy/syncmark/collector/internal/model"
	"github.com/ymy/syncmark/collector/internal/stream"
)

// ERC20 Transfer event signature: Transfer(address,address,uint256)
var erc20TransferTopic = common.HexToHash("0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef")

// EthWatcher monitors Ethereum for whale transfers and smart money activity.
type EthWatcher struct {
	cfg       config.ChainNodeConfig
	publisher *stream.Publisher
	labels    *LabelStore
}

func NewEthWatcher(cfg config.ChainNodeConfig, pub *stream.Publisher, labels *LabelStore) *EthWatcher {
	return &EthWatcher{cfg: cfg, publisher: pub, labels: labels}
}

// Start connects to the Ethereum node and subscribes to Transfer logs.
//
// @bodhi.intent Connect to Ethereum WebSocket, subscribe to ERC20 Transfer logs for whale/smart money detection
// @bodhi.reads config(chain.ethereum.rpc_ws, chain.ethereum.whale_threshold_usd)
// @bodhi.calls handleTransfer
// @bodhi.calls handleSmartMoney
// @bodhi.on_fail rpc_error → reconnect with backoff
func (w *EthWatcher) Start(ctx context.Context) error {
	for {
		if err := w.connectAndWatch(ctx); err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			slog.Warn("eth watcher disconnected, reconnecting", "error", err)
			time.Sleep(5 * time.Second)
			continue
		}
		return nil
	}
}

func (w *EthWatcher) connectAndWatch(ctx context.Context) error {
	client, err := ethclient.DialContext(ctx, w.cfg.RPCWS)
	if err != nil {
		return fmt.Errorf("dial eth: %w", err)
	}
	defer client.Close()

	slog.Info("eth watcher connected", "rpc", w.cfg.RPCWS)

	// Subscribe to all ERC20 Transfer events.
	query := ethereum.FilterQuery{
		Topics: [][]common.Hash{{erc20TransferTopic}},
	}

	logCh := make(chan types.Log, 256)
	sub, err := client.SubscribeFilterLogs(ctx, query, logCh)
	if err != nil {
		return fmt.Errorf("subscribe logs: %w", err)
	}
	defer sub.Unsubscribe()

	for {
		select {
		case <-ctx.Done():
			return nil
		case err := <-sub.Err():
			return fmt.Errorf("subscription: %w", err)
		case log := <-logCh:
			w.processLog(ctx, log)
		}
	}
}

func (w *EthWatcher) processLog(ctx context.Context, log types.Log) {
	if len(log.Topics) < 3 {
		return
	}

	from := common.BytesToAddress(log.Topics[1].Bytes()).Hex()
	to := common.BytesToAddress(log.Topics[2].Bytes()).Hex()
	amount := new(big.Float).SetInt(new(big.Int).SetBytes(log.Data))

	// Rough USD estimate — in production, use a price oracle.
	// For now, treat raw token amount as a proxy (works for stablecoins).
	decimals := 18.0
	valueFloat, _ := new(big.Float).Quo(amount, big.NewFloat(math.Pow(10, decimals))).Float64()

	// Check smart money first (lower threshold).
	if w.labels.IsSmartMoney(from) || w.labels.IsSmartMoney(to) {
		w.handleSmartMoney(ctx, from, to, valueFloat, log)
	}

	// Check whale threshold.
	if valueFloat >= w.cfg.WhaleThresholdUSD {
		w.handleTransfer(ctx, from, to, valueFloat, log)
	}
}

// handleTransfer publishes a whale transfer event.
//
// @bodhi.intent Process ETH/ERC20 large transfer, match address labels, publish whale event
// @bodhi.reads eth.log(from, to, value, token, tx_hash, block_timestamp)
// @bodhi.reads labels(address → label)
// @bodhi.reads config(chain.ethereum.whale_threshold_usd)
// @bodhi.emits chain_whale_transfer(chain, tx_hash, from_address, from_label, to_address, to_label, token, amount, value_usd, timestamp) to redis:chain:whale_transfers
// @bodhi.on_fail rpc_error → retry 3 → log
// @bodhi.on_fail label_lookup_miss → use "Unknown"
func (w *EthWatcher) handleTransfer(ctx context.Context, from, to string, valueUSD float64, log types.Log) {
	fromLabel := w.labels.Lookup(from)
	toLabel := w.labels.Lookup(to)

	transfer := model.WhaleTransfer{
		Chain:       "ethereum",
		TxHash:      log.TxHash.Hex(),
		FromAddress: from,
		FromLabel:   fromLabel.Label,
		ToAddress:   to,
		ToLabel:     toLabel.Label,
		Token:       "ERC20",
		Amount:      valueUSD,
		ValueUSD:    valueUSD,
		Timestamp:   time.Now(),
	}

	if err := w.publisher.PublishWithRetry(ctx, stream.ChainWhaleTransfers, transfer, 3); err != nil {
		slog.Error("eth whale transfer publish", "tx", log.TxHash.Hex(), "error", err)
	}
}

// handleSmartMoney publishes a smart money activity event.
//
// @bodhi.intent Detect smart money buy/sell from tracked addresses
// @bodhi.reads eth.log(from, to, value, token, tx_hash, block_timestamp)
// @bodhi.reads labels(address → label, is_smart_money)
// @bodhi.emits chain_smart_money(chain, address, label, action, token, amount, value_usd, tx_hash, timestamp) to redis:chain:smart_money
// @bodhi.on_fail price_lookup_error → log + skip
func (w *EthWatcher) handleSmartMoney(ctx context.Context, from, to string, valueUSD float64, log types.Log) {
	var address, action string
	if w.labels.IsSmartMoney(from) {
		address = from
		action = "sell"
	} else {
		address = to
		action = "buy"
	}

	label := w.labels.Lookup(address)

	// If the counterparty is an exchange, refine the action.
	counterparty := to
	if address == to {
		counterparty = from
	}
	cpLabel := w.labels.Lookup(counterparty)
	if cpLabel.IsExchange && action == "sell" {
		action = "transfer_to_exchange"
	}

	move := model.SmartMoneyMove{
		Chain:     "ethereum",
		Address:   address,
		Label:     label.Label,
		Action:    action,
		Token:     "ERC20",
		Amount:    valueUSD,
		ValueUSD:  valueUSD,
		TxHash:    log.TxHash.Hex(),
		Timestamp: time.Now(),
	}

	if err := w.publisher.Publish(ctx, stream.ChainSmartMoney, move); err != nil {
		slog.Warn("eth smart money publish", "address", address, "error", err)
	}

	slog.Info("smart money detected",
		"chain", "ethereum", "address", truncateAddr(address),
		"action", action, "value_usd", valueUSD)
}

func truncateAddr(addr string) string {
	if len(addr) > 10 {
		return addr[:6] + "..." + addr[len(addr)-4:]
	}
	return addr
}

// isNativeETHTransfer checks if a transfer is native ETH (not ERC20).
// Currently unused — reserved for future native ETH monitoring via pending tx subscription.
func isNativeETHTransfer(addr string) bool {
	return strings.EqualFold(addr, "0x0000000000000000000000000000000000000000")
}
