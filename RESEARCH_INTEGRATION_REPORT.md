# BLACK BOX - R&D Integration Report
## Financial Room Engine Architecture

**Date:** 2026-09-30  
**Author:** BLACK BOX Development Team  
**Status:** Research & Design Document  
**Version:** 1.0

---

## Executive Summary

This report documents open-source projects and tools recommended for integration into the BLACK BOX system. The goal is to build a production-grade **Signal Generator Engine** that:

1. Calculates **Gamma Exposure (GEX)** and **Max Pain**
2. Detects **Unusual Options Activity** (volume spikes, IV increases)
3. Performs **Technical Analysis** (RSI, SMA, trend detection)
4. Fetches **Real-time data** (free, independent of yfinance)
5. Generates **Arabic alerts** with full data lineage and deduplication

---

## 1. Gamma & Liquidity Engine (GEX & Order Flow)

### Recommended Projects

#### 🏆 **Primary: FlashAlpha SDK** (Free Tier)
- **URL:** https://github.com/FlashAlpha-lab/awesome-options-analytics
- **Install:** `pip install flashalpha`
- **Features:**
  - Per-strike gamma exposure calculation
  - Gamma flip detection (dealer regime change)
  - Call/Put walls identification
  - Max pain calculation
  - Open Interest aggregation
  - Confidence-tagged data (LIVE vs RESEARCH)
- **API Usage Example:**
  ```python
  from flashalpha import FlashAlpha
  fa = FlashAlpha(api_key="YOUR_KEY")
  gex = fa.gex("SPY")
  # Returns: net_gex, gamma_flip, dealer_regime, confidence
  ```
- **Why:** Production-ready, free tier, confidence grading built-in

#### 🥈 **Secondary: GammaGrid**
- **URL:** https://github.com/gammagrid/gammagrid
- **Features:** Dashboard + open-source code, self-hosted option
- **Why:** Reference implementation, good for backtesting

#### 🥉 **Tertiary: gex-terminal**
- **URL:** https://github.com/zrack/gex-terminal
- **Features:** Lightweight CLI for intraday GEX
- **Why:** Minimal dependencies, good for CLI integrations

### Data Lineage & Confidence
- All GEX sources will be tagged:
  - `LIVE`: Real options data (decision_authority eligible)
  - `RESEARCH`: Delayed or reconstructed data (research only)
  - `UNAVAILABLE`: No data (reject)

---

## 2. Unusual Options Activity Detector

### Recommended Projects

#### 🏆 **Primary: options-volume-scanner**
- **URL:** https://github.com/KPH3802/options-volume-scanner
- **Features:**
  - Monitors unusual volume across SPX 500
  - Statistical anomaly detection (std dev thresholds)
  - Day-of-week adjustment
  - Earnings window awareness
  - SQLite state persistence
- **Integration:**
  ```python
  from options_scanner import AnomalyDetector
  detector = AnomalyDetector(lookback_days=20)
  unusual = detector.find_unusual_contracts(ticker="AAPL")
  # Returns: [contracts with vol > 3x 20-day avg]
  ```

#### 🥈 **Secondary: FlashAlpha SDK (Flow Signals)**
- **Unusual Flow:** Deep money flows, smart money detection
- **IV Spike Detection:** Built-in IV ranking
- **Why:** Complementary to volume detection

### Threshold Definitions (Configurable)
- **Unusual Volume:** vol > 3x 20-day average
- **Unusual Open Interest:** OI change > 50% in single day
- **High IV Rank:** IV percentile > 80th
- **Volume/OI Ratio:** Unusual when vol > OI (institutional flow)

---

## 3. Chart Analysis & Strike Selection Engine

### Recommended Projects

#### 🏆 **Primary: pandas-ta (Pure Python)**
- **URL:** https://github.com/twopirllc/pandas-ta
- **Install:** `pip install pandas-ta`
- **Features:**
  - 150+ indicators (RSI, SMA, EMA, MACD, Bollinger Bands, etc.)
  - No C-compiler required (unlike TA-Lib)
  - Pandas DataFrame integration
  - Active maintenance
- **Key Indicators:**
  ```python
  import pandas_ta as ta
  
  df['rsi_14'] = ta.rsi(df['close'], length=14)
  df['sma_20'] = ta.sma(df['close'], length=20)
  df['bb'] = ta.bbands(df['close'], length=20)
  df['macd'] = ta.macd(df['close'])
  ```

#### 🥈 **Secondary: TA-Lib (Legacy)**
- **Why:** Established, but harder to install (needs C compiler)
- **Use:** If already compiled in production

### Strike Selection Logic
```
1. Identify trend direction (EMA 9 vs EMA 21)
2. Find key support/resistance levels
3. Identify ATM (at-the-money) strike
4. Score alternative strikes by:
   - Distance to key levels
   - Gamma concentration
   - Liquidity (bid/ask spread)
   - Probability of Touch (using Delta)
5. Return top 3 candidate strikes with confidence scores
```

### Expiration Selection
```
Momentum / Catalyst Timing:
  - If immediate catalyst (< 4 hours): 0DTE
  - If intraday momentum (4-24 hrs): Weekly (next Friday)
  - If structural setup (1-5 days): Monthly
  - If longer-term thesis: 30-45 DTE
```

---

## 4. Real-time Data Ingestion (Free, Fast, yfinance-independent)

### Recommended Hierarchy

#### ✅ **Tier 1: Finnhub** (Best for US options)
- **URL:** https://finnhub.io
- **Features:**
  - Real-time US stock + options quotes
  - 60 requests/minute free tier
  - Low latency, reliable
  - Python SDK: `pip install finnhub-client`
- **Example:**
  ```python
  import finnhub
  client = finnhub.Client(api_key="YOUR_KEY")
  quote = client.quote("AAPL")
  # Returns: {'c': 150.23, 'h': 151.5, 'l': 149.8, 'pc': 149.5, 't': 1234567890}
  ```

#### ✅ **Tier 2: IEX Cloud** (US stocks, good free tier)
- **URL:** https://iexcloud.io
- **Features:**
  - Real-time US equity data
  - 50k messages/month free
  - Python SDK: `pip install iexfinance`

#### ✅ **Tier 3: Alpha Vantage** (Global fallback)
- **URL:** https://alphavantage.co
- **Features:**
  - Global equities, crypto, forex
  - 5 requests/minute free tier
  - Lower latency than yfinance

#### ✅ **Tier 4: Polygon.io** (Paid, but excellent options data)
- **URL:** https://polygon.io
- **Features:**
  - Real-time options chains
  - Tick-level data
  - Best for options flow analysis

### Implementation Strategy
```
decision_authority flow:
  1. Try Finnhub (primary, fastest)
  2. On failure: Fallback to IEX Cloud
  3. On failure: Fallback to Alpha Vantage
  4. On all failures: Reject quote, log event
  5. NEVER use yfinance for decision_authority = True
```

---

## 5. Arabic Alerting & Catalyst Engine

### Alert Structure (Telegram HTML Format)

```html
<b>🎯 CALL Signal: AAPL</b>
━━━━━━━━━━━━━━━━━━━━━

<b>الهدف (Target):</b> $160 - $165
<b>العقد (Contract):</b> CALL | Strike: $155 | Exp: 2026-10-10

<b>الأسباب (Catalysts):</b>
📊 Gamma Squeeze: 25M dealer gamma short
💰 Smart Money: $8.3M call flow in 2 mins
📈 Technical: RSI 28 + Price > SMA20
🔥 Unusual Volume: 450K contracts (3.2x avg)

<b>البيانات (Data Source):</b>
🔗 Source: Finnhub Real-Time + FlashAlpha GEX
⏱️ Freshness: &lt;2 seconds
✓ decision_authority: TRUE

<b>رقم الرسالة (Message ID):</b> #TG_12345678
━━━━━━━━━━━━━━━━━━━━━
```

### Catalyst Classification
- **🔥 Gamma Squeeze:** Net GEX < -5M and gamma flip detected
- **💰 Smart Flow:** Volume >> OpenInterest in 5min window
- **📈 Technical:** Multi-timeframe alignment (1D/1H/15m)
- **📊 High IV:** IV rank > 80th percentile + spike detection
- **🎯 Support/Resistance:** Price bounce at technical levels

---

## 6. Integration Architecture

```
┌─────────────────────────────────────────────────────────┐
│           Signal Generator Engine                       │
│  (engines/signal_generator.py)                          │
└─────────────────────────────────────────────────────────┘
         │              │              │              │
         ▼              ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ GEX Engine   │ │ Volume Flow  │ │Chart Analysis│ │ Data Feeder  │
│(FlashAlpha)  │ │(options-vol) │ │(pandas-ta)   │ │(Finnhub API) │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
         │              │              │              │
         └──────────────┼──────────────┼──────────────┘
                        ▼
        ┌───────────────────────────────────────┐
        │    Signal Fusion & Scoring            │
        │  (Multi-source confidence calc)       │
        └───────────────────────────────────────┘
                        ▼
        ┌───────────────────────────────────────┐
        │   validators/ (Validation Layer)      │
        │  ✓ options_validator.py               │
        │  ✓ sec_verifier.py                    │
        │  ✓ telegram_notifier.py               │
        └───────────────────────────────────────┘
                        ▼
        ┌───────────────────────────────────────┐
        │   Telegram Delivery                   │
        │  (No duplicates, Message ID tracking) │
        └───────────────────────────────────────┘
```

---

## 7. Dependencies Summary

### Core Libraries

```
# Financial Data & Analysis
flashalpha>=0.1.5          # GEX and gamma exposure
pandas-ta>=0.3.14b         # Technical indicators
finnhub-client>=1.3.0      # Real-time data
iexfinance>=0.5.0          # Fallback data (IEX Cloud)
alpha_vantage>=2.3.1       # Fallback data (Alpha Vantage)

# Data Processing
pandas>=1.3.0              # DataFrames
numpy>=1.21.0              # Numerical computing

# HTTP & APIs
requests>=2.28.0           # HTTP client with retry logic
urllib3>=1.26.0            # URL utilities

# Existing (already in repo)
python-telegram-bot>=13.0  # Telegram integration
```

### Optional (For advanced features)

```
# Backtesting
backtrader>=1.9.76         # Backtest signal quality
zipline-reloaded>=2.1.0    # Research framework

# Machine Learning
scikit-learn>=1.0.0        # Anomaly detection models
xgboost>=1.5.0             # Ensemble models
```

---

## 8. Validation & Data Lineage

All signals must satisfy:

### decision_authority = True Requirements
1. ✅ **Data Source:** Only LIVE feeds (Finnhub, IEX, FlashAlpha with LIVE tag)
2. ✅ **Freshness:** Quote age < 5 seconds
3. ✅ **Options Validation:** Bid/Ask spread ≤ 5%
4. ✅ **Company Name:** SEC verification (confidence > 0.85)
5. ✅ **Catalyst Count:** Minimum 2 independent signals aligned

### Signal Rejection
- Single source data → Research only
- Bid/Ask spread > 5% → Research only
- Quote age > 5 seconds → Reject
- yfinance or Yahoo Finance → Always reject
- Confidence score < 0.7 → Research only

---

## 9. Testing Strategy

### Unit Tests
- Test each engine (GEX, Volume, Chart) independently
- Mock API responses
- Validate confidence scoring logic

### Integration Tests
- End-to-end signal generation
- Deduplication verification
- Telegram delivery simulation

### Regression Tests
- Historical backtesting (last 30 days of known signals)
- False positive rate measurement
- Hit rate vs announced catalysts

---

## 10. Next Steps

1. ✅ Create `engines/signal_generator.py` (master orchestrator)
2. ✅ Write integration tests in `tests/test_signal_generator.py`
3. ✅ Add external dependencies to `requirements.txt`
4. ✅ Create Pull Request from `feature/financial-room-validators`
5. ⬜ Obtain API keys (Finnhub, FlashAlpha free tier)
6. ⬜ Deploy to staging and backtest against historical data
7. ⬜ Set up GitHub Actions for continuous signal validation

---

## References

1. **GammaGrid:** https://github.com/gammagrid/gammagrid
2. **FlashAlpha:** https://github.com/FlashAlpha-lab/awesome-options-analytics
3. **options-volume-scanner:** https://github.com/KPH3802/options-volume-scanner
4. **pandas-ta:** https://github.com/twopirllc/pandas-ta
5. **Finnhub Docs:** https://finnhub.io/docs/api/
6. **IEX Cloud Docs:** https://iexcloud.io/docs/
7. **Alpha Vantage:** https://alphavantage.co/
8. **Polygon.io:** https://polygon.io/

---

**End of Report**
