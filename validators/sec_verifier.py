"""SEC/EDGAR Verification Module for BLACK BOX Trading System.

Verifies company names against SEC/EDGAR to ensure trading accuracy
and prevent pump-and-dump or ticker confusion attacks.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional
from pathlib import Path
import hashlib

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    requests = None

logger = logging.getLogger(__name__)


@dataclass
class SECVerificationResult:
    """Result of SEC/EDGAR company verification."""
    symbol: str
    provided_name: str
    sec_legal_name: Optional[str] = None
    cik: Optional[str] = None
    confidence_score: float = 0.0  # 0.0 to 1.0
    is_match: bool = False  # True if names match (high confidence)
    match_type: str = "unknown"  # exact, fuzzy, mismatch, not_found
    sec_entity_type: Optional[str] = None
    sec_ticker: Optional[str] = None
    sec_filing_date: Optional[str] = None
    cik_url: Optional[str] = None
    verification_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated_sec: Optional[str] = None
    error_message: Optional[str] = None
    data_source: str = "SEC_EDGAR"  # Data lineage
    cache_hit: bool = False  # Whether result came from cache
    
    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["verification_timestamp"] = self.verification_timestamp.isoformat()
        return result
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


class SECVerifier:
    """Verifies stock symbols and company names against SEC/EDGAR database."""
    
    # SEC/EDGAR API endpoints
    SEC_COMPANY_SEARCH_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
    SEC_CIK_LOOKUP_URL = "https://www.sec.gov/files/company_tickers.json"
    
    # Configuration
    CONFIDENCE_EXACT_MATCH = 1.0
    CONFIDENCE_FUZZY_MATCH = 0.85
    CONFIDENCE_NO_MATCH = 0.0
    REQUEST_TIMEOUT = 10
    MAX_RETRIES = 3
    
    def __init__(
        self,
        cache_path: Optional[Path] = None,
        use_cache: bool = True,
    ):
        """Initialize SEC verifier.
        
        Args:
            cache_path: Path to cache directory for SEC data
            use_cache: Whether to use local cache
        """
        self.cache_path = cache_path or Path("data/cache/sec_verification")
        self.use_cache = use_cache
        if self.use_cache:
            self.cache_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize session with retries
        self.session = self._create_session()
        self._ticker_cache = {}
    
    def _create_session(self) -> requests.Session:
        """Create requests session with retry strategy."""
        if requests is None:
            logger.warning("requests library not available. SEC verification will be limited.")
            return None
        
        session = requests.Session()
        retry_strategy = Retry(
            total=self.MAX_RETRIES,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({
            "User-Agent": "BLACK-BOX-Verifier/1.0 (Trading System Validation)"
        })
        return session
    
    def verify(
        self,
        symbol: str,
        company_name: Optional[str] = None,
        use_cache_override: bool = False,
    ) -> SECVerificationResult:
        """Verify a stock symbol and company name against SEC/EDGAR.
        
        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL')
            company_name: Company legal name to verify against
            use_cache_override: Force fresh lookup despite cache
        
        Returns:
            SECVerificationResult with confidence score
        """
        symbol_upper = symbol.upper().strip()
        
        # Check cache first
        if self.use_cache and not use_cache_override:
            cached = self._get_from_cache(symbol_upper)
            if cached:
                cached.cache_hit = True
                logger.info(f"SEC verification cache hit for {symbol_upper}")
                return cached
        
        # Fetch from SEC/EDGAR
        try:
            result = self._fetch_from_sec(symbol_upper, company_name)
        except Exception as exc:
            logger.error(f"SEC verification failed for {symbol_upper}: {exc}")
            result = SECVerificationResult(
                symbol=symbol_upper,
                provided_name=company_name or "unknown",
                confidence_score=0.0,
                match_type="not_found",
                error_message=str(exc),
            )
        
        # Cache result
        if self.use_cache:
            self._save_to_cache(symbol_upper, result)
        
        return result
    
    def _fetch_from_sec(
        self,
        symbol: str,
        company_name: Optional[str] = None,
    ) -> SECVerificationResult:
        """Fetch company information from SEC/EDGAR.
        
        Args:
            symbol: Stock ticker
            company_name: Company name to verify
        
        Returns:
            SECVerificationResult
        """
        if requests is None:
            logger.warning("requests not available, returning unverified result")
            return SECVerificationResult(
                symbol=symbol,
                provided_name=company_name or "unknown",
                confidence_score=0.0,
                match_type="unavailable",
                error_message="requests library not installed",
            )
        
        try:
            # Try to fetch SEC company tickers JSON
            response = self.session.get(
                self.SEC_CIK_LOOKUP_URL,
                timeout=self.REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            
            tickers_data = response.json()
            
            # Search for matching ticker
            for item in tickers_data.values():
                if isinstance(item, dict):
                    ticker = item.get("ticker", "").upper()
                    if ticker == symbol:
                        sec_name = item.get("title", "")
                        cik = item.get("cik_str")
                        
                        # Calculate confidence based on name match
                        if company_name:
                            is_match, match_type, confidence = self._compare_names(
                                company_name,
                                sec_name
                            )
                        else:
                            is_match = False
                            match_type = "ticker_found_no_name"
                            confidence = 0.7  # Ticker found but no name to verify
                        
                        return SECVerificationResult(
                            symbol=symbol,
                            provided_name=company_name or "unknown",
                            sec_legal_name=sec_name,
                            cik=str(cik) if cik else None,
                            confidence_score=confidence,
                            is_match=is_match,
                            match_type=match_type,
                            cik_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}" if cik else None,
                            verification_timestamp=datetime.now(timezone.utc),
                        )
            
            # Symbol not found in SEC database
            return SECVerificationResult(
                symbol=symbol,
                provided_name=company_name or "unknown",
                confidence_score=0.0,
                match_type="not_found",
                error_message=f"Symbol '{symbol}' not found in SEC/EDGAR database",
                verification_timestamp=datetime.now(timezone.utc),
            )
        
        except requests.exceptions.RequestException as exc:
            logger.error(f"SEC API request failed: {exc}")
            raise
    
    def _compare_names(
        self,
        provided_name: str,
        sec_name: str,
    ) -> tuple[bool, str, float]:
        """Compare provided company name with SEC legal name.
        
        Args:
            provided_name: Company name provided by user/API
            sec_name: Legal name from SEC/EDGAR
        
        Returns:
            Tuple of (is_match, match_type, confidence_score)
        """
        # Normalize names
        prov_norm = provided_name.upper().strip()
        sec_norm = sec_name.upper().strip()
        
        # Exact match
        if prov_norm == sec_norm:
            return True, "exact", self.CONFIDENCE_EXACT_MATCH
        
        # Check if one contains the other (partial match)
        if prov_norm in sec_norm or sec_norm in prov_norm:
            return True, "fuzzy", self.CONFIDENCE_FUZZY_MATCH
        
        # Remove common suffixes and check again
        suffixes = [" INC", " CORP", " LLC", " LP", ".COM", " CORPORATION", " INCORPORATED"]
        prov_clean = prov_norm
        sec_clean = sec_norm
        
        for suffix in suffixes:
            prov_clean = prov_clean.replace(suffix, "").strip()
            sec_clean = sec_clean.replace(suffix, "").strip()
        
        if prov_clean and sec_clean and prov_clean in sec_clean or sec_clean in prov_clean:
            return True, "fuzzy", self.CONFIDENCE_FUZZY_MATCH
        
        # No match
        return False, "mismatch", self.CONFIDENCE_NO_MATCH
    
    def _get_from_cache(self, symbol: str) -> Optional[SECVerificationResult]:
        """Retrieve verification result from cache.
        
        Args:
            symbol: Stock ticker
        
        Returns:
            Cached result or None
        """
        try:
            cache_file = self.cache_path / f"{symbol}.json"
            if cache_file.exists():
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                return SECVerificationResult(**data)
        except Exception as exc:
            logger.warning(f"Failed to read SEC cache for {symbol}: {exc}")
        return None
    
    def _save_to_cache(self, symbol: str, result: SECVerificationResult) -> None:
        """Save verification result to cache.
        
        Args:
            symbol: Stock ticker
            result: Verification result to cache
        """
        try:
            cache_file = self.cache_path / f"{symbol}.json"
            cache_file.write_text(result.to_json(), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Failed to save SEC cache for {symbol}: {exc}")
    
    def batch_verify(
        self,
        verifications: list[dict[str, Any]]
    ) -> list[SECVerificationResult]:
        """Verify multiple symbols at once.
        
        Args:
            verifications: List of {"symbol": ..., "company_name": ...} dicts
        
        Returns:
            List of SECVerificationResult objects
        """
        results = []
        for item in verifications:
            try:
                result = self.verify(
                    symbol=item["symbol"],
                    company_name=item.get("company_name"),
                )
                results.append(result)
            except Exception as exc:
                logger.error(f"Batch verification failed for {item.get('symbol')}: {exc}")
        return results
