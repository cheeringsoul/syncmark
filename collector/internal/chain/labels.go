package chain

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

// AddressLabel holds metadata for a tracked address.
type AddressLabel struct {
	Label        string `json:"label"`
	IsSmartMoney bool   `json:"is_smart_money"`
	IsExchange   bool   `json:"is_exchange"`
}

// LabelStore provides address → label lookups.
type LabelStore struct {
	labels map[string]AddressLabel // lowercase address → label
}

// NewLabelStore loads address labels from a JSON file.
func NewLabelStore(path string) (*LabelStore, error) {
	store := &LabelStore{labels: make(map[string]AddressLabel)}

	if path == "" {
		return store, nil
	}

	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return store, nil
		}
		return nil, fmt.Errorf("read labels: %w", err)
	}

	var raw map[string]AddressLabel
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("parse labels: %w", err)
	}

	for addr, label := range raw {
		store.labels[strings.ToLower(addr)] = label
	}
	return store, nil
}

// Lookup returns the label for an address. Returns "Unknown" if not found.
func (s *LabelStore) Lookup(address string) AddressLabel {
	if l, ok := s.labels[strings.ToLower(address)]; ok {
		return l
	}
	return AddressLabel{Label: "Unknown"}
}

// IsSmartMoney checks if an address is tracked as smart money.
func (s *LabelStore) IsSmartMoney(address string) bool {
	return s.labels[strings.ToLower(address)].IsSmartMoney
}
