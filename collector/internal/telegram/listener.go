package telegram

import (
	"context"
	"fmt"
	"log/slog"
	"path/filepath"
	"time"

	"github.com/gotd/td/session"
	"github.com/gotd/td/telegram"
	"github.com/gotd/td/telegram/auth"
	"github.com/gotd/td/tg"

	"github.com/ymy/syncmark/collector/internal/config"
	"github.com/ymy/syncmark/collector/internal/model"
	"github.com/ymy/syncmark/collector/internal/stream"
)

// Listener connects to Telegram via MTProto and forwards channel messages to Redis Stream.
type Listener struct {
	cfg       config.TelegramConfig
	publisher *stream.Publisher
	client    *telegram.Client
	channels  map[int64]string // channelID → name
}

// NewListener creates a Telegram listener.
func NewListener(cfg config.TelegramConfig, pub *stream.Publisher) *Listener {
	channels := make(map[int64]string, len(cfg.Channels))
	for _, ch := range cfg.Channels {
		channels[ch.ID] = ch.Name
	}
	return &Listener{
		cfg:       cfg,
		publisher: pub,
		channels:  channels,
	}
}

// Start initializes the MTProto client, authenticates, and begins listening.
//
// @bodhi.intent Initialize MTProto client, authenticate, subscribe to configured channels
// @bodhi.reads config(telegram.app_id, telegram.app_hash, telegram.phone, telegram.channels)
// @bodhi.calls handleMessage
// @bodhi.on_fail auth_error → return error
// @bodhi.on_fail connection_error → reconnect (handled by gotd)
func (l *Listener) Start(ctx context.Context) error {
	sessionStorage := &session.FileStorage{
		Path: filepath.Join(l.cfg.SessionDir, "session.json"),
	}

	dispatcher := tg.NewUpdateDispatcher()
	dispatcher.OnNewChannelMessage(func(ctx context.Context, e tg.Entities, update *tg.UpdateNewChannelMessage) error {
		msg, ok := update.Message.(*tg.Message)
		if !ok {
			return nil
		}
		return l.handleMessage(ctx, msg)
	})

	l.client = telegram.NewClient(l.cfg.AppID, l.cfg.AppHash, telegram.Options{
		SessionStorage: sessionStorage,
		UpdateHandler:  &dispatcher,
	})

	return l.client.Run(ctx, func(ctx context.Context) error {
		status, err := l.client.Auth().Status(ctx)
		if err != nil {
			return fmt.Errorf("auth status: %w", err)
		}
		if !status.Authorized {
			flow := auth.NewFlow(terminalAuth{phone: l.cfg.Phone}, auth.SendCodeOptions{})
			if err := l.client.Auth().IfNecessary(ctx, flow); err != nil {
				return fmt.Errorf("auth: %w", err)
			}
		}

		slog.Info("telegram authenticated", "phone", l.cfg.Phone)
		return telegram.RunUntilCanceled(ctx, l.client)
	})
}

// handleMessage processes a single incoming Telegram message and publishes it to Redis Stream.
//
// @bodhi.intent Process incoming Telegram message, extract fields, publish to Redis Stream
// @bodhi.reads telegram.message(channelID, messageID, text, media, date)
// @bodhi.emits telegram_raw_message(channel_id, channel_name, message_id, text, media_type, media_url, telegram_date) to redis:telegram:raw_messages
// @bodhi.on_fail marshal_error → log + skip
// @bodhi.on_fail stream_write_error → retry 3 → log
func (l *Listener) handleMessage(ctx context.Context, msg *tg.Message) error {
	peerChannel, ok := msg.PeerID.(*tg.PeerChannel)
	if !ok {
		return nil
	}

	channelID := peerChannel.ChannelID
	channelName, monitored := l.channels[channelID]
	if !monitored {
		return nil
	}

	mediaType, mediaURL := extractMedia(msg)

	event := model.TelegramMessage{
		ChannelID:    channelID,
		ChannelName:  channelName,
		MessageID:    int64(msg.ID),
		Text:         msg.Message,
		MediaType:    mediaType,
		MediaURL:     mediaURL,
		TelegramDate: time.Unix(int64(msg.Date), 0),
	}

	if err := l.publisher.PublishWithRetry(ctx, stream.TelegramRawMessages, event, 3); err != nil {
		slog.Error("failed to publish telegram message",
			"channel", channelName, "msg_id", msg.ID, "error", err)
		return nil // don't crash on publish failure
	}

	slog.Debug("telegram message published",
		"channel", channelName, "msg_id", msg.ID)
	return nil
}

func extractMedia(msg *tg.Message) (mediaType string, mediaURL string) {
	if msg.Media == nil {
		return "none", ""
	}
	switch msg.Media.(type) {
	case *tg.MessageMediaPhoto:
		return "photo", ""
	case *tg.MessageMediaDocument:
		return "document", ""
	default:
		return "other", ""
	}
}
