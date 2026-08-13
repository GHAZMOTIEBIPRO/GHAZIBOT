from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

LOGGER = logging.getLogger(__name__)

OCC_DLP_URL = "https://marketdata.theocc.com/delo-download"
CBOE_MOST_ACTIVE_URL = (
    "https://www-api.cboe.com/us/options/market_statistics/most_active/data/"
)
DEFAULT_CACHE = Path("data/cache/occ_optionable_universe.json")
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

# Index products sometimes use exchange-specific roots (SPXW, VIXW, etc.).
# Canonicalization is intentionally conservative: aliases are only collapsed
# where the economic underlying is unambiguous for discovery purposes.
_CANONICAL_UNDERLYING = {
    "SPXW": "SPX",
    "SPXPM": "SPX",
    "VIXW": "VIX",
    "RUTW": "RUT",
    "NDXP": "NDX",
}


def _symbol(value: Any) -> str:
    raw = str(value or "").strip().upper().replace("/", ".")
    return _CANONICAL_UNDERLYING.get(raw, raw)


def _valid_symbol(value: Any) -> bool:
    symbol = _symbol(value)
    return bool(_SYMBOL_RE.fullmatch(symbol)) and symbol not in {
        "SYMBOL",
        "UNDERLYING",
        "UNDERLYING SYMBOL",
        "N/A",
        "NONE",
    }


def _unique(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        symbol = _symbol(value)
        if not _valid_symbol(symbol) or symbol in seen:
            continue
        seen.add(symbol)
        output.append(symbol)
    return output


def _split_line(line: str) -> list[str]:
    text = str(line or "").strip().lstrip("\ufeff")
    if not text:
        return []
    for delimiter in ("|", "\t", ",", ";"):
        if delimiter in text:
            return [part.strip().strip('"') for part in text.split(delimiter)]
    # OCC's DLP text layout has historically changed. A final whitespace
    # fallback keeps discovery fail-soft while tests pin the supported shapes.
    return [part.strip() for part in re.split(r"\s{2,}", text) if part.strip()]


def parse_occ_dlp_text(text: str) -> list[dict[str, str]]:
    """Parse OCC DLP text into option-root/underlying rows.

    OCC's DLP endpoint supports selectable OS/US/SN/EXCH/ONN fields. The
    downloader can return delimited or aligned text depending on upstream
    behavior, so this parser accepts common delimiters and ignores metadata.
    We only need the first two selected fields: option symbol and underlying.
    """

    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "<", "Directory of Listed")):
            continue
        parts = _split_line(line)
        if len(parts) < 2:
            continue

        option_root = _symbol(parts[0])
        underlying = _symbol(parts[1])
        upper = " ".join(parts[:2]).upper()
        if (
            "OPTION SYMBOL" in upper
            or "UNDERLYING SYMBOL" in upper
            or option_root in {"OS", "OPTION"}
            or underlying in {"US", "UNDERLYING"}
        ):
            continue
        if not _valid_symbol(option_root) or not _valid_symbol(underlying):
            continue
        key = (option_root, underlying)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "option_symbol": option_root,
                "underlying_symbol": underlying,
                "symbol_name": parts[2] if len(parts) >= 3 else "",
                "exchanges": parts[3] if len(parts) >= 4 else "",
                "product_type": parts[4] if len(parts) >= 5 else "",
            }
        )
    return rows


def _walk_cboe_active(payload: Any) -> list[dict[str, Any]]:
    """Extract Cboe most-active contract rows from its public JSON shape."""

    rows: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        # The current public endpoint groups calls/puts under categories.
        if "symbol" in payload and any(
            key in payload for key in ("expires", "expiration", "strike", "volume")
        ):
            symbol = _symbol(payload.get("symbol"))
            if _valid_symbol(symbol):
                rows.append(
                    {
                        "symbol": symbol,
                        "expiration": payload.get("expires") or payload.get("expiration"),
                        "strike": payload.get("strike"),
                        "volume": payload.get("volume"),
                        "option_type": payload.get("option_type") or payload.get("type"),
                    }
                )
        for value in payload.values():
            rows.extend(_walk_cboe_active(value))
    elif isinstance(payload, list):
        for value in payload:
            rows.extend(_walk_cboe_active(value))
    return rows


@dataclass
class OptionableUniverseResult:
    symbols: list[str]
    official_symbols: list[str]
    attention_symbols: list[str]
    configured_symbols: list[str]
    source: str
    official_verified: bool
    generated_at: str
    product_types: list[str] = field(default_factory=list)
    occ_rows: int = 0
    cboe_attention_rows: int = 0
    cache_used: bool = False
    limitations: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class IndependentOptionableUniverse:
    """Build an options-native universe without consuming StockRadar output.

    Source roles are deliberately separated:
    - OCC DLP: authoritative optionability / product directory.
    - Cboe Most Active: partial-exchange *attention* seed only.
    - configured_symbols: independent preferred/liquid watch universe.

    Cboe activity never proves whole-market flow and configured symbols never
    override OCC optionability when an official DLP snapshot is available.
    """

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        cache_path: str | Path = DEFAULT_CACHE,
        timeout: int = 25,
        user_agent: str | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.cache_path = Path(cache_path)
        self.timeout = max(5, int(timeout))
        self.session.headers.update(
            {
                "User-Agent": user_agent
                or os.getenv("SEC_USER_AGENT")
                or "GHAZI Options Radar (configure SEC_USER_AGENT with contact email)",
                "Accept": "text/plain,application/json;q=0.9,*/*;q=0.5",
            }
        )

    def _fetch_occ_product(self, product_type: str) -> list[dict[str, str]]:
        response = self.session.get(
            OCC_DLP_URL,
            params={
                "prodType": product_type,
                "downloadFields": "OS;US;SN;EXCH;ONN",
                "format": "txt",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        rows = parse_occ_dlp_text(response.text)
        if not rows:
            raise ValueError(f"OCC DLP {product_type} returned no parseable rows")
        return rows

    def _read_cache(self) -> dict[str, Any]:
        if not self.cache_path.exists():
            return {}
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_cache(self, payload: dict[str, Any]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(self.cache_path)
        except OSError as exc:
            LOGGER.warning("Could not persist OCC optionable universe cache: %s", exc)

    def fetch_official(
        self,
    ) -> tuple[
        list[str],
        list[dict[str, str]],
        list[str],
        dict[str, str],
        bool,
    ]:
        errors: dict[str, str] = {}
        all_rows: list[dict[str, str]] = []
        successful_types: list[str] = []
        for product_type in ("EU", "IU"):
            try:
                rows = self._fetch_occ_product(product_type)
                all_rows.extend(rows)
                successful_types.append(product_type)
            except Exception as exc:  # network/source failure must fail soft
                errors[f"occ:{product_type}"] = f"{type(exc).__name__}: {exc}"

        if all_rows:
            symbols = _unique(row.get("underlying_symbol") for row in all_rows)
            payload = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": "OCC Directory of Listed Products",
                "official": True,
                "product_types": successful_types,
                "symbols": symbols,
                "rows": all_rows,
            }
            self._write_cache(payload)
            return symbols, all_rows, successful_types, errors, False

        cache = self._read_cache()
        cached_symbols = _unique(cache.get("symbols", []))
        cached_rows = (
            [row for row in cache.get("rows", []) if isinstance(row, dict)]
            if isinstance(cache.get("rows"), list)
            else []
        )
        cached_types = [str(value) for value in cache.get("product_types", [])]
        if cached_symbols:
            return cached_symbols, cached_rows, cached_types, errors, True
        return [], [], [], errors, False

    def fetch_cboe_attention(
        self, limit: int = 100
    ) -> tuple[list[str], list[dict[str, Any]], str | None]:
        safe_limit = limit if limit in {10, 25, 50, 100} else 100
        try:
            response = self.session.get(
                CBOE_MOST_ACTIVE_URL,
                params={"mkt": "cone", "limit": safe_limit},
                headers={
                    "Accept": "application/json",
                    "User-Agent": self.session.headers["User-Agent"],
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            rows = _walk_cboe_active(response.json())
            symbols = _unique(row.get("symbol") for row in rows)
            return symbols, rows, None
        except Exception as exc:
            return [], [], f"{type(exc).__name__}: {exc}"

    def build(
        self,
        configured_symbols: Iterable[Any],
        *,
        max_symbols: int = 80,
        include_cboe_attention: bool = True,
        priority_symbols: Iterable[Any] = (
            "SPX",
            "SPY",
            "QQQ",
            "IWM",
            "VIX",
            "AAPL",
            "NVDA",
            "TSLA",
            "AMD",
            "META",
            "AMZN",
            "MSFT",
        ),
    ) -> OptionableUniverseResult:
        max_symbols = max(10, int(max_symbols))
        configured = _unique(configured_symbols)
        priority = _unique(priority_symbols)
        official, occ_rows, product_types, errors, cache_used = self.fetch_official()
        official_set = set(official)

        attention: list[str] = []
        attention_rows: list[dict[str, Any]] = []
        if include_cboe_attention:
            attention, attention_rows, cboe_error = self.fetch_cboe_attention(limit=100)
            if cboe_error:
                errors["cboe:most_active"] = cboe_error

        if official_set:
            # With OCC verification available, options-native activity gets first
            # priority, followed by the liquid core and configured research list.
            ordered = _unique([*attention, *priority, *configured])
            selected = [symbol for symbol in ordered if symbol in official_set]
            official_verified = True
            source = "OCC DLP + Cboe options attention + configured options universe"
        else:
            # Without current/cached OCC proof, do not let a hard-coded priority
            # list silently displace the configured research universe. Preserve
            # live options attention first, then configured symbols, then the
            # liquid core as a continuity fallback — all explicitly unverified.
            selected = _unique([*attention, *configured, *priority])
            official_verified = False
            source = "configured/Cboe fallback; OCC verification unavailable"

        limitations = [
            "Cboe Most Active is a partial-exchange attention source, not whole-market OPRA flow.",
            "Optionability does not imply liquidity; contract-level bid/ask, volume, OI and freshness guards still apply.",
            "The universe is independent from StockRadar and may contain symbols absent from the stock path.",
        ]
        if not official_verified:
            limitations.append(
                "OCC DLP was unavailable and no official cache was usable; optionability is not officially verified this run."
            )

        return OptionableUniverseResult(
            symbols=selected[:max_symbols],
            official_symbols=official,
            attention_symbols=attention,
            configured_symbols=configured,
            source=source,
            official_verified=official_verified,
            generated_at=datetime.now(timezone.utc).isoformat(),
            product_types=product_types,
            occ_rows=len(occ_rows),
            cboe_attention_rows=len(attention_rows),
            cache_used=cache_used,
            limitations=limitations,
            errors=errors,
        )
