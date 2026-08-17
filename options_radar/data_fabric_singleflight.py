from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Hashable, TypeVar

T = TypeVar("T")


@dataclass
class _Flight:
    event: threading.Event = field(default_factory=threading.Event)
    value: Any = None
    error: BaseException | None = None


class SingleFlightGroup:
    """Collapse only overlapping identical calls; never cache completed work.

    A leader executes the loader while concurrent followers with the same key
    wait for that exact result. The key is removed as soon as the leader
    completes, so a later call always performs a fresh fetch. Every caller gets
    a deep copy to keep mutable DataFrames/metadata isolated.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._flights: dict[Hashable, _Flight] = {}

    def do(
        self,
        key: Hashable,
        loader: Callable[[], T],
        *,
        clone: Callable[[T], T] = copy.deepcopy,
    ) -> tuple[T, bool]:
        with self._lock:
            flight = self._flights.get(key)
            leader = flight is None
            if leader:
                flight = _Flight()
                self._flights[key] = flight

        assert flight is not None
        if leader:
            try:
                flight.value = loader()
            except BaseException as exc:
                flight.error = exc
            finally:
                flight.event.set()
                with self._lock:
                    if self._flights.get(key) is flight:
                        self._flights.pop(key, None)

            if flight.error is not None:
                raise flight.error
            return clone(flight.value), False

        flight.event.wait()
        if flight.error is not None:
            raise flight.error
        return clone(flight.value), True

    def in_flight_count(self) -> int:
        with self._lock:
            return len(self._flights)


_GROUP = SingleFlightGroup()


def _time_key(value: Any) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return str(isoformat())
        except Exception:
            pass
    return str(value)


def _provider_key(providers: list[str] | tuple[str, ...] | None, fallback: Any) -> tuple[str, ...]:
    if providers is not None:
        return tuple(str(item).strip().lower() for item in providers if str(item).strip())
    return tuple(
        item.strip().lower()
        for item in str(fallback or "").split(",")
        if item.strip()
    )


def _annotate(result: Any, *, shared: bool) -> Any:
    metadata = getattr(result, "metadata", None)
    if isinstance(metadata, dict):
        metadata["singleflight"] = {
            "shared_in_flight_request": bool(shared),
            "post_completion_cache": False,
            "freshness_timestamp_preserved": True,
        }
    return result


def install_data_fabric_singleflight() -> None:
    """Wrap the installed Data Fabric with zero-staleness request coalescing.

    Call this *after* ``install_data_fabric()``. It changes acquisition
    efficiency only: no TTL is used, no quote survives completion as a cache,
    and the original fetched_at/freshness metadata is preserved.
    """

    from options_radar import hybrid_fetcher as hybrid

    DataFetcher = hybrid.DataFetcher
    if getattr(DataFetcher, "_ghazi_singleflight_v1", False):
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
        normalized_symbol = str(symbol or "").strip().upper()
        provider_fallback = (
            getattr(self.settings, "daily_provider_order", "")
            if interval == "1d"
            else getattr(self.settings, "intraday_provider_order", "")
        )
        provider_signature = _provider_key(providers, provider_fallback)
        key = (
            "stock_bars",
            normalized_symbol,
            str(interval),
            _time_key(start),
            _time_key(end),
            provider_signature,
        )
        result, shared = _GROUP.do(
            key,
            lambda: original_stock(
                self,
                normalized_symbol,
                start=start,
                end=end,
                interval=interval,
                providers=providers,
            ),
        )
        return _annotate(result, shared=shared)

    def option_chain(
        self: Any,
        symbol: str,
        *,
        min_dte: int | None = None,
        max_dte: int | None = None,
        providers: list[str] | None = None,
        apply_guards: bool = True,
    ):
        normalized_symbol = str(symbol or "").strip().upper()
        minimum = int(min_dte if min_dte is not None else self.settings.min_dte)
        maximum = int(max_dte if max_dte is not None else self.settings.max_dte)
        provider_signature = _provider_key(
            providers,
            getattr(self.settings, "options_provider_order", ""),
        )
        key = (
            "option_chain",
            normalized_symbol,
            minimum,
            maximum,
            provider_signature,
            bool(apply_guards),
        )
        result, shared = _GROUP.do(
            key,
            lambda: original_options(
                self,
                normalized_symbol,
                min_dte=min_dte,
                max_dte=max_dte,
                providers=providers,
                apply_guards=apply_guards,
            ),
        )
        return _annotate(result, shared=shared)

    DataFetcher.fetch_stock_bars = stock_bars
    DataFetcher.fetch_option_chain = option_chain
    DataFetcher._ghazi_singleflight_v1 = True
