from __future__ import annotations

import csv
import io
import json
import math
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from .ghazi_gex_multi import build as build_ghazi_gex

CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json"
SOURCES = {
    "dhawalc/spx-gamma-levels": "https://raw.githubusercontent.com/dhawalc/spx-gamma-levels/main/data/latest.json",
    "Alexduanran/spx-0dte-archive": "https://raw.githubusercontent.com/Alexduanran/spx-0dte-archive/main/gex/summary.csv",
    "itsfabtrading/Gex-Multi": "https://raw.githubusercontent.com/itsfabtrading/Gex-Multi/master/README.md",
    "MitchelTurner/GEX": "https://raw.githubusercontent.com/MitchelTurner/GEX/main/README.md",
}
HISTORY = Path("public/data/free_gex_validation_history.json")
OUT = Path("public/data/free_gex_validation.json")


def get(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "GHAZI-Black-Box/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def num(x: Any) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def fetch_json_source(name: str, url: str) -> dict[str, Any]:
    raw = json.loads(get(url).decode("utf-8"))
    if name == "dhawalc/spx-gamma-levels":
        return {
            "available": True, "source": name, "spot": num(raw.get("spot")),
            "gex": num(raw.get("net_gex_dollars")),
            "flip": num(raw.get("zero_gamma_flip")),
            "call_wall": num(raw.get("call_wall")),
            "put_wall": num(raw.get("put_wall")),
            "regime": raw.get("gamma_regime"),
        }
    raise ValueError("unsupported JSON source")


def fetch_archive(url: str) -> dict[str, Any]:
    rows = list(csv.DictReader(io.StringIO(get(url).decode("utf-8"))))
    if not rows:
        raise ValueError("archive empty")
    r = rows[-1]
    return {
        "available": True, "source": "Alexduanran/spx-0dte-archive",
        "spot": num(r.get("spot")), "gex": num(r.get("net_0dte_gex")),
        "flip": num(r.get("gamma_flip_proxy")),
        "call_wall": num(r.get("call_wall")), "put_wall": num(r.get("put_wall")),
        "contracts": num(r.get("contracts")),
        "timestamp": f"{r.get('date','')}T{r.get('time','')}:00",
        "spxw_0dte": True,
    }


def fetch_cboe(url: str) -> dict[str, Any]:
    raw = json.loads(get(url).decode("utf-8"))
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        raise ValueError("unexpected CBOE payload")
    options = data.get("options") or []
    spxw = [x for x in options if str(x.get("option", "")).upper().startswith("SPXW")]
    return {
        "available": True, "source": "CBOE delayed public",
        "spot": num(data.get("current_price") or data.get("price")),
        "contracts": len(spxw),
        "spxw_0dte": True,
        "note_ar": "CBOE العام مؤخر؛ ليس مصدراً لتنفيذ لحظي.",
    }


def safe_fetch(name: str, fn) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:
        return {"available": False, "source": name, "error": f"{type(exc).__name__}: {exc}"}


def relative_disagreement(values: list[float]) -> float | None:
    values = [v for v in values if v is not None and math.isfinite(v)]
    if len(values) < 2:
        return None
    m = median(values)
    if not m:
        return None
    return round((max(values) - min(values)) / abs(m), 4)


def compare_metric(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    vals = [num(r.get(key)) for r in rows if r.get("available")]
    vals = [v for v in vals if v is not None]
    return {
        "count": len(vals),
        "median": median(vals) if vals else None,
        "relative_disagreement": relative_disagreement(vals),
    }


def build() -> dict[str, Any]:
    rows = [
        safe_fetch("dhawalc/spx-gamma-levels", lambda: fetch_json_source("dhawalc/spx-gamma-levels", SOURCES["dhawalc/spx-gamma-levels"])),
        safe_fetch("Alexduanran/spx-0dte-archive", lambda: fetch_archive(SOURCES["Alexduanran/spx-0dte-archive"])),
        safe_fetch("CBOE delayed public", lambda: fetch_cboe(CBOE_URL)),
    ]
    ghazi_engine = safe_fetch("ghazi_gex_multi_reimplementation", lambda: build_ghazi_gex())
    metrics = {k: compare_metric(rows, k) for k in ("spot", "gex", "flip", "call_wall", "put_wall")}
    usable = sum(bool(r.get("available")) for r in rows)
    engine_available = bool(ghazi_engine.get("available"))
    if engine_available:
        rows.append({
            "available": True,
            "source": "ghazi_gex_multi_reimplementation",
            "spot": num(ghazi_engine.get("spot")),
            "gex": num(ghazi_engine.get("net_gex")),
            "flip": num(ghazi_engine.get("gamma_flip")),
            "call_wall": num(ghazi_engine.get("call_wall")),
            "put_wall": num(ghazi_engine.get("put_wall")),
            "regime": ghazi_engine.get("gamma_regime"),
        })
        usable += 1
    agreement_votes = []
    for key, m in metrics.items():
        d = m["relative_disagreement"]
        if d is not None:
            agreement_votes.append(d <= (0.015 if key == "spot" else 0.06))
    agreement = sum(agreement_votes) / len(agreement_votes) if agreement_votes else 0.0

    decision = "SHADOW_ONLY"
    reasons = [
        "مصادر البحث لا تملك سلطة منفردة على الإشارة.",
        "CBOE العام مؤخر؛ بعض المستودعات البحثية ليست تغذية لحظية.",
        "لا يتم اعتماد مصدر جديد إلا بعد عينة تاريخية كافية واختبار walk-forward.",
    ]
    if usable < 2:
        reasons.append("عدد المصادر القابلة للمقارنة أقل من 2.")
    if agreement < 0.60:
        reasons.append("التوافق الحالي أقل من 60%.")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": "shadow_validation_never_signal_authority",
        "decision": decision,
        "source_count_available": usable,
        "agreement_score": round(agreement, 3),
        "metrics": metrics,
        "sources": rows,
        "integrated_engines": {
            "ghazi_gex_multi": ghazi_engine,
            "upstream_methodology": ["itsfabtrading/Gex-Multi", "MitchelTurner/GEX"],
            "integration_mode": "original_reimplementation_shadow_only"
        },
        "research_indicators_ar": [
            "GEX", "Gamma Flip", "Call Wall", "Put Wall", "0DTE GEX",
            "GCI", "PGR", "GDW", "CAR", "DEX", "Vanna", "Charm",
            "Vomma", "Zomma", "IV Rank", "IV Percentile", "Skew",
            "Term Structure", "Expected Move", "Realized Volatility",
            "Put/Call OI", "Volume/OI", "Signed Flow", "Liquidity",
            "VWAP", "RSI", "ATR", "Event Risk"
        ],
        "reliability_policy_ar": {
            "minimum_samples": 100,
            "walk_forward_required": True,
            "max_source_weight_before_validation": 0.0,
            "promotion_requires": "agreement + freshness + outcome stability",
        },
        "reasons_ar": reasons,\n        "promotion_status_ar": "محرك GEX الجديد مدمج فعلياً ويحسب المستويات وGreeks المتقدمة، لكنه لا يملك سلطة على CALL/PUT قبل اكتمال الاختبار التاريخي.",
    }

    history = []
    if HISTORY.exists():
        try:
            history = json.loads(HISTORY.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []
    history.append({
        "generated_at": payload["generated_at"],
        "available": usable,
        "agreement_score": payload["agreement_score"],
        "metrics": metrics,
    })
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(history[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
