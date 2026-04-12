package config

import (
	"os"
	"time"

	"gopkg.in/yaml.v3"
)

type Config struct {
	Redis    RedisConfig    `yaml:"redis"`
	Telegram TelegramConfig `yaml:"telegram"`
	CEX      CEXConfig      `yaml:"cex"`
	Chain    ChainConfig    `yaml:"chain"`
	Macro    MacroConfig    `yaml:"macro"`
}

type RedisConfig struct {
	Addr     string `yaml:"addr"`
	Password string `yaml:"password"`
	DB       int    `yaml:"db"`
}

type TelegramConfig struct {
	AppID      int              `yaml:"app_id"`
	AppHash    string           `yaml:"app_hash"`
	Phone      string           `yaml:"phone"`
	SessionDir string           `yaml:"session_dir"`
	Channels   []TelegramTarget `yaml:"channels"`
}

type TelegramTarget struct {
	ID   int64  `yaml:"id"`
	Name string `yaml:"name"`
}

type CEXConfig struct {
	LargeOrderThresholdUSD float64  `yaml:"large_order_threshold_usd"`
	Symbols                []string `yaml:"symbols"`
	KlineIntervals         []string `yaml:"kline_intervals"`
}

type ChainConfig struct {
	Ethereum   ChainNodeConfig `yaml:"ethereum"`
	Solana     ChainNodeConfig `yaml:"solana"`
	LabelsFile string          `yaml:"labels_file"`
}

type ChainNodeConfig struct {
	RPCWS             string  `yaml:"rpc_ws"`
	WhaleThresholdUSD float64 `yaml:"whale_threshold_usd"`
}

type MacroConfig struct {
	CalendarCron             string        `yaml:"calendar_cron"`
	PublishPollInterval      time.Duration `yaml:"publish_poll_interval"`
	PublishPollWindow        time.Duration `yaml:"publish_poll_window"`
	DashboardRefreshInterval time.Duration `yaml:"dashboard_refresh_interval"`
	Sources                  MacroSources  `yaml:"sources"`
}

type MacroSources struct {
	FearGreedURL string `yaml:"fear_greed_url"`
}

// Load reads and parses the YAML config file at the given path.
func Load(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var cfg Config
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
}
