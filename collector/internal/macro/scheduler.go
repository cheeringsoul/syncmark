package macro

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"

	"github.com/ymy/syncmark/collector/internal/config"
	"github.com/ymy/syncmark/collector/internal/model"
	"github.com/ymy/syncmark/collector/internal/stream"
)

// Scheduler manages periodic macro economic data collection tasks.
type Scheduler struct {
	cfg       config.MacroConfig
	publisher *stream.Publisher
	client    *http.Client
}

// NewScheduler creates a macro data scheduler.
func NewScheduler(cfg config.MacroConfig, pub *stream.Publisher) *Scheduler {
	return &Scheduler{
		cfg:       cfg,
		publisher: pub,
		client:    &http.Client{Timeout: 15 * time.Second},
	}
}

// Start launches all periodic macro data collection tasks.
//
// @bodhi.intent Initialize cron jobs for calendar sync, publish polling, and dashboard refresh
// @bodhi.reads config(macro.calendar_cron, macro.publish_poll_interval, macro.dashboard_refresh_interval)
// @bodhi.calls syncCalendar
// @bodhi.calls pollPublish
// @bodhi.calls refreshDashboard
func (s *Scheduler) Start(ctx context.Context) error {
	// Initial calendar sync on startup.
	s.syncCalendar(ctx)
	s.refreshDashboard(ctx)

	calendarTicker := time.NewTicker(24 * time.Hour)
	dashboardTicker := time.NewTicker(s.cfg.DashboardRefreshInterval)
	pollTicker := time.NewTicker(s.cfg.PublishPollInterval)

	defer calendarTicker.Stop()
	defer dashboardTicker.Stop()
	defer pollTicker.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-calendarTicker.C:
			s.syncCalendar(ctx)
		case <-dashboardTicker.C:
			s.refreshDashboard(ctx)
		case <-pollTicker.C:
			s.pollPublish(ctx)
		}
	}
}

// syncCalendar fetches the economic calendar and publishes events to Redis Stream.
//
// @bodhi.intent Scrape economic calendar from data source, upsert events to stream
// @bodhi.reads http:calendar_source(events)
// @bodhi.emits macro_economic_event(event_id, name, country, importance, scheduled_at, previous, forecast, status=SCHEDULED) to redis:macro:economic_events
// @bodhi.on_fail scrape_error → retry 3 → log
func (s *Scheduler) syncCalendar(ctx context.Context) {
	slog.Info("syncing economic calendar")

	events, err := s.fetchCalendar(ctx)
	if err != nil {
		slog.Error("calendar sync failed", "error", err)
		return
	}

	for _, event := range events {
		if err := s.publisher.Publish(ctx, stream.MacroEconomicEvents, event); err != nil {
			slog.Warn("calendar event publish", "event_id", event.EventID, "error", err)
		}
	}

	slog.Info("calendar synced", "events", len(events))
}

// pollPublish checks for recently published economic data and emits updates.
//
// @bodhi.intent During publish window, poll for actual values of upcoming economic events
// @bodhi.reads http:calendar_source(event_id, actual)
// @bodhi.emits macro_event_published(event_id, actual) to redis:macro:economic_events
// @bodhi.on_fail poll_error → log + continue
func (s *Scheduler) pollPublish(ctx context.Context) {
	// In production, this would:
	// 1. Check which events are in UPCOMING status and within the publish window
	// 2. Poll the data source for actual values
	// 3. Emit updates when actual values appear
	//
	// Placeholder — requires integration with a specific calendar data source.
}

// refreshDashboard fetches key macro indicators and updates Redis cache.
//
// @bodhi.intent Fetch key macro indicators and update Redis cache
// @bodhi.reads http:alternative.me/fng(value, classification)
// @bodhi.writes redis:macro:dashboard(fear_greed_index, dxy, us10y_yield, updated_at) via SET
// @bodhi.on_fail api_error → use stale data + log
func (s *Scheduler) refreshDashboard(ctx context.Context) {
	dashboard := model.DashboardData{
		UpdatedAt: time.Now(),
	}

	// Fetch Fear & Greed Index.
	if fg, err := s.fetchFearGreed(ctx); err != nil {
		slog.Warn("fear greed fetch failed", "error", err)
	} else {
		dashboard.FearGreedIndex = fg.Value
		dashboard.FearGreedLabel = fg.Classification
	}

	key := "macro:dashboard"
	if err := s.publisher.SetHashFromJSON(ctx, key, dashboard); err != nil {
		slog.Warn("dashboard cache write", "error", err)
	}
}

type fearGreedResponse struct {
	Data []struct {
		Value          string `json:"value"`
		Classification string `json:"value_classification"`
	} `json:"data"`
}

type fearGreedResult struct {
	Value          int
	Classification string
}

func (s *Scheduler) fetchFearGreed(ctx context.Context) (*fearGreedResult, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.cfg.Sources.FearGreedURL, nil)
	if err != nil {
		return nil, err
	}

	resp, err := s.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var fgResp fearGreedResponse
	if err := json.Unmarshal(body, &fgResp); err != nil {
		return nil, err
	}

	if len(fgResp.Data) == 0 {
		return nil, fmt.Errorf("empty fear greed response")
	}

	var val int
	fmt.Sscanf(fgResp.Data[0].Value, "%d", &val)

	return &fearGreedResult{
		Value:          val,
		Classification: fgResp.Data[0].Classification,
	}, nil
}

// fetchCalendar fetches economic events from the calendar data source.
// Placeholder — in production, integrate with Investing.com / TradingEconomics / 金十数据.
func (s *Scheduler) fetchCalendar(ctx context.Context) ([]model.EconomicEvent, error) {
	// TODO: Implement actual calendar scraping.
	// This would parse HTML or call an API to get upcoming economic events.
	return nil, nil
}
