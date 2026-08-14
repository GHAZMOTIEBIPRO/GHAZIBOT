from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import math
import pandas as pd


@dataclass(frozen=True)
class TimeframeView:
    timeframe: str
    score: int
    direction: str
    close: float
    sma20: float | None
    sma50: float | None
    sma200: float | None
    support: float | None
    resistance: float | None
    last_swing_low: float | None
    last_swing_high: float | None
    volume_ratio: float | None
    breakout: bool
    breakdown: bool
    breakout_retest: bool
    breakdown_retest: bool
    trendline_bias: str
    pattern: str
    candle: str
    reasons_ar: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClassicalDirection:
    symbol: str
    decision: str
    priority: str
    agreement_score: int
    horizon: str
    price: float
    confirmation_level: float | None
    invalidation_level: float | None
    daily: TimeframeView
    hourly: TimeframeView
    intraday: TimeframeView
    reasons_ar: tuple[str, ...]
    limitations_ar: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "daily": self.daily.as_dict(),
            "hourly": self.hourly.as_dict(),
            "intraday": self.intraday.as_dict(),
        }


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        if len(set(data.columns.get_level_values(0))) == 1:
            data.columns = data.columns.get_level_values(-1)
        elif len(set(data.columns.get_level_values(-1))) == 1:
            data.columns = data.columns.get_level_values(0)
    aliases = {str(column).lower(): column for column in data.columns}
    required: dict[str, Any] = {}
    for canonical in ("Open", "High", "Low", "Close", "Volume"):
        source = aliases.get(canonical.lower())
        if source is None:
            return pd.DataFrame()
        required[canonical] = pd.to_numeric(data[source], errors="coerce")
    clean = pd.DataFrame(required, index=data.index).dropna(subset=["Open", "High", "Low", "Close"])
    clean = clean[clean["Close"] > 0]
    return clean


def _swing_points(data: pd.DataFrame, window: int = 2) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    if len(data) < 2 * window + 5:
        return [], []
    highs = data["High"]
    lows = data["Low"]
    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []
    for index in range(window, len(data) - window):
        high = _number(highs.iloc[index])
        low = _number(lows.iloc[index])
        high_slice = highs.iloc[index - window : index + window + 1]
        low_slice = lows.iloc[index - window : index + window + 1]
        other_highs = high_slice.drop(high_slice.index[window])
        other_lows = low_slice.drop(low_slice.index[window])
        if high >= _number(high_slice.max()) and high > _number(other_highs.max()):
            swing_highs.append((index, high))
        if low <= _number(low_slice.min()) and low < _number(other_lows.min()):
            swing_lows.append((index, low))
    return swing_highs, swing_lows


def _trendline_bias(
    price: float,
    swing_highs: list[tuple[int, float]],
    swing_lows: list[tuple[int, float]],
    last_index: int,
) -> str:
    bullish = False
    bearish = False
    if len(swing_lows) >= 2:
        (x1, y1), (x2, y2) = swing_lows[-2], swing_lows[-1]
        if x2 > x1 and y2 > y1:
            projected = y2 + ((y2 - y1) / (x2 - x1)) * max(last_index - x2, 0)
            bullish = price >= projected * 0.995
    if len(swing_highs) >= 2:
        (x1, y1), (x2, y2) = swing_highs[-2], swing_highs[-1]
        if x2 > x1 and y2 < y1:
            projected = y2 + ((y2 - y1) / (x2 - x1)) * max(last_index - x2, 0)
            bearish = price <= projected * 1.005
    if bullish and not bearish:
        return "BULLISH"
    if bearish and not bullish:
        return "BEARISH"
    return "NEUTRAL"


def _double_pattern(
    swing_highs: list[tuple[int, float]],
    swing_lows: list[tuple[int, float]],
    tolerance: float = 0.012,
) -> str:
    if len(swing_lows) >= 2:
        (_, a), (_, b) = swing_lows[-2], swing_lows[-1]
        midpoint = max((abs(a) + abs(b)) / 2, 1e-9)
        if abs(a - b) / midpoint <= tolerance:
            return "DOUBLE_BOTTOM"
    if len(swing_highs) >= 2:
        (_, a), (_, b) = swing_highs[-2], swing_highs[-1]
        midpoint = max((abs(a) + abs(b)) / 2, 1e-9)
        if abs(a - b) / midpoint <= tolerance:
            return "DOUBLE_TOP"
    return "NONE"


def _candle_signal(data: pd.DataFrame) -> str:
    if len(data) < 2:
        return "NONE"
    prev = data.iloc[-2]
    last = data.iloc[-1]
    po, pc = _number(prev["Open"]), _number(prev["Close"])
    o, h, l, c = (_number(last[key]) for key in ("Open", "High", "Low", "Close"))
    body = abs(c - o)
    candle_range = max(h - l, 1e-9)
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)

    if pc < po and c > o and o <= pc and c >= po:
        return "BULLISH_ENGULFING"
    if pc > po and c < o and o >= pc and c <= po:
        return "BEARISH_ENGULFING"
    if body / candle_range <= 0.45 and lower_wick >= body * 2 and upper_wick <= max(body, candle_range * 0.2):
        return "HAMMER"
    if body / candle_range <= 0.45 and upper_wick >= body * 2 and lower_wick <= max(body, candle_range * 0.2):
        return "SHOOTING_STAR"
    return "NONE"


def analyze_timeframe(frame: pd.DataFrame, timeframe: str) -> TimeframeView:
    data = _clean_frame(frame)
    minimum = 220 if timeframe == "1D" else 80
    if len(data) < minimum:
        raise ValueError(f"{timeframe}: insufficient history ({len(data)} < {minimum})")

    close = data["Close"]
    volume = data["Volume"].fillna(0)
    sma20_series = close.rolling(20).mean()
    sma50_series = close.rolling(50).mean()
    sma200_series = close.rolling(200).mean()
    sma20 = _number(sma20_series.iloc[-1]) or None
    sma50 = _number(sma50_series.iloc[-1]) or None
    sma200_value = _number(sma200_series.iloc[-1])
    sma200 = sma200_value if sma200_value > 0 else None
    price = _number(close.iloc[-1])

    swing_highs, swing_lows = _swing_points(data)
    last_high = swing_highs[-1][1] if swing_highs else None
    last_low = swing_lows[-1][1] if swing_lows else None

    # Classical support/resistance prefers completed pivots; fall back to a 20-bar range.
    prior = data.iloc[-21:-1]
    support = last_low or (_number(prior["Low"].min()) or None)
    resistance = last_high or (_number(prior["High"].max()) or None)

    vol20 = _number(volume.iloc[-21:-1].mean()) if len(volume) >= 21 else 0.0
    current_volume = _number(volume.iloc[-1])
    volume_ratio = current_volume / vol20 if vol20 > 0 else None

    breakout = bool(resistance and price > resistance * 1.001 and (volume_ratio or 0) >= 1.15)
    breakdown = bool(support and price < support * 0.999 and (volume_ratio or 0) >= 1.15)

    previous_close = _number(close.iloc[-2]) if len(close) >= 2 else price
    breakout_retest = bool(
        resistance
        and previous_close > resistance
        and _number(data["Low"].iloc[-1]) <= resistance * 1.003
        and price >= resistance
    )
    breakdown_retest = bool(
        support
        and previous_close < support
        and _number(data["High"].iloc[-1]) >= support * 0.997
        and price <= support
    )

    dow = "NEUTRAL"
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        if swing_highs[-1][1] > swing_highs[-2][1] and swing_lows[-1][1] > swing_lows[-2][1]:
            dow = "BULLISH"
        elif swing_highs[-1][1] < swing_highs[-2][1] and swing_lows[-1][1] < swing_lows[-2][1]:
            dow = "BEARISH"

    ma = "NEUTRAL"
    if sma20 and sma50:
        if sma200 and price > sma20 > sma50 > sma200:
            ma = "BULLISH"
        elif sma200 and price < sma20 < sma50 < sma200:
            ma = "BEARISH"
        elif price > sma20 > sma50:
            ma = "BULLISH"
        elif price < sma20 < sma50:
            ma = "BEARISH"

    trendline = _trendline_bias(price, swing_highs, swing_lows, len(data) - 1)
    pattern = _double_pattern(swing_highs, swing_lows)
    candle = _candle_signal(data)

    score = 0
    reasons: list[str] = []
    if dow == "BULLISH":
        score += 3
        reasons.append("قمم وقيعان صاعدة وفق منطق داو")
    elif dow == "BEARISH":
        score -= 3
        reasons.append("قمم وقيعان هابطة وفق منطق داو")

    if ma == "BULLISH":
        score += 1
        reasons.append("ترتيب المتوسطات البسيطة يدعم الاتجاه الصاعد")
    elif ma == "BEARISH":
        score -= 1
        reasons.append("ترتيب المتوسطات البسيطة يدعم الاتجاه الهابط")

    if trendline == "BULLISH":
        score += 1
        reasons.append("خط الاتجاه الصاعد من القيعان ما زال محافظًا على بنيته")
    elif trendline == "BEARISH":
        score -= 1
        reasons.append("خط الاتجاه الهابط من القمم ما زال محافظًا على بنيته")

    if breakout:
        score += 2
        reasons.append("اختراق مقاومة مكتملة مع تأكيد الحجم")
    elif breakdown:
        score -= 2
        reasons.append("كسر دعم مكتمل مع تأكيد الحجم")
    elif breakout_retest:
        score += 2
        reasons.append("إعادة اختبار ناجحة لمقاومة مخترقة وتحولها إلى دعم")
    elif breakdown_retest:
        score -= 2
        reasons.append("إعادة اختبار ناجحة لدعم مكسور وتحوله إلى مقاومة")

    if pattern == "DOUBLE_BOTTOM":
        score += 1
        reasons.append("قاع مزدوج كلاسيكي محتمل عند منطقة دعم متقاربة")
    elif pattern == "DOUBLE_TOP":
        score -= 1
        reasons.append("قمة مزدوجة كلاسيكية محتملة عند منطقة مقاومة متقاربة")

    if candle in {"BULLISH_ENGULFING", "HAMMER"}:
        score += 1
        reasons.append("شمعة انعكاسية كلاسيكية تميل للصعود")
    elif candle in {"BEARISH_ENGULFING", "SHOOTING_STAR"}:
        score -= 1
        reasons.append("شمعة انعكاسية كلاسيكية تميل للهبوط")

    if volume_ratio is not None and volume_ratio >= 1.5:
        if score > 0:
            score += 1
            reasons.append("الحجم أعلى بوضوح من متوسطه ويؤكد القوة الشرائية")
        elif score < 0:
            score -= 1
            reasons.append("الحجم أعلى بوضوح من متوسطه ويؤكد الضغط البيعي")

    direction = "BULLISH" if score >= 3 else "BEARISH" if score <= -3 else "NEUTRAL"
    return TimeframeView(
        timeframe=timeframe,
        score=score,
        direction=direction,
        close=price,
        sma20=sma20,
        sma50=sma50,
        sma200=sma200,
        support=support,
        resistance=resistance,
        last_swing_low=last_low,
        last_swing_high=last_high,
        volume_ratio=volume_ratio,
        breakout=breakout,
        breakdown=breakdown,
        breakout_retest=breakout_retest,
        breakdown_retest=breakdown_retest,
        trendline_bias=trendline,
        pattern=pattern,
        candle=candle,
        reasons_ar=tuple(reasons),
    )


def build_direction(
    symbol: str,
    daily_frame: pd.DataFrame,
    hourly_frame: pd.DataFrame,
    intraday_frame: pd.DataFrame,
) -> ClassicalDirection:
    daily = analyze_timeframe(daily_frame, "1D")
    hourly = analyze_timeframe(hourly_frame, "1H")
    intraday = analyze_timeframe(intraday_frame, "15m")

    sign = {"BULLISH": 1, "NEUTRAL": 0, "BEARISH": -1}
    agreement = sign[daily.direction] * 3 + sign[hourly.direction] * 2 + sign[intraday.direction]

    decision = "WAIT"
    if (
        daily.direction == "BULLISH"
        and daily.score >= 3
        and hourly.direction != "BEARISH"
        and intraday.direction == "BULLISH"
        and agreement >= 4
    ):
        decision = "CALL"
    elif (
        daily.direction == "BEARISH"
        and daily.score <= -3
        and hourly.direction != "BULLISH"
        and intraday.direction == "BEARISH"
        and agreement <= -4
    ):
        decision = "PUT"

    if abs(agreement) >= 6 and abs(daily.score) >= 5:
        priority = "HIGH"
    elif abs(agreement) >= 4:
        priority = "MEDIUM"
    else:
        priority = "WAIT"

    confirmation: float | None = None
    invalidation: float | None = None
    reasons: list[str] = []
    if decision == "CALL":
        confirmation = intraday.resistance or hourly.resistance
        invalidation = intraday.last_swing_low or intraday.support or hourly.last_swing_low
        reasons.append("اليومي صاعد والساعة لا تعارضه و15 دقيقة تؤكد اتجاه CALL")
    elif decision == "PUT":
        confirmation = intraday.support or hourly.support
        invalidation = intraday.last_swing_high or intraday.resistance or hourly.last_swing_high
        reasons.append("اليومي هابط والساعة لا تعارضه و15 دقيقة تؤكد اتجاه PUT")
    else:
        reasons.append("القراءة الكلاسيكية غير متفقة بما يكفي لإصدار CALL أو PUT")

    # Lead with the higher-timeframe evidence; intraday is only the trigger layer.
    for view in (daily, hourly, intraday):
        reasons.extend(view.reasons_ar[:3])

    return ClassicalDirection(
        symbol=str(symbol).upper(),
        decision=decision,
        priority=priority,
        agreement_score=agreement,
        horizon="1-5 جلسات تداول",
        price=intraday.close,
        confirmation_level=confirmation,
        invalidation_level=invalidation,
        daily=daily,
        hourly=hourly,
        intraday=intraday,
        reasons_ar=tuple(dict.fromkeys(reasons)),
        limitations_ar=(
            "التوجه مشتق من السهم نفسه فقط؛ لا تدخل بيانات سلسلة الأوبشن أو اليونانيات أو تدفق العقود في القرار.",
            "CALL/PUT هنا اتجاه للسهم وليس اختيارًا لسترايك أو تاريخ انتهاء محدد.",
            "المنهج كلاسيكي: اتجاه داو، دعم/مقاومة، خط اتجاه، متوسطات بسيطة، حجم، اختراق/إعادة اختبار، نماذج وشموع كلاسيكية.",
            "إذا اختلفت الأطر الزمنية فالنتيجة WAIT ولا يرسل البوت تنبيه اتجاه.",
        ),
    )
