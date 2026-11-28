"""Arabic PNG of one pre-open price map (options_radar.premarket_map). Deterministic, no AI imagery.

Draws only what the map holds, on a real price scale:
- observed completed daily candles (solid) - never a forming bar;
- WAIT band (gray), CALL zone above its trigger (blue), PUT zone below its trigger (yellow);
- triggers (CALL blue, PUT yellow), T1/T2/T3 (purple), invalidation (red), daily pivot and
  support/resistance (gray), the reference price with its type and time;
- the two conditional scenarios as dashed arrows from the reference to each T1 (hypothetical
  paths are dashed, never drawn as candles).
Labels sit in a right-hand column, pushed apart so none overlap, each joined to its level.

Text: matplotlib >= 3.11 shapes Arabic and lays out right-to-left runs itself (complex text
layout), so labels are passed in logical order; no reshaper or bidi package. Fonts: Noto Sans
Arabic (OFL, assets/fonts) with DejaVu Sans for Latin and digits.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
COLORS = {"call": "#1f6feb", "put": "#d4a20a", "target": "#7b3fbf", "invalid": "#cf222e",
          "neutral": "#6e7781", "ref": "#111111", "up": "#1a7f37", "down": "#cf222e"}
def _fonts():
    from matplotlib import font_manager

    for path in FONT_DIR.glob("*.ttf"):
        font_manager.fontManager.addfont(str(path))
    return ["Noto Sans Arabic", "DejaVu Sans"]


def _spread(ys: list[float], gap: float) -> list[float]:
    """Push label positions apart by at least `gap`, keeping order, staying near the levels."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    placed = [ys[i] for i in order]
    for k in range(1, len(placed)):
        placed[k] = max(placed[k], placed[k - 1] + gap)
    shift = (sum(placed) - sum(ys[i] for i in order)) / len(placed) if placed else 0
    placed = [p - shift for p in placed]
    for k in range(1, len(placed)):
        placed[k] = max(placed[k], placed[k - 1] + gap)
    out = [0.0] * len(ys)
    for k, i in enumerate(order):
        out[i] = placed[k]
    return out


def levels(m: dict[str, Any]) -> list[dict[str, Any]]:
    """Every horizontal level of the map with its Arabic label and color (shared by tests)."""
    rows = [{"value": m["call"]["trigger"], "label": "محفز CALL", "color": COLORS["call"], "width": 2.2},
            {"value": m["put"]["trigger"], "label": "محفز PUT", "color": COLORS["put"], "width": 2.2},
            {"value": m["call"]["invalidation"], "label": "إبطال CALL", "color": COLORS["invalid"], "width": 1.2},
            {"value": m["put"]["invalidation"], "label": "إبطال PUT", "color": COLORS["invalid"], "width": 1.2},
            {"value": m["pivot"], "label": "المحور اليومي", "color": COLORS["neutral"], "width": 1.2}]
    for side, word in (("call", "CALL"), ("put", "PUT")):
        for t in m[side]["targets"]:
            rows.append({"value": t["value"], "label": f"{t['name']} {word}", "color": COLORS["target"], "width": 1.4})
    for key, word in (("resistance", "مقاومة"), ("support", "دعم")):
        lv = (m.get("levels_sr") or {}).get(key)
        if lv:
            rows.append({"value": lv["value"], "label": f"{word} ({lv['basis_ar']})", "color": COLORS["neutral"],
                         "width": 1.0, "style": ":"})
    return rows


def render_png(m: dict[str, Any], candles: list[dict[str, Any]] | None, *, title_ar: str, footer_ar: str) -> bytes:
    """PNG bytes, 1080x1350 (phone portrait). Raises ValueError for a NO_DATA map."""
    if m.get("state") in (None, "NO_DATA"):
        raise ValueError("no chart for a NO_DATA map")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, Rectangle

    family = _fonts()
    plt.rcParams.update({"font.family": family, "axes.unicode_minus": False})
    fig = plt.figure(figsize=(7.2, 9.0), dpi=150)
    ax = fig.add_axes((0.10, 0.12, 0.52, 0.76))
    lab = fig.add_axes((0.62, 0.12, 0.37, 0.76), sharey=ax)
    lab.axis("off")
    rows = levels(m)
    bars = [c for c in (candles or []) if all(isinstance(c.get(k), (int, float)) for k in ("open", "high", "low", "close"))]
    ref = m["reference"]["price"]
    values = [r["value"] for r in rows] + [ref] + [c["high"] for c in bars] + [c["low"] for c in bars]
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.06 or 1.0
    ax.set_ylim(lo - pad, hi + pad)
    n = len(bars)
    xmax = n + 5
    ax.set_xlim(-1, xmax)
    # zones
    ax.add_patch(Rectangle((-1, m["wait_band"]["low"]), xmax + 1, m["wait_band"]["high"] - m["wait_band"]["low"],
                           color=COLORS["neutral"], alpha=0.10, lw=0))
    ax.add_patch(Rectangle((-1, m["call"]["trigger"]), xmax + 1, hi + pad - m["call"]["trigger"],
                           color=COLORS["call"], alpha=0.07, lw=0))
    ax.add_patch(Rectangle((-1, lo - pad), xmax + 1, m["put"]["trigger"] - (lo - pad),
                           color=COLORS["put"], alpha=0.10, lw=0))
    zone_font = {"fontsize": 10, "ha": "left", "fontweight": "bold", "alpha": 0.85}
    ax.text(-0.6, m["wait_band"]["low"] + 0.8 * (m["wait_band"]["high"] - m["wait_band"]["low"]), "منطقة الانتظار",
            color=COLORS["neutral"], va="center", **zone_font)
    ax.text(-0.6, hi + pad * 0.5, "منطقة CALL", color=COLORS["call"], va="center", **zone_font)
    ax.text(-0.6, lo - pad * 0.5, "منطقة PUT", color=COLORS["put"], va="center", **zone_font)
    # observed candles (solid)
    for i, c in enumerate(bars, start=1):
        color = COLORS["up"] if c["close"] >= c["open"] else COLORS["down"]
        ax.vlines(i, c["low"], c["high"], color=color, lw=1.0)
        body_lo, body_hi = sorted((c["open"], c["close"]))
        ax.add_patch(Rectangle((i - 0.32, body_lo), 0.64, max(body_hi - body_lo, (hi - lo) * 0.002), color=color, lw=0))
    for r in rows:
        ax.axhline(r["value"], color=r["color"], lw=r["width"], ls=r.get("style", "-"), alpha=0.9)
    # reference and dashed hypothetical paths to each T1
    x_ref = n + 1.2
    ax.plot([x_ref], [ref], marker="o", color=COLORS["ref"], ms=7, zorder=5)
    for side, color in (("call", COLORS["call"]), ("put", COLORS["put"])):
        targets = m[side]["targets"]
        if targets:
            ax.add_patch(FancyArrowPatch((x_ref, ref), (xmax - 0.6, targets[0]["value"]), arrowstyle="-|>",
                                         mutation_scale=14, color=color, lw=1.6, ls="--", zorder=4))
    ax.yaxis.tick_left()
    ax.tick_params(axis="y", labelsize=10)
    ax.set_xticks([])
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    # label column, de-overlapped
    span = (hi - lo) + 2 * pad
    entries = [*rows, {"value": ref, "label": "المرجع", "color": COLORS["ref"]}]
    ys = _spread([e["value"] for e in entries], span * 0.034)
    for e, y in zip(entries, ys, strict=True):
        lab.plot([0.0, 0.06], [e["value"], y], color=e["color"], lw=0.8)
        lab.text(0.08, y, f"{e['value']:,.2f}", color=e["color"], fontsize=10, va="center", ha="left",
                 family="DejaVu Sans", fontweight="bold")
        lab.text(0.98, y, (e["label"]), color=e["color"], fontsize=10.5, va="center", ha="right")
    lab.set_xlim(0, 1)
    fig.text(0.97, 0.955, (title_ar), ha="right", va="center", fontsize=15, fontweight="bold")
    sub = f"{m['state_ar']} — المرجع {ref:,.2f} ({m['reference']['type_ar']}، {m['reference']['time_ar']})"
    fig.text(0.97, 0.915, (sub), ha="right", va="center", fontsize=11.5)
    fig.text(0.97, 0.06, (footer_ar), ha="right", va="center", fontsize=8.5, color=COLORS["neutral"])
    fig.text(0.97, 0.03, ("خطوط متقطعة = سيناريو افتراضي، الشموع = جلسات مكتملة فعلية. ليست توصية."),
             ha="right", va="center", fontsize=8.5, color=COLORS["neutral"])
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
