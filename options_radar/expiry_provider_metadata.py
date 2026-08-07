from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from . import hybrid_fetcher, providers as legacy_providers

_INSTALLED = False
_ORIGINAL_TRADIER_CHAIN = hybrid_fetcher.DataFetcher._tradier_chain

_EXPIRY_METADATA_COLUMNS = (
    "provider_expiry_family",
    "expiration_type",
    "series_type",
    "root_symbol",
    "option_root",
    "settlement_type",
    "settlement_time",
    "exercise_style",
    "multiplier",
)


def _extend_common_schemas() -> None:
    for column in _EXPIRY_METADATA_COLUMNS:
        if column not in hybrid_fetcher.OPTION_COLUMNS:
            hybrid_fetcher.OPTION_COLUMNS.append(column)
        if column not in legacy_providers.STANDARD_COLUMNS:
            legacy_providers.STANDARD_COLUMNS.append(column)


def _tradier_chain_with_expiry_metadata(
    self: hybrid_fetcher.DataFetcher,
    symbol: str,
    min_dte: int,
    max_dte: int,
) -> pd.DataFrame:
    token = getattr(self.settings, "tradier_token", None)
    if not token:
        raise RuntimeError("TRADIER_TOKEN is not configured")

    base = str(
        getattr(self.settings, "tradier_base_url", "https://sandbox.tradier.com")
    ).rstrip("/")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    expiry_payload = self._get_json(
        f"{base}/v1/markets/options/expirations",
        params={"symbol": symbol, "includeAllRoots": "true", "strikes": "false"},
        headers=headers,
    )
    dates = (expiry_payload.get("expirations") or {}).get("date", [])
    if isinstance(dates, str):
        dates = [dates]
    today = date.today()
    expirations = [
        raw
        for raw in dates or []
        if min_dte
        <= (datetime.strptime(str(raw), "%Y-%m-%d").date() - today).days
        <= max_dte
    ][:10]

    quote_payload = self._get_json(
        f"{base}/v1/markets/quotes",
        params={"symbols": symbol, "greeks": "false"},
        headers=headers,
    )
    quote = (quote_payload.get("quotes") or {}).get("quote", {})
    if isinstance(quote, list):
        quote = quote[0] if quote else {}
    underlying_price = hybrid_fetcher._safe_float(quote.get("last") or quote.get("close"))

    rows: list[dict[str, Any]] = []
    for expiry in expirations:
        payload = self._get_json(
            f"{base}/v1/markets/options/chains",
            params={"symbol": symbol, "expiration": expiry, "greeks": "true"},
            headers=headers,
        )
        options = (payload.get("options") or {}).get("option", [])
        if isinstance(options, dict):
            options = [options]
        for item in options or []:
            greek = item.get("greeks") or {}
            row = self._build_option_row(
                symbol=symbol,
                contract=item.get("symbol"),
                expiry=item.get("expiration_date") or expiry,
                strike=item.get("strike"),
                side=item.get("option_type"),
                bid=item.get("bid"),
                ask=item.get("ask"),
                last=item.get("last"),
                volume=item.get("volume"),
                open_interest=item.get("open_interest"),
                iv=greek.get("mid_iv") or greek.get("smv_vol"),
                delta=greek.get("delta"),
                gamma=greek.get("gamma"),
                theta=greek.get("theta"),
                vega=greek.get("vega"),
                underlying=item.get("underlying_price") or underlying_price,
                updated_at=item.get("trade_date"),
                source="tradier",
                data_quality=0.66 if "sandbox" in base else 0.90,
                freshness="sandbox delayed" if "sandbox" in base else "brokerage feed",
            )
            expiration_type = item.get("expiration_type") or item.get("expiry_type")
            root_symbol = item.get("root_symbol") or item.get("root") or symbol
            row.update(
                provider_expiry_family=expiration_type,
                expiration_type=expiration_type,
                series_type=item.get("series_type"),
                root_symbol=root_symbol,
                option_root=item.get("option_root") or root_symbol,
                settlement_type=item.get("settlement_type"),
                settlement_time=item.get("settlement_time"),
                exercise_style=item.get("exercise_style"),
                multiplier=item.get("multiplier") or item.get("contract_size"),
            )
            rows.append(row)
    return hybrid_fetcher._option_frame(rows)


def install_expiry_provider_metadata() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _extend_common_schemas()
    hybrid_fetcher.DataFetcher._tradier_chain = _tradier_chain_with_expiry_metadata
    _INSTALLED = True
