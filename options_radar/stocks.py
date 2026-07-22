from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .catalysts import best_catalyst_map
from .indicators import TechnicalSnapshot, analyze_technical, market_regime
from .providers import get_price_history
from .settings import Settings


@dataclass
class StockScanResult:
    opportunities: pd.DataFrame
    errors: dict[str, str]
    regime: str


class StockRadar:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _technical(self, symbol: str) -> tuple[TechnicalSnapshot, pd.DataFrame]:
        history = get_price_history(symbol, period="1y")
        return analyze_technical(symbol, history), history

    def _market_regime(self) -> str:
        spy, _ = self._technical("SPY")
        qqq, _ = self._technical("QQQ")
        vix = get_price_history("^VIX", period="3mo")
        vix_close = 20.0 if vix.empty else float(vix["Close"].dropna().iloc[-1])
        return market_regime(spy, qqq, vix_close)

    @staticmethod
    def _score(
        symbol: str,
        technical: TechnicalSnapshot,
        history: pd.DataFrame,
        regime: str,
        catalyst: dict | None,
    ) -> dict:
        score = 0.0
        reasons: list[str] = []
        if technical.close > technical.ema9:
            score += 5
            reasons.append("السعر فوق EMA9")
        if technical.ema9 > technical.ema21:
            score += 8
            reasons.append("EMA9 فوق EMA21")
        if technical.ema21 > technical.ema50:
            score += 8
            reasons.append("اتجاه متوسط صاعد")
        if technical.close > technical.ema200:
            score += 5
            reasons.append("فوق المتوسط 200")
        if technical.macd > technical.macd_signal:
            score += 6
            reasons.append("MACD إيجابي")
        if 50 <= technical.rsi14 <= 72:
            score += 5
            reasons.append("RSI صحي")
        elif technical.rsi14 > 78:
            score -= 10
            reasons.append("تشبع شراء")
        if technical.relative_volume20 >= 1.5:
            score += 8
            reasons.append("حجم نسبي قوي")
        elif technical.relative_volume20 >= 1.15:
            score += 4
            reasons.append("حجم فوق المتوسط")
        if technical.breakout and technical.direction == "bullish":
            score += 10
            reasons.append("اختراق 20 يومًا")

        volume = pd.to_numeric(history["Volume"], errors="coerce")
        close = pd.to_numeric(history["Close"], errors="coerce")
        avg_dollar_volume = float((volume * close).tail(20).mean())
        if avg_dollar_volume >= 100_000_000:
            score += 10
        elif avg_dollar_volume >= 30_000_000:
            score += 8
        elif avg_dollar_volume >= 10_000_000:
            score += 6
        elif avg_dollar_volume >= 3_000_000:
            score += 3
        else:
            score -= 8
            reasons.append("سيولة السهم ضعيفة")

        catalyst_score = 0.0
        catalyst_text = "لا يوجد محفز قوي حديث"
        catalyst_url = ""
        catalyst_source = ""
        if catalyst:
            catalyst_score = max(-25.0, min(25.0, float(catalyst.get("score", 0))))
            score += catalyst_score
            catalyst_text = f"{catalyst.get('category', '')}: {catalyst.get('headline', '')}"
            catalyst_url = str(catalyst.get("url", ""))
            catalyst_source = str(catalyst.get("source", ""))
            reasons.append(f"محفز {catalyst_score:+.0f}")

        if regime == "risk_on":
            score += 5
        elif regime == "risk_off":
            score -= 7
        if technical.direction != "bullish":
            score -= 12
        if technical.close > technical.resistance20 + 2.0 * technical.atr14:
            score -= 8
            reasons.append("السعر ممتد بعيدًا عن نقطة الاختراق")

        score = max(0.0, min(100.0, score))
        close_price = technical.close
        entry_low = max(technical.ema9, close_price - 0.30 * technical.atr14)
        entry_high = close_price + 0.12 * technical.atr14
        stop = max(technical.support20, close_price - 1.5 * technical.atr14)
        stop = min(stop, close_price * 0.98)
        target_1 = close_price + 1.5 * technical.atr14
        target_2 = close_price + 3.0 * technical.atr14
        return {
            "symbol": symbol,
            "score": round(score, 1),
            "rating": "A+" if score >= 90 else "A" if score >= 82 else "B+" if score >= 74 else "B" if score >= 65 else "C",
            "price": round(close_price, 2),
            "entry_low": round(entry_low, 2),
            "entry_high": round(entry_high, 2),
            "target_1": round(target_1, 2),
            "target_2": round(target_2, 2),
            "stop": round(stop, 2),
            "rsi": round(technical.rsi14, 1),
            "relative_volume": round(technical.relative_volume20, 2),
            "avg_dollar_volume": round(avg_dollar_volume, 0),
            "breakout": technical.breakout,
            "technical_direction": technical.direction,
            "catalyst_score": catalyst_score,
            "catalyst": catalyst_text,
            "catalyst_source": catalyst_source,
            "catalyst_url": catalyst_url,
            "reasons": "؛ ".join(reasons),
            "market_regime": regime,
            "new_stock_setup": bool(
                score >= 78
                and technical.direction == "bullish"
                and (technical.breakout or catalyst_score >= 15)
            ),
        }

    def scan(
        self,
        symbols: list[str],
        catalysts: pd.DataFrame | None = None,
        top: int = 15,
        output_csv: str | Path | None = None,
    ) -> StockScanResult:
        symbols = list(dict.fromkeys(str(s).strip().upper() for s in symbols if str(s).strip()))
        if not symbols:
            raise ValueError("At least one symbol is required")
        regime = self._market_regime()
        catalyst_map = best_catalyst_map(catalysts if catalysts is not None else pd.DataFrame())
        rows: list[dict] = []
        errors: dict[str, str] = {}
        workers = max(1, min(self.settings.max_workers, len(symbols)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self._technical, symbol): symbol for symbol in symbols}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    technical, history = future.result()
                    rows.append(self._score(symbol, technical, history, regime, catalyst_map.get(symbol)))
                except Exception as exc:
                    errors[symbol] = str(exc)
        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame = frame[frame["score"] >= 55].sort_values(
                ["score", "catalyst_score", "relative_volume"],
                ascending=[False, False, False],
            ).head(top).reset_index(drop=True)
        if output_csv:
            path = Path(output_csv)
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(path, index=False)
        return StockScanResult(frame, errors, regime)
