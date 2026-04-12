package model

import "time"

type TelegramMessage struct {
	ChannelID    int64     `json:"channel_id"`
	ChannelName  string    `json:"channel_name"`
	MessageID    int64     `json:"message_id"`
	Text         string    `json:"text"`
	MediaType    string    `json:"media_type"`
	MediaURL     string    `json:"media_url"`
	TelegramDate time.Time `json:"telegram_date"`
}

type Ticker struct {
	Exchange  string    `json:"exchange"`
	Symbol    string    `json:"symbol"`
	Price     string    `json:"price"`
	Change24h string    `json:"change_24h"`
	Volume24h string    `json:"volume_24h"`
	High24h   string    `json:"high_24h"`
	Low24h    string    `json:"low_24h"`
	UpdatedAt time.Time `json:"updated_at"`
}

type Kline struct {
	Exchange    string    `json:"exchange"`
	Symbol      string    `json:"symbol"`
	Interval    string    `json:"interval"`
	Open        string    `json:"open"`
	High        string    `json:"high"`
	Low         string    `json:"low"`
	Close       string    `json:"close"`
	Volume      string    `json:"volume"`
	QuoteVolume string    `json:"quote_volume"`
	OpenTime    time.Time `json:"open_time"`
	CloseTime   time.Time `json:"close_time"`
}

type LargeOrder struct {
	Exchange  string    `json:"exchange"`
	Symbol    string    `json:"symbol"`
	Side      string    `json:"side"`
	Price     float64   `json:"price"`
	Quantity  float64   `json:"quantity"`
	ValueUSD  float64   `json:"value_usd"`
	Timestamp time.Time `json:"timestamp"`
}

type WhaleTransfer struct {
	Chain       string    `json:"chain"`
	TxHash      string    `json:"tx_hash"`
	FromAddress string    `json:"from_address"`
	FromLabel   string    `json:"from_label"`
	ToAddress   string    `json:"to_address"`
	ToLabel     string    `json:"to_label"`
	Token       string    `json:"token"`
	Amount      float64   `json:"amount"`
	ValueUSD    float64   `json:"value_usd"`
	Timestamp   time.Time `json:"timestamp"`
}

type SmartMoneyMove struct {
	Chain     string    `json:"chain"`
	Address   string    `json:"address"`
	Label     string    `json:"label"`
	Action    string    `json:"action"`
	Token     string    `json:"token"`
	Amount    float64   `json:"amount"`
	ValueUSD  float64   `json:"value_usd"`
	TxHash    string    `json:"tx_hash"`
	Timestamp time.Time `json:"timestamp"`
}

type EconomicEvent struct {
	EventID     string    `json:"event_id"`
	Name        string    `json:"name"`
	Country     string    `json:"country"`
	Importance  string    `json:"importance"`
	ScheduledAt time.Time `json:"scheduled_at"`
	Previous    string    `json:"previous"`
	Forecast    string    `json:"forecast"`
	Actual      string    `json:"actual"`
	Status      string    `json:"status"`
}

type DashboardData struct {
	FearGreedIndex int       `json:"fear_greed_index"`
	FearGreedLabel string    `json:"fear_greed_label"`
	DXY            string    `json:"dxy"`
	US10YYield     string    `json:"us10y_yield"`
	UpdatedAt      time.Time `json:"updated_at"`
}
