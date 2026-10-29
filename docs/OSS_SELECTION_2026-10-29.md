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

## Infrastructure, calendars, options and charts (2026-10-29, third pass)

Each project was checked against what the repository already has. Versions and licences come from PyPI; the JS library version is the one already pinned in `public/classic.html`.

| Project | Licence | Decision | Evidence / reason |
|---|---|---|---|
| [requests-cache](https://github.com/requests-cache/requests-cache) 1.3.3 | BSD-2-Clause | **Not added.** | `options_radar/http_fetch.py` (PR #402) already sends conditional GETs with the stored `Last-Modified`. The 13 MB DOL file answered 304 in run 40856203424. Each builder keeps its own freshness limit: claims 20 days, rates 6, MMF 75. A disk cache would also need to persist between fresh runners. It would add a second freshness mechanism to keep honest, not new data. |
| [tenacity](https://github.com/jd/tenacity) 9.2.1 | Apache-2.0 | **Not added.** | `http_fetch.fetch` already gives bounded retries with backoff, a capped single Retry-After for 429, and no retry on 401/403/451. All of this is tested in `tests/test_http_fetch.py`. |
| [duckdb](https://github.com/duckdb/duckdb) 2.0.0 | MIT | **Not added (measured).** | bot-state holds 29.4 MB in 401 JSON files; the largest is 6.8 MB (`contract_guardian_state.json`). No candle history exists, because no lawful price source is configured. Revisit when Alpaca intraday bars accumulate: then a DuckDB file in a durable store (bot-state LFS or an artifact), never a runner temp disk. |
| [pandas_market_calendars](https://github.com/rsheftel/pandas_market_calendars) 5.5.0 | MIT | **Not added.** | `exchange_calendars` (the library it builds on) is already used: daily plan XNYS sessions, early closes, holidays and DST. |
| [quantstats](https://github.com/ranaroussi/quantstats) 0.0.86 | Apache-2.0 | **Already used** (`scripts/run_quantstats_stock_shadow.py`, research requirements). | Stock-only reports, never presented as option performance. |
| [py_vollib](https://github.com/vollib/py_vollib) 1.0.12 | MIT | **Already used** (`scripts/validate_open_source_greeks.py`). | Black-Scholes is European; US equity options are American, so these Greeks are model checks only. Not wired to live contracts: no qualifying chain inputs are configured. |
| [TA-Lib](https://github.com/TA-Lib/ta-lib-python) | BSD-2-Clause | Unchanged. | Optional shadow comparison only (`options_radar/ta_lib_shadow.py`); pandas-ta-classic stays the reference. |
| [apache/echarts](https://github.com/apache/echarts) | Apache-2.0 | **Not added; lightweight-charts reused instead.** | `lightweight-charts@5.2.1` (Apache-2.0) is already pinned in `public/classic.html`, so the liquidity charts reuse it. It is loaded on demand from jsDelivr with a values-table fallback. A second chart library would duplicate it, and only time-series lines are needed. |
| [microsoft/playwright](https://github.com/microsoft/playwright) | Apache-2.0 | Extended. | A new UX task checks, on phone and desktop, that the liquidity reading is present, both charts draw (canvas), the observation and publication captions show, and the NY Fed notice appears. |

### Skills
- [obra/superpowers](https://github.com/obra/superpowers) @2ce8aa1 (MIT): seven skills vendored into `.claude/skills/`.
  - The skills: `writing-plans`, `executing-plans`, `subagent-driven-development` (its scripts are needed by `executing-plans`), `requesting-code-review`, `receiving-code-review`, `verification-before-completion`, `systematic-debugging`.
  - The plugin's SessionStart hook (forced brainstorming before any work) is **not** installed, so settled questions are not reopened.
  - The scripts were reviewed first: no network calls, no pushes.

### Discovery outside GitHub
- `scripts/probe_macro_sources.py discover` runs on the runner. It checks:
  - Hugging Face model cards for FinBERT: the weights licence, not the code's;
  - data.gov catalog searches: publisher and licence as stated.
- No model is adopted from that listing alone.

