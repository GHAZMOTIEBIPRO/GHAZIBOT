# Open-source selection, 2026-10-29

Each candidate below was checked against the AGENTS.md open-source policy:
- licence, read from PyPI metadata (GitHub reports NOASSERTION for some);
- activity;
- dependencies;
- whether it fills a real gap in this change.

No code is copied. Each candidate is either used as a library or not taken.

| Project | Licence | Activity | Decision | Why |
|---|---|---|---|---|
| [tiran/defusedxml](https://github.com/tiran/defusedxml) 0.7.1 | PSF-2.0 (PyPI classifier; GitHub reports NOASSERTION) | 559 stars; last push 2024-09; stable API | **Integrated** as a library in `scripts/build_ir_news.py` | See "defusedxml" below. |
| [kurtmckee/feedparser](https://github.com/kurtmckee/feedparser) 6.0.x | BSD-2-Clause | 2,451 stars; updated 2026-10-27 | **Not used for IR news** (it is already a dependency of `options_radar/free_public_intelligence.py`) | See "feedparser" below. |
| [gerrymanoim/exchange_calendars](https://github.com/gerrymanoim/exchange_calendars) | Apache-2.0 | active | Already integrated (week agenda, daily plan) | XNYS holidays and early closes come from it, not from our own lists. |
| [yipjunkai/pyvolr](https://github.com/yipjunkai/pyvolr) | — | 5 stars, created 2026-05 | **Not taken** | Too young. Option Greeks already have a test-only MIT oracle (`blackscholes`). |
| USAspending, FINRA client libraries | — | — | **Not taken** | The official APIs are a few documented POST calls. A wrapper adds a dependency with no data or rights benefit. |

## defusedxml

**Why we integrated it:**
- Company IR feeds come from 10 external hosts and are untrusted XML.
- The stdlib parser processes entity declarations and DTDs. defusedxml refuses them: entity expansion ("billion laughs"), external entities, DTD retrieval.

**What changes:**
- A refused feed gets status `XML_REFUSED_UNSAFE` and is handled like any other failed source: its last good items are kept and no new success time is recorded.
- The same change fixes `NOT_XML`, which used to record a success time and drop the source's items.

## feedparser

**Why it is not used for IR news:**
- It normalises every date to a UTC `struct_time`, so it cannot tell whether the feed gave a time zone. The project rule is that a time without a zone is not an absolute time, and is dropped, never assumed to be UTC.
- All 10 reviewed feeds parse strictly today (probe runs 40770962704 and 40793143955), so its lenient parsing fixes no observed failure.

**Revisit if:** a reviewed feed ever fails `NOT_XML`. Then use feedparser for structure only, keep the raw date string, and run it through our own `parse_time`.

## Data-quality and calculation libraries (2026-10-29, second pass)

| Project | Licence (from its repo) | Decision | Why |
|---|---|---|---|
| [unionai-oss/pandera](https://github.com/unionai-oss/pandera) 0.26.1 | MIT | Already a dev dependency. Its rules are **extended**, not added again. | See "pandera" below. |
| [pandas-ta-classic](https://pypi.org/project/pandas-ta-classic/) 0.8.32 | MIT | Already the reference in tests. **Kept as the indicator reference.** | See "Indicator parity" below. |
| [TA-Lib/ta-lib-python](https://github.com/TA-Lib/ta-lib-python) @0598313 | BSD-2-Clause | **Not added.** | It needs the TA-Lib C library built on every runner. pandas-ta-classic already gives an exact reference for the indicators we publish. A second reference would check nothing new. |
| [kernc/backtesting.py](https://github.com/kernc/backtesting.py) @ca2e261 | **AGPL-3.0** | **Not integrated** (AGENTS.md: GPL/AGPL code needs explicit licence review before entering core). | See "backtesting.py" below. |
| [microsoft/playwright](https://github.com/microsoft/playwright) | Apache-2.0 | Already used (`scripts/ux_tasks.cjs`, `scripts/site_smoke.cjs`), with the pre-installed Chromium. | — |

### pandera
`options_radar/ohlcv_quality.py` defines each OHLCV rule once as a function, and the pandera schema runs those functions as named checks. The rules:
- positive and finite prices;
- high ≥ open/close/low, and low ≤ open/close/high;
- volume ≥ 0.

Outside pandera, the module also checks:
- timestamps that are aware and parseable;
- order and duplicates;
- completed vs forming bars;
- split suspects on unadjusted data;
- whether the history is long enough.

The private workflows install only `requirements.txt`. There the same functions run without pandera and give the same codes. `test_pandera_and_plain_python_give_the_same_codes` checks this.

### Indicator parity
`tests/test_ohlcv_quality.py` compares the engine against the reference:
- **EMA:** identical to `ta.ema(sma=False)`, which uses the same seeding. Against the library's default SMA seed, the difference is under 1e-3 after a 100-bar warm-up.
- **ATR14 (Wilder / RMA):** identical to `ta.atr(mamode="rma")`.

### backtesting.py
- The existing walk-forward evaluation (`scripts/run_stock_walk_forward.py`, explosion stage evaluation) already does out-of-sample, time-ordered tests.
- A second engine would duplicate it.
- A stock-strategy backtest also could not show that option contracts are profitable.

