from __future__ import annotations
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SOURCES = [
    ("dhawalc/spx-gamma-levels", "https://raw.githubusercontent.com/dhawalc/spx-gamma-levels/main/data/latest.json"),
    ("Alexduanran/spx-0dte-archive", "https://raw.githubusercontent.com/Alexduanran/spx-0dte-archive/main/gex/summary.csv"),
    ("itsfabtrading/Gex-Multi", "https://raw.githubusercontent.com/itsfabtrading/Gex-Multi/master/README.md"),
    ("MitchelTurner/GEX", "https://raw.githubusercontent.com/MitchelTurner/GEX/main/README.md"),
]

def check(name, url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GHAZI-Black-Box/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read()
        return {"name": name, "ok": True, "bytes": len(data), "status": getattr(r, "status", 200)}
    except Exception as exc:
        return {"name": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

results = [check(*x) for x in SOURCES]
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "policy": "health_only_never_signal_authority",
    "overall": "healthy" if any(x["ok"] for x in results) else "degraded",
    "sources": results,
}
out = Path("public/data/free_data_health.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False))
