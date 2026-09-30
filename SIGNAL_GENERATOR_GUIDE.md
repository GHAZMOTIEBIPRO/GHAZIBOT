# BLACK BOX Signal Generator - Technical Guide

**Date:** 2026-09-30  
**Version:** 1.0  
**Status:** Production-Ready Reference Implementation  

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Core Engines](#core-engines)
4. [Integration Points](#integration-points)
5. [API Reference](#api-reference)
6. [Usage Examples](#usage-examples)
7. [Testing Strategy](#testing-strategy)
8. [Deployment Checklist](#deployment-checklist)

---

## Overview

### Purpose

The **Signal Generator** is the orchestration layer that fuses:
- Real-time market quotes (via Finnhub, IEX, Polygon)
- Technical indicators (EMA, RSI, trend detection)
- Options flow metrics (unusual volume, IV spikes)
- Gamma exposure levels (via FlashAlpha SDK)
- SEC company verification
- Strict data validation

Into a **single, confidence-scored trading signal** suitable for manual review and Telegram alerting.

### Non-Goals

- ❌ Placing broker orders or executing trades
- ❌ Accepting or forwarding TradingView webhooks
- ❌ Using yfinance or Yahoo Finance for decision authority
- ❌ Promising win rates or guaranteed profit

### Key Design Principles

1. **Decision Authority Only When Qualified:**
   - Quote source must be real-time (LIVE_OPRA, MARKET_DATA_FEED, ACCOUNT_FEED)
   - Bid/Ask spread ≤ 5%
   - Data freshness < 5 seconds
   - SEC company verification confidence ≥ 85%
   - Minimum 2 independent signals aligned

2. **Data Lineage at Every Step:**
   - Every quote carries source, timestamp, and confidence level
   - Rejection reasons fully documented
   - Audit trail for compliance and backtesting

3. **Provider Agnostic:**
   - No hard dependency on yfinance
   - Adapter pattern for data sources
   - Easy to swap providers without rewriting core logic

---

## Architecture

### System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     Signal Generator Engine                      │
│                  (engines/signal_generator.py)                   │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  GEX Calculator  │ │  Flow Detector   │ │  Chart Analyzer  │
│ (FlashAlpha)     │ │ (Vol Ratio)      │ │ (EMA, RSI)       │
└──────────────────┘ └──────────────────┘ └──────────────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              ▼
        ┌─────────────────────────────────────────┐
        │   Validation Layer (validators/)         │
        │  ✓ options_validator.py                  │
        │  ✓ sec_verifier.py                       │
        │  ✓ telegram_notifier.py                  │
        └─────────────────────────────────────────┘
                              ▼
        ┌─────────────────────────────────────────┐
        │   Signal Scoring & Fusion               │
        │  • Multi-source confidence              │
        │  • Catalyst ranking                     │
        │  • Arabic alert generation              │
        └─────────────────────────────────────────┘
                              ▼
        ┌─────────────────────────────────────────┐
        │   Telegram Delivery                     │
        │  • Deduplication check                  │
        │  • Message ID tracking                  │
        │  • Retry logic                          │
        └─────────────────────────────────────────┘
```

---

## Core Engines

### 1. Gamma & Liquidity Engine (GEX)

**Provider:** FlashAlpha SDK (free tier)

**Concept:**
- Dealer gamma exposure (GEX) indicates how much dealers are short/long gamma
- Negative GEX suggests potential squeeze (dealers hedging = protective buying)
- Positive GEX suggests structural resistance (dealers hedging = protective selling)

**Implementation:**
```python
from flashalpha import FlashAlpha

fa = FlashAlpha(api_key="YOUR_API_KEY")
gex_data = fa.gex("SPY")  # Returns: net_gex, gamma_flip, max_pain

# Integrate into signal:
if gex_data['net_gex'] < -5_000_000:  # Dealer short gamma
    catalyst_strength = "GAMMA_SQUEEZE"  # High risk/reward potential
```

**Threshold Configuration:**
- **Gamma Squeeze:** GEX < -5M (strong dealer short gamma)
- **Gamma Resistance:** GEX > 5M (strong dealer long gamma)
- **Neutral:** -5M to 5M

### 2. Unusual Volume & Flow Detector

**Provider:** Real-time data + statistical anomaly detection

**Concept:**
- Volume ratio = current_option_volume / 20-day_average_volume
- Smart money often trades unusual size before institutional moves
- High flow with low spread indicates institutional activity

**Implementation:**
```python
# Detect unusual volume
volume_ratio = current_volume / historical_avg_volume
if volume_ratio >= 3.0:
    catalyst_strength = "UNUSUAL_VOLUME"  # 3x+ typical volume

# Detect unusual flow
call_volume = calls_traded
put_volume = puts_traded
flow_ratio = call_volume / put_volume if put_volume > 0 else 0
if flow_ratio > 2.0:  # Call-heavy
    catalyst_strength = "CALL_FLOW"
```

**Thresholds:**
- **Unusual Volume:** Volume > 3x 20-day average
- **Call Flow:** Call volume > 2x Put volume
- **Put Flow:** Put volume > 2x Call volume
- **Smart Money:** Volume >> Open Interest in single 5-minute bar

### 3. Chart Analysis & Technical Signals

**Provider:** pandas-ta (internal EMA/RSI calculations)

**Concept:**
- Multi-timeframe confirmation (1D, 1H, 15m)
- Trend direction via EMA alignment
- Momentum via RSI and relative strength
- Support/resistance via key levels

**Implementation:**
```python
# Calculate exponential moving averages
ema_9 = SignalGenerator._ema(closes, 9)   # Fast
ema_21 = SignalGenerator._ema(closes, 21)  # Slow

# Determine trend
bullish = ema_9 > ema_21 and closes[-1] >= closes[-2]
bearish = ema_9 < ema_21 and closes[-1] <= closes[-2]

# Select contract type
direction = "CALL" if bullish else "PUT" if bearish else None
```

**Signals:**
- **Golden Cross:** EMA 9 > EMA 21 + closing above EMA 21 = Bullish
- **Death Cross:** EMA 9 < EMA 21 + closing below EMA 21 = Bearish
- **RSI Extremes:** RSI < 30 (oversold), RSI > 70 (overbought)
- **IV Rank:** Current IV / (52-week high IV) - ranks from 0 to 100

### 4. Strike & Expiration Selector

**Concept:**
- Strike selection based on technical levels + gamma concentration
- Expiration based on catalyst timing and momentum

**Strike Logic:**
```
1. Calculate ATM strike (nearest to underlying price)
2. Identify support/resistance levels from technical analysis
3. Score strikes by:
   - Distance to key levels
   - Gamma concentration
   - Bid/Ask spread (liquidity)
   - Delta (probability of touch)
4. Return top 3 candidates
```

**Expiration Logic:**
```
IF catalyst_timing < 4 hours AND valid_0dte_available:
    return "0DTE" (same day)
ELSIF momentum_strength > 0.8 OR intraday_setup:
    return "Weekly" (5-14 DTE)
ELSE:
    return "Monthly" (15-45 DTE)
```

---

## Integration Points

### 1. Validators Layer

All quotes pass through **three validation stages:**

#### Stage 1: Options Validator (options_validator.py)
```python
from validators.options_validator import OptionsValidator, DataSource

validator = OptionsValidator()
result = validator.validate(
    symbol="AAPL",
    contract_type="CALL",
    expiration="2026-10-10",
    strike_price=150.0,
    bid=2.10,
    ask=2.20,
    source=DataSource.LIVE_OPRA,
    last_trade_timestamp=datetime.now(timezone.utc),
)

if not result.decision_authority:
    return None  # Reject signal
```

#### Stage 2: SEC Verifier (sec_verifier.py)
```python
from validators.sec_verifier import SECVerifier

verifier = SECVerifier()
result = verifier.verify(
    symbol="AAPL",
    company_name="Apple Inc."
)

if result.confidence_score < 0.85:
    return None  # Research only
```

#### Stage 3: Telegram Notifier (telegram_notifier.py)
```python
from validators.telegram_notifier import TelegramNotifier

notifier = TelegramNotifier(
    token="YOUR_BOT_TOKEN",
    chat_id="YOUR_CHAT_ID"
)

message = notifier.send(
    text=alert_text,
    content_lineage={"source": "FlashAlpha", "timestamp": now},
    disable_web_preview=True
)
```

### 2. Data Provider Adapters

Implement provider adapters to normalize quotes:

```python
class FinnhubProvider:
    def quote(self, symbol: str) -> dict:
        """Return normalized quote dict."""
        return {
            "symbol": symbol,
            "bid": 150.10,
            "ask": 150.15,
            "last": 150.12,
            "quote_timestamp": datetime.now(timezone.utc),
            "source": "live_opra",
        }

class PolygonProvider:
    def quote(self, symbol: str) -> dict:
        """Return normalized quote dict."""
        # ...
```

---

## API Reference

### SignalGenerator.generate()

```python
def generate(
    self,
    *,
    quote: Mapping[str, Any],           # Normalized quote dict
    bars: Sequence[Mapping[str, float]], # OHLCV bars (min 2 required)
    sec_verification: Mapping[str, Any], # SEC verifier output
    gex: float = 0.0,                   # Gamma exposure (optional)
    flow: float = 0.0,                  # Flow ratio (optional)
    volume_ratio: float = 0.0,          # Volume / 20-day avg (optional)
    now: datetime | None = None,        # Current time (uses now() if None)
) -> Signal | None:
    """Generate a scored, qualified signal or return None if rejected."""
```

**Returns:**
```python
@dataclass(frozen=True)
class Signal:
    symbol: str                     # "AAPL"
    direction: str                  # "CALL" or "PUT"
    strike: float                   # 150.0
    expiration: str                 # "2026-10-10"
    horizon: str                    # "0DTE", "Weekly", "Monthly"
    target: float                   # 152.50
    score: float                    # 75.3 (0-100)
    decision_authority: bool        # True if all checks pass
    catalysts: tuple[str, ...]      # ("تدفق CALL قوي", "Gamma Squeeze")
    data_lineage: Mapping           # Source tracking
    rejection_reasons: tuple[str]   # Why signal was rejected
```

---

## Usage Examples

### Example 1: Real-time Signal Generation

```python
from engines.signal_generator import SignalGenerator
from validators.options_validator import OptionsValidator
from datetime import datetime, timezone

# Initialize
validator = OptionsValidator()
generator = SignalGenerator(options_validator=validator)

# Get real-time data (from Finnhub or IEX)
quote = {
    "symbol": "AAPL",
    "contract_type": "CALL",
    "strike": 150.0,
    "bid": 2.10,
    "ask": 2.20,
    "last": 2.15,
    "expiration": "2026-10-10",
    "source": "live_opra",
    "quote_timestamp": datetime.now(timezone.utc),
}

# Get historical bars (last 100 candles, 1H timeframe)
bars = [
    {"close": 148.5},
    {"close": 149.2},
    {"close": 150.1},
    # ... more bars
]

# Get analytics
sec_result = verifier.verify("AAPL", "Apple Inc.")
gex_data = fa.gex("AAPL")

# Generate signal
signal = generator.generate(
    quote=quote,
    bars=bars,
    sec_verification={"confidence_score": sec_result.confidence_score},
    gex=gex_data["net_gex"],
    flow=1.5,  # Call-heavy flow
    volume_ratio=3.2,  # 3.2x normal volume
)

if signal and signal.decision_authority:
    print(signal.to_alert())  # Print Arabic alert
```

### Example 2: Backtesting with Historical Data

```python
import pandas as pd
from datetime import datetime, timedelta

# Load historical data
df = pd.read_csv("aapl_historical.csv")
signals = []

for i in range(100, len(df)):
    bars = [
        {"close": row["close"]}
        for _, row in df.iloc[i-100:i].iterrows()
    ]
    
    quote = {
        "symbol": "AAPL",
        "contract_type": "CALL",
        "strike": df.iloc[i]["close"],
        "bid": df.iloc[i]["close"] - 0.10,
        "ask": df.iloc[i]["close"] + 0.10,
        "expiration": (df.iloc[i]["date"] + timedelta(days=7)).isoformat(),
        "source": "research_data",  # Not real-time
        "quote_timestamp": df.iloc[i]["date"],
    }
    
    signal = generator.generate(
        quote=quote,
        bars=bars,
        sec_verification={"confidence_score": 0.95},
        flow=0.5,
    )
    
    if signal:
        signals.append(signal)

print(f"Generated {len(signals)} signals over {len(df)} periods")
```

---

## Testing Strategy

### Unit Tests (test_signal_generator.py)

1. **Test Decision Authority Gates:**
   - ✅ Approve live_opra + spread ≤ 5% + SEC ≥ 0.85
   - ❌ Reject yahoo/yfinance source
   - ❌ Reject spread > 5%
   - ❌ Reject SEC confidence < 0.85

2. **Test Catalyst Detection:**
   - ✅ Gamma squeeze detected (GEX < -5M)
   - ✅ Unusual volume detected (ratio > 3x)
   - ✅ Flow direction detected (CALL/PUT bias)

3. **Test Signal Scoring:**
   - ✅ Score increases with evidence count
   - ✅ Score capped at 100
   - ✅ Score below min_score rejected

4. **Test Arabic Alert Generation:**
   - ✅ Contains ticker, strike, expiration
   - ✅ Contains Arabic catalysts
   - ✅ Contains decision_authority status

### Integration Tests

1. **End-to-End Signal Pipeline:**
   - Mock Finnhub API
   - Mock FlashAlpha API
   - Verify signal generation
   - Verify Telegram delivery

2. **Provider Fallback:**
   - Finnhub fails → IEX Cloud
   - IEX fails → Alpha Vantage
   - All fail → Reject quote

3. **Deduplication:**
   - Send same signal twice
   - Verify second is deduplicated

### Regression Tests

1. **Historical Backtesting:**
   - Replay last 30 days of known catalysts
   - Measure false positive rate
   - Compare hit rate vs announced moves

2. **Performance Benchmarks:**
   - Signal generation < 500ms
   - Telegram delivery < 2s
   - API rate limits respected

---

## Deployment Checklist

- [ ] Obtain API keys:
  - [ ] Finnhub (free tier: https://finnhub.io)
  - [ ] FlashAlpha (free tier: https://flashalpha.com)
  - [ ] IEX Cloud (optional fallback: https://iexcloud.io)
  - [ ] SEC Edgar (public API, no key needed)

- [ ] Set environment variables:
  ```bash
  export FINNHUB_API_KEY="your_key"
  export FLASHALPHA_API_KEY="your_key"
  export TELEGRAM_BOT_TOKEN="your_token"
  export TELEGRAM_CHAT_ID="your_chat_id"
  ```

- [ ] Install dependencies:
  ```bash
  pip install -r requirements.txt
  ```

- [ ] Run tests:
  ```bash
  pytest tests/test_signal_generator.py -v --cov
  ```

- [ ] Backtest (optional):
  ```bash
  python scripts/backtest_signal_generator.py
  ```

- [ ] Deploy to production:
  ```bash
  git checkout feature/financial-room-validators
  git push origin feature/financial-room-validators
  # Create Pull Request on GitHub
  ```

---

## References

1. **Gamma Exposure (GEX):**
   - GammaGrid: https://github.com/gammagrid/gammagrid
   - FlashAlpha: https://github.com/FlashAlpha-lab/awesome-options-analytics
   - GEX Tracker: https://matteo-ferrara.github.io/gex-tracker/

2. **Unusual Volume Detection:**
   - KPH3802/options-volume-scanner: https://github.com/KPH3802/options-volume-scanner
   - Orthogonal Trading: https://orthogonal.info/unusual-options-activity-scanner-python-free/

3. **Technical Analysis:**
   - pandas-ta: https://github.com/twopirllc/pandas-ta
   - TA-Lib: https://github.com/TA-Lib/ta-lib

4. **Market Data APIs:**
   - Finnhub: https://finnhub.io/docs/api/
   - IEX Cloud: https://iexcloud.io/docs/
   - Alpha Vantage: https://alphavantage.co/
   - Polygon.io: https://polygon.io/

5. **Options Analysis:**
   - CBOE Volatility Surface: https://www.cboe.com/us/options/symboldir/
   - Options Pricing (Black-Scholes): https://en.wikipedia.org/wiki/Black%E2%80%93Scholes_model

---

**End of Technical Guide**
