from __future__ import annotations

import base64
import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .phase61_providers import alpaca_option_snapshots, alpaca_stock_snapshots
from .settings import Settings

INTELLIGENCE_AUDIT_PATH = Path("data/live/intelligence_audit.json")


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


_BULLISH = {
    "bullish", "calls", "call flow", "breakout", "upgrade", "beat", "approval",
    "contract award", "buyback", "accumulation", "squeeze", "long",
}
_BEARISH = {
    "bearish", "puts", "put flow", "breakdown", "downgrade", "miss", "offering",
    "dilution", "short", "fraud", "investigation", "delisting",
}
_SYMBOL_RE = re.compile(r"(?<![A-Z0-9])\$?([A-Z]{1,5})(?![A-Z0-9])")


def _session() -> requests.Session:
    client = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
    )
    client.mount("https://", HTTPAdapter(max_retries=retry))
    client.headers.update({"Accept": "application/json"})
    return client


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _utc_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            stamp = datetime.fromtimestamp(float(value), tz=timezone.utc)
        else:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            stamp = stamp.astimezone(timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    return stamp.isoformat()


def _sentiment(text: str) -> tuple[int, int]:
    lowered = str(text or "").lower()
    return (
        sum(term in lowered for term in _BULLISH),
        sum(term in lowered for term in _BEARISH),
    )


def _symbols_from_text(text: str, allowed: set[str]) -> set[str]:
    return {match.group(1) for match in _SYMBOL_RE.finditer(str(text or "").upper()) if match.group(1) in allowed}


def _attempt(provider: str, configured: bool) -> dict[str, Any]:
    return {
        "provider": provider,
        "configured": configured,
        "success": False,
        "records": 0,
        "error": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _write_audit(payload: dict[str, Any]) -> None:
    INTELLIGENCE_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = INTELLIGENCE_AUDIT_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(INTELLIGENCE_AUDIT_PATH)


def _collect_finra(client: requests.Session, settings: Settings, symbols: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    audit = _attempt("finra_reg_sho", True)
    output: dict[str, dict[str, Any]] = {}
    endpoint = "https://api.finra.org/data/group/OTCMarket/name/regShoDaily"
    try:
        for symbol in symbols[:20]:
            response = client.post(
                endpoint,
                json={
                    "limit": 5,
                    "compareFilters": [{"compareType": "equal", "fieldName": "symbolCode", "fieldValue": symbol}],
                    "sortFields": ["tradeReportDate"],
                    "sortOrders": [-1],
                },
                timeout=settings.request_timeout_seconds,
            )
            response.raise_for_status()
            rows = response.json() or []
            if isinstance(rows, dict):
                rows = rows.get("data") or rows.get("results") or []
            if not rows:
                continue
            row = rows[0]
            short_volume = _safe_float(
                row.get("shortVolume") or row.get("shortSaleVolume") or row.get("totalShortVolume") or row.get("shortVolumeQuantity"), 0.0
            ) or 0.0
            total_volume = _safe_float(
                row.get("totalVolume") or row.get("totalVolumeQuantity") or row.get("totalReportedVolume"), 0.0
            ) or 0.0
            output[symbol] = {
                "source": "FINRA Reg SHO",
                "trade_date": row.get("tradeReportDate") or row.get("date"),
                "short_volume": short_volume,
                "total_volume": total_volume,
                "short_volume_ratio": round(short_volume / total_volume, 4) if total_volume > 0 else None,
            }
        audit["success"] = True
        audit["records"] = len(output)
    except Exception as exc:
        audit["error"] = f"{type(exc).__name__}: {exc}"
    return output, audit


def _collect_alpha_news(client: requests.Session, settings: Settings, symbols: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    configured = bool(settings.alpha_vantage_api_key)
    audit = _attempt("alpha_vantage_news", configured)
    if not configured or not symbols:
        return {}, audit
    output: dict[str, dict[str, Any]] = defaultdict(lambda: {"mentions": 0, "sentiment_total": 0.0, "articles": []})
    try:
        response = client.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "NEWS_SENTIMENT",
                "tickers": ",".join(symbols[:12]),
                "limit": 200,
                "sort": "LATEST",
                "apikey": settings.alpha_vantage_api_key,
            },
            timeout=settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json() or {}
        if payload.get("Information") or payload.get("Note"):
            raise RuntimeError(payload.get("Information") or payload.get("Note"))
        allowed = set(symbols)
        for article in payload.get("feed") or []:
            title = str(article.get("title") or "")
            for item in article.get("ticker_sentiment") or []:
                symbol = str(item.get("ticker") or "").upper()
                if symbol not in allowed:
                    continue
                score = _safe_float(item.get("ticker_sentiment_score"), 0.0) or 0.0
                row = output[symbol]
                row["mentions"] += 1
                row["sentiment_total"] += score
                if len(row["articles"]) < 5:
                    row["articles"].append({
                        "title": title,
                        "url": article.get("url"),
                        "published": article.get("time_published"),
                        "score": score,
                    })
        normalized: dict[str, dict[str, Any]] = {}
        for symbol, row in output.items():
            mentions = int(row["mentions"])
            normalized[symbol] = {
                "source": "Alpha Vantage News Sentiment",
                "mentions": mentions,
                "sentiment": round(float(row["sentiment_total"]) / max(1, mentions), 4),
                "articles": row["articles"],
            }
        audit["success"] = True
        audit["records"] = sum(item["mentions"] for item in normalized.values())
        return normalized, audit
    except Exception as exc:
        audit["error"] = f"{type(exc).__name__}: {exc}"
        return {}, audit


def _collect_x(client: requests.Session, settings: Settings, symbols: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    token = _env("X_BEARER_TOKEN")
    configured = bool(token)
    audit = _attempt("x_recent_search", configured)
    if not configured or not symbols:
        return {}, audit
    allowed = set(symbols)
    cashtags = " OR ".join(f"${symbol}" for symbol in symbols[:12])
    accounts = [item.strip().lstrip("@") for item in _env(
        "X_WATCH_ACCOUNTS", "unusual_whales,spotgamma,CheddarFlow,Barchart,Benzinga,Cboe,NasdaqExchange,NYSE"
    ).split(",") if item.strip()]
    account_filter = " (" + " OR ".join(f"from:{name}" for name in accounts[:12]) + ")" if accounts else ""
    query = f"({cashtags}){account_filter} lang:en -is:retweet"
    output: dict[str, dict[str, Any]] = defaultdict(lambda: {"mentions": 0, "bullish": 0, "bearish": 0, "engagement": 0, "posts": []})
    try:
        response = client.get(
            "https://api.twitter.com/2/tweets/search/recent",
            params={"query": query, "max_results": 100, "tweet.fields": "created_at,author_id,public_metrics,text"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.request_timeout_seconds,
        )
        response.raise_for_status()
        for post in (response.json() or {}).get("data") or []:
            text = str(post.get("text") or "")
            bullish, bearish = _sentiment(text)
            metrics = post.get("public_metrics") or {}
            engagement = sum(int(metrics.get(key) or 0) for key in ("like_count", "retweet_count", "reply_count", "quote_count"))
            for symbol in _symbols_from_text(text, allowed):
                row = output[symbol]
                row["mentions"] += 1
                row["bullish"] += bullish
                row["bearish"] += bearish
                row["engagement"] += engagement
                if len(row["posts"]) < 5:
                    row["posts"].append({
                        "id": post.get("id"), "created_at": post.get("created_at"), "author_id": post.get("author_id"),
                        "text": text[:280], "engagement": engagement,
                    })
        audit["success"] = True
        audit["records"] = sum(row["mentions"] for row in output.values())
    except Exception as exc:
        audit["error"] = f"{type(exc).__name__}: {exc}"
    return dict(output), audit


def _reddit_token(client: requests.Session, settings: Settings) -> str:
    client_id = _env("REDDIT_CLIENT_ID")
    client_secret = _env("REDDIT_CLIENT_SECRET")
    user_agent = _env("REDDIT_USER_AGENT", "GHAZI-Market-Radar/6.1")
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    response = client.post(
        "https://www.reddit.com/api/v1/access_token",
        data={"grant_type": "client_credentials"},
        headers={"Authorization": "Basic " + base64.b64encode(raw).decode("ascii"), "User-Agent": user_agent},
        timeout=settings.request_timeout_seconds,
    )
    response.raise_for_status()
    token = (response.json() or {}).get("access_token")
    if not token:
        raise RuntimeError("Reddit OAuth response did not include access_token")
    return str(token)


def _collect_reddit(client: requests.Session, settings: Settings, symbols: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    configured = bool(_env("REDDIT_CLIENT_ID") and _env("REDDIT_CLIENT_SECRET"))
    audit = _attempt("reddit_oauth_search", configured)
    if not configured or not symbols:
        return {}, audit
    allowed = set(symbols)
    communities = [item.strip() for item in _env(
        "REDDIT_COMMUNITIES", "options,stocks,StockMarket,wallstreetbets,thetagang,investing,SecurityAnalysis"
    ).split(",") if item.strip()]
    query = " OR ".join(f'"{symbol}" OR "${symbol}"' for symbol in symbols[:10])
    output: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "mentions": 0, "bullish": 0, "bearish": 0, "engagement": 0, "communities": set(), "posts": []
    })
    try:
        token = _reddit_token(client, settings)
        headers = {"Authorization": f"bearer {token}", "User-Agent": _env("REDDIT_USER_AGENT", "GHAZI-Market-Radar/6.1")}
        for community in communities[:8]:
            response = client.get(
                f"https://oauth.reddit.com/r/{community}/search",
                params={"q": query, "restrict_sr": 1, "sort": "new", "t": "day", "limit": 100, "raw_json": 1},
                headers=headers,
                timeout=settings.request_timeout_seconds,
            )
            response.raise_for_status()
            children = (((response.json() or {}).get("data") or {}).get("children") or [])
            for child in children:
                post = child.get("data") or {}
                text = f"{post.get('title') or ''} {post.get('selftext') or ''}"
                bullish, bearish = _sentiment(text)
                engagement = int(post.get("score") or 0) + int(post.get("num_comments") or 0)
                for symbol in _symbols_from_text(text, allowed):
                    row = output[symbol]
                    row["mentions"] += 1
                    row["bullish"] += bullish
                    row["bearish"] += bearish
                    row["engagement"] += engagement
                    row["communities"].add(community)
                    if len(row["posts"]) < 5:
                        row["posts"].append({
                            "community": community,
                            "title": str(post.get("title") or "")[:240],
                            "permalink": post.get("permalink"),
                            "created_at": _utc_iso(post.get("created_utc")),
                            "score": post.get("score"),
                            "comments": post.get("num_comments"),
                        })
        normalized = {symbol: {**row, "communities": sorted(row["communities"])} for symbol, row in output.items()}
        audit["success"] = True
        audit["records"] = sum(row["mentions"] for row in normalized.values())
        return normalized, audit
    except Exception as exc:
        audit["error"] = f"{type(exc).__name__}: {exc}"
        return {}, audit


def _collect_benzinga(client: requests.Session, settings: Settings, contracts: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    token = _env("BENZINGA_TOKEN")
    configured = bool(token)
    audit = _attempt("benzinga_option_activity", configured)
    if not configured or not contracts:
        return {}, audit
    allowed = {str(value).replace("O:", "").replace(" ", "") for value in contracts}
    output: dict[str, dict[str, Any]] = {}
    try:
        response = client.get(
            "https://api.benzinga.com/api/v1/signal/option_activity",
            params={"token": token, "pagesize": 1000},
            timeout=settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json() or {}
        rows = payload.get("option_activity") if isinstance(payload, dict) else payload
        for row in rows or []:
            contract = str(row.get("option_symbol") or "").replace("O:", "").replace(" ", "")
            if contract not in allowed:
                continue
            output[contract] = {
                "source": "Benzinga Option Activity",
                "execution_estimate": row.get("execution_estimate"),
                "sentiment": row.get("sentiment"),
                "aggressor_ind": _safe_float(row.get("aggressor_ind")),
                "cost_basis": _safe_float(row.get("cost_basis")),
                "size": _safe_float(row.get("size")),
                "volume": _safe_float(row.get("volume")),
                "open_interest": _safe_float(row.get("open_interest")),
                "price": _safe_float(row.get("price")),
                "updated": _utc_iso(row.get("updated")),
                "description": row.get("description"),
            }
        audit["success"] = True
        audit["records"] = len(output)
    except Exception as exc:
        audit["error"] = f"{type(exc).__name__}: {exc}"
    return output, audit


def _collect_alpaca(client: requests.Session, settings: Settings, symbols: list[str], contracts: list[str]):
    configured = bool(settings.alpaca_api_key and settings.alpaca_secret_key)
    stock_audit = _attempt("alpaca_stock_snapshots", configured)
    option_audit = _attempt("alpaca_option_snapshots", configured)
    stocks: dict[str, dict[str, Any]] = {}
    options: dict[str, dict[str, Any]] = {}
    if configured:
        try:
            stocks = alpaca_stock_snapshots(settings, symbols, session=client)
            stock_audit.update(success=True, records=len(stocks))
        except Exception as exc:
            stock_audit["error"] = f"{type(exc).__name__}: {exc}"
        try:
            options = alpaca_option_snapshots(settings, contracts, session=client)
            option_audit.update(success=True, records=len(options))
        except Exception as exc:
            option_audit["error"] = f"{type(exc).__name__}: {exc}"
    return stocks, options, [stock_audit, option_audit]


def _social_score(*rows: dict[str, Any] | None) -> float:
    mentions = sum(int((row or {}).get("mentions") or 0) for row in rows)
    engagement = sum(int((row or {}).get("engagement") or 0) for row in rows)
    bullish = sum(int((row or {}).get("bullish") or 0) for row in rows)
    bearish = sum(int((row or {}).get("bearish") or 0) for row in rows)
    return round(min(25.0, mentions * 1.8 + math.log1p(max(0, engagement)) * 1.4 + abs(bullish - bearish) * 0.8), 2)


def collect_phase61_intelligence(payload: dict[str, Any], settings: Settings | None = None, *, session: requests.Session | None = None) -> dict[str, Any]:
    """Collect official, licensed flow and community evidence.

    X and Reddit are supporting evidence only. They cannot promote a stock or
    contract without independent market or official confirmation.
    """

    settings = settings or Settings()
    client = session or _session()
    symbols = list(dict.fromkeys(
        str(row.get("symbol") or "").upper()
        for row in payload.get("stocks", []) or [] if row.get("symbol")
    ))[: int(_env("INTELLIGENCE_MAX_SYMBOLS", "15"))]
    contracts = list(dict.fromkeys(
        str(row.get("contract_symbol") or "").replace("O:", "").replace(" ", "")
        for row in list(payload.get("top_calls", []) or []) + list(payload.get("top_puts", []) or [])
        if row.get("contract_symbol")
    ))[: int(_env("INTELLIGENCE_MAX_CONTRACTS", "30"))]

    finra, finra_audit = _collect_finra(client, settings, symbols)
    alpha_news, alpha_audit = _collect_alpha_news(client, settings, symbols)
    x_rows, x_audit = _collect_x(client, settings, symbols)
    reddit_rows, reddit_audit = _collect_reddit(client, settings, symbols)
    benzinga, benzinga_audit = _collect_benzinga(client, settings, contracts)
    alpaca_stocks, alpaca_options, alpaca_audits = _collect_alpaca(client, settings, symbols, contracts)
    audits = [finra_audit, alpha_audit, x_audit, reddit_audit, benzinga_audit, *alpaca_audits]

    stock_evidence: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        sources: list[str] = []
        official_sources: list[str] = []
        market_sources: list[str] = []
        if symbol in finra:
            sources.append("FINRA Reg SHO")
            official_sources.append("FINRA Reg SHO")
        if symbol in alpha_news:
            sources.append("Alpha Vantage News Sentiment")
        if symbol in alpaca_stocks:
            sources.append("Alpaca stock snapshot")
            market_sources.append("alpaca")
        if (x_rows.get(symbol) or {}).get("mentions"):
            sources.append("X recent search")
        if (reddit_rows.get(symbol) or {}).get("mentions"):
            sources.append("Reddit communities")
        stock_evidence[symbol] = {
            "sources": sources,
            "official_sources": official_sources,
            "market_sources": market_sources,
            "finra": finra.get(symbol),
            "news": alpha_news.get(symbol),
            "x": x_rows.get(symbol),
            "reddit": reddit_rows.get(symbol),
            "alpaca": alpaca_stocks.get(symbol),
            "social_score": _social_score(x_rows.get(symbol), reddit_rows.get(symbol)),
        }

    contract_evidence: dict[str, dict[str, Any]] = {}
    for contract in contracts:
        sources: list[str] = []
        market_flow_sources: list[str] = []
        if contract in benzinga:
            sources.append("Benzinga Option Activity")
            market_flow_sources.append("benzinga")
        if contract in alpaca_options:
            sources.append("Alpaca option snapshot")
            market_flow_sources.append("alpaca")
        contract_evidence[contract] = {
            "sources": sources,
            "market_flow_sources": market_flow_sources,
            "benzinga": benzinga.get(contract),
            "alpaca": alpaca_options.get(contract),
        }

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "social_is_supporting_only": True,
            "social_cannot_promote_recommendation_alone": True,
            "official_and_licensed_apis_only": True,
            "direct_site_scraping": False,
        },
        "summary": {
            "symbols_checked": len(symbols),
            "contracts_checked": len(contracts),
            "configured_sources": sum(bool(row.get("configured")) for row in audits),
            "successful_sources": sum(bool(row.get("success")) for row in audits),
            "social_mentions": sum(int((row or {}).get("mentions") or 0) for row in x_rows.values())
            + sum(int((row or {}).get("mentions") or 0) for row in reddit_rows.values()),
            "benzinga_contract_matches": len(benzinga),
            "finra_symbols": len(finra),
        },
        "audit": audits,
        "stocks": stock_evidence,
        "contracts": contract_evidence,
    }
    _write_audit(result)
    return result
