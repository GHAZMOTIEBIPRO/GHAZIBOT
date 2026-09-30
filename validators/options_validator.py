"""Options Validator Module for BLACK BOX Trading System.

Validates live option prices with strict requirements:
- Bid/Ask spread ≤ 5%
- Data freshness < 5 seconds
- Rejects all yfinance/Yahoo Finance data
- Returns decision_authority status with full data lineage tracking
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class DataSource(Enum):
    """Supported data sources for options validation."""
    LIVE_OPRA = "live_opra"  # Production-ready
    MARKET_DATA_FEED = "market_data_feed"  # Real-time provider
    ACCOUNT_FEED = "account_feed"  # Broker account data
    YFINANCE = "yfinance"  # Explicitly rejected
    YAHOO = "yahoo"  # Explicitly rejected
    DELAYED = "delayed"  # Research only
    INDICATIVE = "indicative"  # Research only
    UNKNOWN = "unknown"  # Default rejection


class ValidationStatus(Enum):
    """Validation outcome statuses."""
    APPROVED = "approved"  # decision_authority = True
    REJECTED = "rejected"  # decision_authority = False
    RESEARCH_ONLY = "research_only"  # Usable for research, not execution


@dataclass
class DataLineage:
    """Complete data lineage tracking for audit and compliance."""
    source: DataSource
    feed_name: Optional[str] = None
    provider_id: Optional[str] = None
    fetch_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_trade_timestamp: Optional[datetime] = None
    data_freshness_ms: Optional[float] = None
    quote_age_seconds: Optional[float] = None
    confidence_level: str = "UNAVAILABLE"  # LIVE / ACCOUNT / RESEARCH / UNAVAILABLE
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "feed_name": self.feed_name,
            "provider_id": self.provider_id,
            "fetch_timestamp": self.fetch_timestamp.isoformat(),
            "last_trade_timestamp": self.last_trade_timestamp.isoformat() if self.last_trade_timestamp else None,
            "data_freshness_ms": self.data_freshness_ms,
            "quote_age_seconds": self.quote_age_seconds,
            "confidence_level": self.confidence_level,
        }


@dataclass
class ValidatorResult:
    """Structured validation result with decision authority."""
    decision_authority: bool  # True only if ALL checks pass
    status: ValidationStatus
    symbol: str
    contract_type: str  # CALL or PUT
    expiration: str  # YYYY-MM-DD
    strike_price: float
    bid: float
    ask: float
    last: Optional[float] = None
    bid_ask_spread_pct: Optional[float] = None
    spread_acceptable: bool = False
    data_freshness_acceptable: bool = False
    source_acceptable: bool = False
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    implied_volatility: Optional[float] = None
    lineage: DataLineage = field(default_factory=DataLineage)
    rejection_reasons: list[str] = field(default_factory=list)
    validation_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["lineage"] = self.lineage.to_dict()
        result["validation_timestamp"] = self.validation_timestamp.isoformat()
        result["status"] = self.status.value
        return result
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


class OptionsValidator:
    """Validates options quotes against production-grade criteria."""
    
    # Configuration constants
    MAX_BID_ASK_SPREAD_PCT = 5.0  # Maximum acceptable spread percentage
    MAX_DATA_FRESHNESS_SECONDS = 5.0  # Maximum acceptable age
    REJECTED_SOURCES = {DataSource.YFINANCE, DataSource.YAHOO, DataSource.UNKNOWN}
    PRODUCTION_SOURCES = {DataSource.LIVE_OPRA, DataSource.MARKET_DATA_FEED, DataSource.ACCOUNT_FEED}
    
    def __init__(self, audit_log_path: Optional[Path] = None):
        """Initialize validator with optional audit logging.
        
        Args:
            audit_log_path: Path to directory for validation audit logs
        """
        self.audit_log_path = audit_log_path or Path("data/audit/options_validation")
        self.audit_log_path.mkdir(parents=True, exist_ok=True)
    
    def validate(
        self,
        symbol: str,
        contract_type: str,  # CALL or PUT
        expiration: str,  # YYYY-MM-DD
        strike_price: float,
        bid: float,
        ask: float,
        last: Optional[float] = None,
        volume: Optional[int] = None,
        open_interest: Optional[int] = None,
        implied_volatility: Optional[float] = None,
        source: DataSource = DataSource.UNKNOWN,
        feed_name: Optional[str] = None,
        provider_id: Optional[str] = None,
        last_trade_timestamp: Optional[datetime] = None,
    ) -> ValidatorResult:
        """Validate an options contract quote.
        
        Args:
            symbol: Stock ticker (e.g., 'AAPL')
            contract_type: 'CALL' or 'PUT'
            expiration: Expiration date YYYY-MM-DD
            strike_price: Strike price
            bid: Current bid price
            ask: Current ask price
            last: Last trade price (optional)
            volume: Current volume (optional)
            open_interest: Open interest (optional)
            implied_volatility: IV (optional)
            source: Data source provider
            feed_name: Name of data feed
            provider_id: Provider identifier
            last_trade_timestamp: Time of last trade
        
        Returns:
            ValidatorResult with decision_authority status
        """
        rejection_reasons = []
        now = datetime.now(timezone.utc)
        
        # Initialize lineage
        lineage = DataLineage(
            source=source,
            feed_name=feed_name,
            provider_id=provider_id,
            fetch_timestamp=now,
            last_trade_timestamp=last_trade_timestamp,
        )
        
        # Check 1: Reject explicitly blocked sources
        source_acceptable = True
        if source in self.REJECTED_SOURCES:
            source_acceptable = False
            rejection_reasons.append(
                f"Data source '{source.value}' is explicitly rejected. "
                f"Only {[s.value for s in self.PRODUCTION_SOURCES]} are acceptable."
            )
        
        # Check 2: Calculate and validate Bid/Ask spread
        spread_acceptable = False
        bid_ask_spread_pct = None
        
        if bid > 0 and ask > 0 and ask >= bid:
            bid_ask_spread_pct = ((ask - bid) / bid) * 100 if bid != 0 else 0
            
            if bid_ask_spread_pct <= self.MAX_BID_ASK_SPREAD_PCT:
                spread_acceptable = True
            else:
                rejection_reasons.append(
                    f"Bid/Ask spread {bid_ask_spread_pct:.2f}% exceeds maximum {self.MAX_BID_ASK_SPREAD_PCT}%. "
                    f"Bid=${bid:.2f}, Ask=${ask:.2f}"
                )
        else:
            rejection_reasons.append(
                f"Invalid bid/ask prices: bid=${bid}, ask=${ask}. "
                f"Require: bid > 0, ask > 0, ask >= bid"
            )
        
        # Check 3: Validate data freshness
        data_freshness_acceptable = False
        data_freshness_ms = None
        quote_age_seconds = None
        
        if last_trade_timestamp:
            age = now - last_trade_timestamp
            quote_age_seconds = age.total_seconds()
            data_freshness_ms = age.total_seconds() * 1000
            lineage.data_freshness_ms = data_freshness_ms
            lineage.quote_age_seconds = quote_age_seconds
            
            if quote_age_seconds <= self.MAX_DATA_FRESHNESS_SECONDS:
                data_freshness_acceptable = True
            else:
                rejection_reasons.append(
                    f"Quote age {quote_age_seconds:.1f}s exceeds maximum {self.MAX_DATA_FRESHNESS_SECONDS}s. "
                    f"Last trade: {last_trade_timestamp.isoformat()}"
                )
        else:
            rejection_reasons.append(
                "No last_trade_timestamp provided. Cannot verify data freshness."
            )
        
        # Determine confidence level based on source
        if source in self.PRODUCTION_SOURCES:
            lineage.confidence_level = "LIVE"
        elif source == DataSource.DELAYED:
            lineage.confidence_level = "RESEARCH"
        elif source == DataSource.INDICATIVE:
            lineage.confidence_level = "RESEARCH"
        else:
            lineage.confidence_level = "UNAVAILABLE"
        
        # Determine overall status
        decision_authority = (
            source_acceptable and 
            spread_acceptable and 
            data_freshness_acceptable
        )
        
        if decision_authority:
            status = ValidationStatus.APPROVED
        elif lineage.confidence_level == "RESEARCH":
            status = ValidationStatus.RESEARCH_ONLY
        else:
            status = ValidationStatus.REJECTED
        
        # Create result
        result = ValidatorResult(
            decision_authority=decision_authority,
            status=status,
            symbol=symbol,
            contract_type=contract_type,
            expiration=expiration,
            strike_price=strike_price,
            bid=bid,
            ask=ask,
            last=last,
            bid_ask_spread_pct=bid_ask_spread_pct,
            spread_acceptable=spread_acceptable,
            data_freshness_acceptable=data_freshness_acceptable,
            source_acceptable=source_acceptable,
            volume=volume,
            open_interest=open_interest,
            implied_volatility=implied_volatility,
            lineage=lineage,
            rejection_reasons=rejection_reasons,
            validation_timestamp=now,
        )
        
        # Log to audit trail
        self._log_validation(result)
        
        logger.info(
            f"Validated {symbol} {contract_type} {expiration} ${strike_price}: "
            f"decision_authority={decision_authority}, status={status.value}, "
            f"source={source.value}"
        )
        
        return result
    
    def _log_validation(self, result: ValidatorResult) -> None:
        """Write validation result to audit log.
        
        Args:
            result: ValidatorResult to log
        """
        try:
            timestamp = result.validation_timestamp.strftime("%Y%m%d_%H%M%S")
            log_file = self.audit_log_path / f"validation_{timestamp}_{result.symbol}.json"
            log_file.write_text(result.to_json(), encoding="utf-8")
        except Exception as exc:
            logger.error(f"Failed to write audit log: {exc}")
    
    def batch_validate(
        self,
        quotes: list[dict[str, Any]]
    ) -> list[ValidatorResult]:
        """Validate multiple option quotes.
        
        Args:
            quotes: List of quote dictionaries with validation parameters
        
        Returns:
            List of ValidatorResult objects
        """
        results = []
        for quote in quotes:
            try:
                result = self.validate(**quote)
                results.append(result)
            except Exception as exc:
                logger.error(f"Validation error for quote {quote.get('symbol')}: {exc}")
        return results
