from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

_FALLBACK_TOKENS = ("yahoo", "yfinance")
_DELAYED_TOKENS = ("sandbox", "delayed", "24h", "indicative", "unofficial", "may be delayed")
_OPRA_TOKENS = ("opra", "polygon_options", "massive", "databento")
_LIVE_TOKENS = ("brokerage feed", "real-time", "realtime", "opra", "sip")


@dataclass(frozen=True)
class ProviderReadiness:
    status: str
    production_quote_ready: bool
    production_flow_ready: bool
    usable_chains: int
    fallback_only_chains: int
    delayed_or_indicative_chains: int
    live_primary_chains: int
    cross_source_chains: int
    opra_chains: int
    sources: tuple[str, ...]
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sources"] = list(self.sources)
        payload["reasons"] = list(self.reasons)
        return payload


def _successful_providers(audit: dict[str, Any]) -> list[str]:
    attempts = audit.get("attempts") if isinstance(audit.get("attempts"), list) else []
    output: list[str] = []
    for item in attempts:
        if not isinstance(item, dict) or not item.get("success"):
            continue
        provider = str(item.get("provider") or "").strip().lower()
        if provider and provider not in output:
            output.append(provider)
    return output


def _contains(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in tokens)


def _fabric_classification(
    raw: dict[str, Any],
    *,
    tradier_base_url: str,
) -> tuple[bool, bool, bool, bool]:
    """Return (live_quote, delayed, fallback_only, opra) for fabric metadata.

    We deliberately do not assume that an account-entitlement source is live.
    Production readiness requires an explicitly live/licensed source or a fresh
    execution-grade OPRA stream overlay.
    """
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    fabric = metadata.get("data_fabric") if isinstance(metadata.get("data_fabric"), dict) else {}
    stream = metadata.get("stream_overlay") if isinstance(metadata.get("stream_overlay"), dict) else {}
    successes = _successful_providers(raw)

    live_quote = False
    delayed = False
    non_fallback = 0
    for provider in successes:
        name = provider.lower()
        if name in {"yahoo", "yfinance"}:
            delayed = True
            continue
        non_fallback += 1
        if name == "tradier":
            if "sandbox" in tradier_base_url.lower():
                delayed = True
            else:
                live_quote = True
        elif name == "marketdata":
            # Current MarketData adapter explicitly labels its free/account path
            # as delayed. A future live adapter must advertise that separately.
            delayed = True
        elif name in {"databento", "massive", "polygon_options"}:
            live_quote = True
        else:
            # Finnhub and other account feeds may be live depending on entitlement,
            # but absence of an explicit live marker must not create Production.
            pass

    stream_execution = bool(stream.get("execution_grade")) and int(stream.get("execution_quotes_replaced") or 0) > 0
    if stream_execution:
        live_quote = True
    opra = stream_execution or bool(fabric.get("opra_source_active"))
    fallback_only = bool(successes) and non_fallback == 0
    return live_quote, delayed, fallback_only, opra


def assess_provider_readiness(
    provider_audit: dict[str, Any] | None,
    *,
    tradier_base_url: str = "",
    stream_active: bool = False,
    stream_source: str = "",
) -> ProviderReadiness:
    audits = provider_audit if isinstance(provider_audit, dict) else {}
    usable = 0
    fallback = 0
    delayed = 0
    live_primary = 0
    cross_source = 0
    opra = 0
    all_sources: list[str] = []

    for raw in audits.values():
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("source") or "").strip().lower()
        freshness = str(raw.get("freshness") or "").strip().lower()
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        successes = _successful_providers(raw)
        if source:
            usable += 1
            if source not in all_sources:
                all_sources.append(source)
        if len(successes) >= 2:
            cross_source += 1

        is_fabric = source.startswith("fabric:") or isinstance(metadata.get("data_fabric"), dict)
        if is_fabric:
            fabric_live, fabric_delayed, fabric_fallback, fabric_opra = _fabric_classification(
                raw,
                tradier_base_url=tradier_base_url,
            )
            if fabric_fallback:
                fallback += 1
            if fabric_delayed:
                delayed += 1
            if fabric_live:
                live_primary += 1
            if fabric_opra:
                opra += 1
            continue

        is_fallback = bool(source) and _contains(source, _FALLBACK_TOKENS) and len(successes) <= 1
        is_delayed = _contains(f"{source} {freshness}", _DELAYED_TOKENS)
        explicit_live = _contains(f"{source} {freshness}", _LIVE_TOKENS)
        live_tradier_chain = "tradier" in source and "sandbox" not in tradier_base_url.lower()
        is_opra = bool(metadata.get("opra_source_active")) or _contains(source, _OPRA_TOKENS)
        if is_fallback:
            fallback += 1
        if is_delayed:
            delayed += 1
        if source and not is_fallback and not is_delayed and (explicit_live or live_tradier_chain or is_opra):
            live_primary += 1
        if is_opra:
            opra += 1

    stream_source_text = str(stream_source or "").strip().lower()
    live_tradier = bool(stream_active and stream_source_text == "tradier" and "sandbox" not in tradier_base_url.lower())
    live_opra_stream = bool(stream_active and _contains(stream_source_text, _OPRA_TOKENS))
    production_quote_ready = bool(live_primary > 0 or live_tradier or live_opra_stream)
    production_flow_ready = bool(opra > 0 or live_tradier or live_opra_stream)

    reasons: list[str] = []
    if usable == 0 and not stream_active:
        status = "CRITICAL_NO_OPTION_DATA"
        reasons.append("No usable option-chain source is currently producing data")
    elif not production_quote_ready:
        status = "FALLBACK_ONLY"
        reasons.append("Only delayed, indicative, unofficial, or unverified-entitlement option data is active")
    elif not production_flow_ready:
        status = "LIVE_QUOTES_NO_TRADE_FLOW"
        reasons.append("Live option quotes are available, but trade+NBBO flow evidence is not active")
    else:
        status = "LIVE_FLOW_READY"
        reasons.append("A live trade/quote flow source is active")

    if fallback:
        reasons.append(f"{fallback} chain(s) are Yahoo/YFinance-only fallback")
    if delayed:
        reasons.append(f"{delayed} chain(s) contain delayed, indicative, or unofficial sources")
    if cross_source:
        reasons.append(f"{cross_source} chain(s) have successful cross-source retrieval")
    if opra:
        reasons.append(f"{opra} chain(s) report OPRA-backed evidence")
    if stream_active:
        reasons.append(f"Streaming source active: {stream_source_text or 'unknown'}")

    return ProviderReadiness(
        status=status,
        production_quote_ready=production_quote_ready,
        production_flow_ready=production_flow_ready,
        usable_chains=usable,
        fallback_only_chains=fallback,
        delayed_or_indicative_chains=delayed,
        live_primary_chains=live_primary,
        cross_source_chains=cross_source,
        opra_chains=opra,
        sources=tuple(sorted(all_sources)),
        reasons=tuple(reasons),
    )
