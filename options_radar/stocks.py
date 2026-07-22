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
    def _liquidity_score(history: pd.DataFrame) -> tuple[float, float, str | None]:
        volume = pd.to_numeric(history["Volume"], errors="coerce")
        close = pd.to_numeric(history["Close"], errors="coerce")
        avg_dollar_volume = float((volume * close).tail(20).mean())
        if avg_dollar_volume >= 100_000_000:
            return 10.0, avg_dollar_volume, None
        if avg_dollar_volume >= 30_000_000:
            return 8.0, avg_dollar_volume, None
        if avg_dollar_volume >= 10_000_000:
            return 6.0, avg_dollar_volume, None
        if avg_dollar_volume >= 3_000_000:
            return 3.0, avg_dollar_volume, None
        return -8.0, avg_dollar_volume, "سيولة السهم ضعيفة"

    @staticmethod
    def _score(
        symbol: str,
        technical: TechnicalSnapshot,
        history: pd.DataFrame,
        regime: str,
        catalyst: dict | None,
    ) -> dict:
        liquidity, avg_dollar_volume, liquidity_reason = StockRadar._liquidity_score(history)
        bullish = max(0.0, liquidity)
        bearish = max(0.0, liquidity)
        bullish_reasons: list[str] = []
        bearish_reasons: list[str] = []
        if liquidity_reason:
            bullish += liquidity
            bearish += liquidity
            bullish_reasons.append(liquidity_reason)
            bearish_reasons.append(liquidity_reason)

        if technical.close > technical.ema9:
            bullish += 5
            bullish_reasons.append("السعر فوق EMA9")
        else:
            bearish += 5
            bearish_reasons.append("السعر تحت EMA9")

        if technical.ema9 > technical.ema21:
            bullish += 8
            bullish_reasons.append("EMA9 فوق EMA21")
        elif technical.ema9 < technical.ema21:
            bearish += 8
            bearish_reasons.append("EMA9 تحت EMA21")

        if technical.ema21 > technical.ema50:
            bullish += 8
            bullish_reasons.append("اتجاه متوسط صاعد")
        elif technical.ema21 < technical.ema50:
            bearish += 8
            bearish_reasons.append("اتجاه متوسط هابط")

        if technical.close > technical.ema200:
            bullish += 5
            bullish_reasons.append("فوق المتوسط 200")
        else:
            bearish += 5
            bearish_reasons.append("تحت المتوسط 200")

        if technical.macd > technical.macd_signal:
            bullish += 6
            bullish_reasons.append("MACD إيجابي")
        elif technical.macd < technical.macd_signal:
            bearish += 6
            bearish_reasons.append("MACD سلبي")

        if 50 <= technical.rsi14 <= 72:
            bullish += 5
            bullish_reasons.append("RSI صاعد صحي")
        elif 28 <= technical.rsi14 <= 48:
            bearish += 5
            bearish_reasons.append("RSI هابط دون تشبع")
        elif technical.rsi14 > 78:
            bullish -= 10
            bullish_reasons.append("تشبع شراء")
        elif technical.rsi14 < 22:
            bearish -= 10
            bearish_reasons.append("تشبع بيع")

        if technical.relative_volume20 >= 1.5:
            bullish += 8
            bearish += 8
            bullish_reasons.append("حجم نسبي قوي")
            bearish_reasons.append("حجم نسبي قوي")
        elif technical.relative_volume20 >= 1.15:
            bullish += 4
            bearish += 4

        bullish_breakout = (
            technical.breakout
            and technical.direction == "bullish"
            and technical.close >= technical.resistance20
        )
        bearish_breakdown = (
            technical.breakout
            and technical.direction == "bearish"
            and technical.close <= technical.support20
        )
        if bullish_breakout:
            bullish += 10
            bullish_reasons.append("اختراق 20 يومًا")
        if bearish_breakdown:
            bearish += 10
            bearish_reasons.append("كسر دعم 20 يومًا")

        catalyst_score = 0.0
        catalyst_text = "لا يوجد محفز قوي حديث"
        catalyst_url = ""
        catalyst_source = ""
        if catalyst:
            catalyst_score = max(-25.0, min(25.0, float(catalyst.get("score", 0))))
            if catalyst_score > 0:
                bullish += catalyst_score
                bullish_reasons.append(f"محفز إيجابي +{catalyst_score:.0f}")
            elif catalyst_score < 0:
                bearish += abs(catalyst_score)
                bearish_reasons.append(f"محفز سلبي {catalyst_score:.0f}")
            catalyst_text = f"{catalyst.get('category', '')}: {catalyst.get('headline', '')}"
            catalyst_url = str(catalyst.get("url", ""))
            catalyst_source = str(catalyst.get("source", ""))

        if regime == "risk_on":
            bullish += 5
            bearish -= 4
        elif regime == "risk_off":
            bearish += 5
            bullish -= 7

        if technical.direction == "bullish":
            bullish += 6
            bearish -= 8
        elif technical.direction == "bearish":
            bearish += 6
            bullish -= 8
        else:
            bullish -= 6
            bearish -= 6

        if technical.close > technical.resistance20 + 2.0 * technical.atr14:
            bullish -= 10
            bullish_reasons.append("الحركة الصاعدة ممتدة؛ الدخول متأخر")
        if technical.close < technical.support20 - 2.0 * technical.atr14:
            bearish -= 10
            bearish_reasons.append("الحركة الهابطة ممتدة؛ الدخول متأخر")

        setup_side = "call" if bullish >= bearish else "put"
        score = bullish if setup_side == "call" else bearish
        reasons = bullish_reasons if setup_side == "call" else bearish_reasons
        score = max(0.0, min(100.0, score))
        close_price = technical.close
        atr = max(technical.atr14, close_price * 0.005)

        if setup_side == "call":
            entry_low = max(technical.ema9, close_price - 0.30 * atr)
            entry_high = close_price + 0.12 * atr
            stop = max(technical.support20, close_price - 1.5 * atr)
            stop = min(stop, close_price * 0.98)
            target_1 = close_price + 1.5 * atr
            target_2 = close_price + 3.0 * atr
            trigger_type = "breakout" if bullish_breakout else "bullish_confirmation"
            direction_confirmed = technical.direction == "bullish"
        else:
            entry_low = close_price - 0.12 * atr
            entry_high = min(technical.ema9, close_price + 0.30 * atr)
            stop = min(technical.resistance20, close_price + 1.5 * atr)
            stop = max(stop, close_price * 1.02)
            target_1 = close_price - 1.5 * atr
            target_2 = close_price - 3.0 * atr
            trigger_type = "breakdown" if bearish_breakdown else "bearish_confirmation"
            direction_confirmed = technical.direction == "bearish"

        entry_low, entry_high = sorted((entry_low, entry_high))
        has_directional_catalyst = catalyst_score >= 15 if setup_side == "call" else catalyst_score <= -15
        trigger_confirmed = bullish_breakout if setup_side == "call" else bearish_breakdown
        new_stock_setup = bool(
            score >= 78
            and direction_confirmed
            and (trigger_confirmed or has_directional_catalyst)
        )
        setup_status = (
            "strong_setup"
            if new_stock_setup
            else "qualified"
            if score >= 65
            else "watchlist"
        )

        return {
            "symbol": symbol,
            "score": round(score, 1),
            "rating": (
                "A+"
                if score >= 90
                else "A"
                if score >= 82
                else "B+"
                if score >= 74
                else "B"
                if score >= 65
                else "C"
            ),
            "setup_side": setup_side,
            "setup_status": setup_status,
            "trigger_type": trigger_type,
            "price": round(close_price, 2),
            "entry_low": round(entry_low, 2),
            "entry_high": round(entry_high, 2),
            "target_1": round(target_1, 2),
            "target_2": round(target_2, 2),
            "stop": round(stop, 2),
            "invalidation": round(stop, 2),
            "rsi": round(technical.rsi14, 1),
            "relative_volume": round(technical.relative_volume20, 2),
            "avg_dollar_volume": round(avg_dollar_volume, 0),
            "breakout": trigger_confirmed,
            "technical_direction": technical.direction,
            "catalyst_score": catalyst_score,
            "catalyst": catalyst_text,
            "catalyst_source": catalyst_source,
            "catalyst_url": catalyst_url,
            "reasons": "؛ ".join(dict.fromkeys(reasons)),
            "market_regime": regime,
            "new_stock_setup": new_stock_setup,
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
