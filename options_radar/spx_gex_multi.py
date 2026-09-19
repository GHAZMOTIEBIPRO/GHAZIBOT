from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any


URL = os.getenv(
    "SPX_GEX_MULTI_URL",
    "https://raw.githubusercontent.com/itsfabtrading/Gex-Multi/main/data/SPX.json",
)


def _get(url: str, timeout: int = 12) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "GHAZI-Black-Box/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def fetch_gex_multi(timeout: int = 12) -> dict[str, Any]:
    raw = json.loads(_get(URL, timeout).decode("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Unexpected Gex-Multi payload")
    return {
        "available": True,
        "source": "itsfabtrading/Gex-Multi",
        "source_url": URL,
        "raw": raw,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "affects_signal_score": False,
        "policy": "shadow_context_only",
    }
