from __future__ import annotations

from typing import Any

_ALIASES = {
    "twelve": "twelve_data",
    "twelvedata": "twelve_data",
    "alpha": "alpha_vantage",
    "alphavantage": "alpha_vantage",
    "yfinance": "yahoo",
}


def normalize_provider_list(raw: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if raw is None:
        return []
    values = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    output: list[str] = []
    for item in values:
        name = str(item).strip().lower()
        name = _ALIASES.get(name, name)
        if name and name not in output:
            output.append(name)
    return output


def provider_is_configured(settings: Any, provider: str) -> bool:
    name = _ALIASES.get(str(provider or "").strip().lower(), str(provider or "").strip().lower())
    if name == "yahoo":
        return True
    if name == "tradier":
        return bool(getattr(settings, "tradier_token", None))
    if name == "marketdata":
        return bool(getattr(settings, "marketdata_token", None))
    if name == "finnhub":
        return bool(getattr(settings, "finnhub_api_key", None))
    if name == "tiingo":
        return bool(getattr(settings, "tiingo_api_key", None))
    if name == "alpaca":
        return bool(
            getattr(settings, "alpaca_api_key", None)
            and getattr(settings, "alpaca_secret_key", None)
        )
    if name == "twelve_data":
        return bool(getattr(settings, "twelve_data_api_key", None))
    if name == "polygon":
        return bool(getattr(settings, "polygon_api_key", None))
    if name == "alpha_vantage":
        return bool(getattr(settings, "alpha_vantage_api_key", None))
    # Unknown/future providers are preserved. Their adapter remains the source
    # of truth until an explicit credential contract is added here.
    return True


def configured_providers(settings: Any, providers: list[str]) -> tuple[list[str], list[str]]:
    configured: list[str] = []
    skipped: list[str] = []
    for provider in normalize_provider_list(providers):
        if provider_is_configured(settings, provider):
            configured.append(provider)
        else:
            skipped.append(provider)
    return configured, skipped


def _annotate(result: Any, configured: list[str], skipped: list[str]) -> Any:
    metadata = getattr(result, "metadata", None)
    if isinstance(metadata, dict):
        metadata["provider_preflight"] = {
            "configured_providers": list(configured),
            "skipped_unconfigured": list(skipped),
            "adapter_attempts_avoided": len(skipped),
            "credentials_exposed": False,
            "decision_authority": False,
        }
    return result


def install_provider_preflight() -> None:
    """Skip deterministically unconfigured providers before Data Fabric fan-out.

    This must be installed after ``install_data_fabric()`` and before optional
    request-coalescing wrappers. It never changes the order of providers that
    are actually configured and it never inspects or emits credential values.
    """

    from options_radar import hybrid_fetcher as hybrid

    DataFetcher = hybrid.DataFetcher
    if getattr(DataFetcher, "_ghazi_provider_preflight_v1", False):
        return

    original_stock = DataFetcher.fetch_stock_bars
    original_options = DataFetcher.fetch_option_chain

    def stock_bars(
        self: Any,
        symbol: str,
        *,
        start: Any = None,
        end: Any = None,
        interval: str = "1d",
        providers: list[str] | None = None,
    ):
        raw = providers
        if raw is None:
            raw = normalize_provider_list(
                getattr(
                    self.settings,
                    "daily_provider_order" if interval == "1d" else "intraday_provider_order",
                    "",
                )
            )
        requested = normalize_provider_list(raw)
        configured, skipped = configured_providers(self.settings, requested)
        if not configured:
            attempts = [
                hybrid.FetchAttempt(
                    provider=name,
                    operation="stock_bars",
                    success=False,
                    elapsed_ms=0,
                    rows=0,
                    error="provider not configured; skipped before adapter call",
                )
                for name in skipped
            ]
            raise hybrid.DataUnavailableError(f"stock_bars:{str(symbol).upper()}", attempts)
        result = original_stock(
            self,
            symbol,
            start=start,
            end=end,
            interval=interval,
            providers=configured,
        )
        return _annotate(result, configured, skipped)

    def option_chain(
        self: Any,
        symbol: str,
        *,
        min_dte: int | None = None,
        max_dte: int | None = None,
        providers: list[str] | None = None,
        apply_guards: bool = True,
    ):
        raw = providers
        if raw is None:
            raw = normalize_provider_list(getattr(self.settings, "options_provider_order", ""))
        requested = normalize_provider_list(raw)
        configured, skipped = configured_providers(self.settings, requested)
        if not configured:
            attempts = [
                hybrid.FetchAttempt(
                    provider=name,
                    operation="option_chain",
                    success=False,
                    elapsed_ms=0,
                    rows=0,
                    error="provider not configured; skipped before adapter call",
                )
                for name in skipped
            ]
            raise hybrid.DataUnavailableError(f"option_chain:{str(symbol).upper()}", attempts)
        result = original_options(
            self,
            symbol,
            min_dte=min_dte,
            max_dte=max_dte,
            providers=configured,
            apply_guards=apply_guards,
        )
        return _annotate(result, configured, skipped)

    DataFetcher.fetch_stock_bars = stock_bars
    DataFetcher.fetch_option_chain = option_chain
    DataFetcher._ghazi_provider_preflight_v1 = True
