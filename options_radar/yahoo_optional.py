"""Lazy, optional access to yfinance.

Yahoo's terms block automated access (CLAUDE.md, source_permissions.py), so every call site checks
`require("yahoo")` / `allowed("yahoo")` first and the library is never used while that gate is closed.
Importing yfinance at module load still cost every workflow 37 of 55 runtime packages (2026-11-19
measurement, including curl-cffi), so it now lives in requirements-legacy.txt and is imported on
first real use only. If the gate is ever opened, install requirements-legacy.txt as well.
"""
from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

LEGACY_HINT = "install requirements-legacy.txt (needed only when the Yahoo gate is approved)"


class _LazyModule:
    """Imports the named module on the first attribute access; tests may set attributes on it."""

    def __init__(self, name: str) -> None:
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_module", None)

    def _load(self) -> ModuleType:
        module = object.__getattribute__(self, "_module")
        if module is None:
            name = object.__getattribute__(self, "_name")
            try:
                module = importlib.import_module(name)
            except ModuleNotFoundError as exc:
                raise ModuleNotFoundError(f"{name} is not installed: {LEGACY_HINT}") from exc
            object.__setattr__(self, "_module", module)
        return module

    def __getattr__(self, attr: str) -> Any:
        if attr.startswith("__"):
            raise AttributeError(attr)
        return getattr(self._load(), attr)


yf: Any = _LazyModule("yfinance")
