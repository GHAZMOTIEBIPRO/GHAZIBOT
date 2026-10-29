"""Shared HTTP fetch for public-data builders (standard library only).

One call, one classified outcome, so a builder can keep its last good copy and say why:
- OK / NOT_MODIFIED (conditional GET answered 304: the previous copy is still current)
- REFUSED (401/403/451: access refused - never retried, never worked around)
- RATE_LIMITED (429: retried once after a bounded Retry-After, then reported)
- NOT_FOUND (404/410: an incomplete check, not a block)
- SERVER_ERROR (5xx) and NETWORK_ERROR (DNS, TLS, timeout, reset): bounded retries with backoff

Requests to one host are spaced by `min_interval` seconds. Nothing here stores data; the
caller decides what to keep. Loaded by file path where the package __init__ (pandas) is absent.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

REFUSED = {401, 403, 451}
GONE = {404, 410}
UA = "GHAZI-RADAR public-data research (github.com/GHAZMOTIEBIPRO/GHAZIBOT)"
_last_call: dict[str, float] = {}


@dataclass
class FetchResult:
    url: str
    outcome: str
    http: int | None = None
    body: bytes = b""
    last_modified: str | None = None
    etag: str | None = None
    error: str = ""
    attempts: int = 0
    seconds: float = 0.0
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.outcome == "OK"

    def status(self) -> str:
        """Short label for logs and published status fields (never the body)."""
        return self.outcome if self.http is None else f"{self.outcome}_HTTP_{self.http}"


def _space(host: str, min_interval: float, sleep: Callable[[float], None], clock: Callable[[], float]) -> None:
    wait = _last_call.get(host, -1e9) + min_interval - clock()
    if wait > 0:
        sleep(wait)
    _last_call[host] = clock()


def fetch(url: str, *, attempts: int = 3, timeout: float = 30, min_interval: float = 1.0,
          if_modified_since: str | None = None, etag: str | None = None, max_retry_after: float = 30,
          opener: Callable[..., object] = urllib.request.urlopen,
          sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> FetchResult:
    host = urllib.parse.urlsplit(url).netloc
    headers = {"User-Agent": UA}
    if if_modified_since:
        headers["If-Modified-Since"] = if_modified_since
    if etag:
        headers["If-None-Match"] = etag
    start = clock()
    result = FetchResult(url=url, outcome="NETWORK_ERROR")
    rate_limited_once = False
    attempt = 0
    while attempt < attempts:
        attempt += 1
        result.attempts = attempt
        _space(host, min_interval, sleep, clock)
        try:
            with opener(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
                result.http = getattr(response, "status", 200)
                result.body = response.read()
                hdrs = {k.lower(): v for k, v in response.headers.items()}
                result.headers, result.outcome, result.error = hdrs, "OK", ""
                result.last_modified, result.etag = hdrs.get("last-modified"), hdrs.get("etag")
                break
        except urllib.error.HTTPError as exc:
            result.http, result.error = exc.code, f"HTTP {exc.code}"
            if exc.code == 304:
                result.outcome = "NOT_MODIFIED"
                break
            if exc.code in REFUSED:
                result.outcome = "REFUSED"
                break
            if exc.code in GONE:
                result.outcome = "NOT_FOUND"
                break
            if exc.code == 429:
                result.outcome = "RATE_LIMITED"
                if rate_limited_once:
                    break
                rate_limited_once = True
                try:
                    delay = float(exc.headers.get("Retry-After") or 5)
                except (TypeError, ValueError):
                    delay = 5.0
                sleep(min(max(delay, 1.0), max_retry_after))
                attempt -= 1  # the one rate-limit retry does not use up an error retry
                continue
            result.outcome = "SERVER_ERROR" if exc.code >= 500 else "HTTP_ERROR"
            if exc.code < 500:
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            result.http, result.outcome = None, "NETWORK_ERROR"
            result.error = f"{type(exc).__name__}: {str(exc)[:160]}"
        if attempt < attempts:
            sleep(2 ** (attempt - 1))
    result.seconds = round(clock() - start, 2)
    return result
