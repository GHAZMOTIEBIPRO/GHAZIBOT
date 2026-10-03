---
applyTo: "options_radar/**/*.py,scripts/*options*.py,tests/test_*option*.py"
---

# Options / Market-Data Instructions

- Preserve V11 and all stricter execution gates.
- Never manufacture quote freshness or convert last-trade time into quote time.
- Preserve bid/ask pairing from one provider; do not manufacture synthetic NBBO unless a future explicit design and tests authorize it.
- Treat Yahoo/yfinance/yahooquery as one independent source family.
- Delayed, sandbox, indicative, and unofficial data may remain RESEARCH/WATCH/CONTEXT, never execution-ready solely because other descriptive labels sound live.
- An execution-ready contract needs structured provider identity, valid bid/ask, absolute verifiable quote timestamp, acceptable quote age, and explicit live/licensed authority.
- Stream overlay authority requires explicit execution metadata such as `stream_execution_grade`; descriptive text is not enough.
- Vol/OI, quote proximity, premium, or relative activity do not prove institutional buying or sweeps.
- Last-trade age is a liquidity/context feature, not a substitute for quote age.
- Preserve DTE/horizon logic and avoid default 0DTE behavior.
- If one provider/symbol fails, isolate it when safe and record provider, symbol, operation, exception type, and health/audit impact.
- Add regression tests for any change to freshness, source independence, contract identity, flow authority, or execution confidence.
