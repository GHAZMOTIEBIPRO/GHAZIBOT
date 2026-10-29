---
name: ghazi-options-evidence
description: Review GHAZI RADAR option-chain evidence before any contract is scored, shown or alerted - OCC contract identity and adjusted/non-standard contracts, quote validity (two-sided, crossed, zero bid), spread width and liquidity, quote vs last-trade vs snapshot time, open-interest timing (OI is end-of-day, not live), Vol/OI as context only, and what the data cannot prove (buyer/seller initiation, sweeps, dealer positioning, trader identity, direction of a trade). Use this whenever the task touches options chains, v11_gate.py, data_fabric.py, GEX/gamma, unusual activity, contract scores, OCC symbols, Tradier/Alpaca/MarketData options data, or a claim like "smart money bought calls".
---

# GHAZI options evidence

A chain shows quotes, prices of trades that happened, and yesterday's open interest. It does not show who traded, which side started a trade, or where dealers stand. Most wrong options claims come from reading those three in. This skill keeps every claim at the level the data supports.

## What each field can and cannot prove

| Field | Proves | Does not prove |
|---|---|---|
| Bid/ask with an absolute quote time | The market at that time | That a fill was possible at that size |
| Last trade price and time | A trade happened | Its side (buyer or seller initiated) |
| Volume (day) | Contracts changed hands | Opening vs closing, direction, who traded |
| Open interest | End-of-previous-day open contracts | Today's flow (OI updates once a day) |
| Vol / OI | Activity relative to yesterday's OI | Institutional intent, a sweep, new positions |
| Model Greeks / GEX | A model under stated assumptions | Actual dealer positioning |

## Workflow

1. **Contract identity.**
   - Parse the OCC symbol (root, expiry, C/P, strike × 1000).
   - Reject adjusted or non-standard deliverables (root with a digit, multiplier ≠ 100). This follows the existing `v11_gate` policy.
2. **Quote validity.**
   - The quote must be two-sided, with `bid > 0` and `ask ≥ bid`.
   - It must carry an absolute quote time from the provider. A local `now()` is not a quote time.
   - Quote age is computed from that time.
   - Crossed or locked quotes are `INVALID_QUOTE`.
3. **Liquidity.**
   - Spread % = (ask − bid) / mid.
   - Wide spreads cap what can be said ("the mid is not a fill estimate").
   - Report OI with its as-of date.
4. **Evidence level.**
   - Delayed, sandbox or indicative data is `RESEARCH` or `CONTEXT` only.
   - Execution-grade requires structured live or licensed evidence that passes `v11_gate`. The strings "live" or "OPRA" in a label are not evidence.
5. **Independence.**
   - Option scores never change the underlying CALL / PUT / WAIT decision (AGENTS.md).
   - Discovery may seed a symbol, never a score.

## Wording rules

- **Allowed:** "Volume 3,200 contracts vs OI 900 (OI as of yesterday's close): unusual activity relative to OI; direction and side unknown."
- **Not allowed:** "Buying sweep", "a large trader is bullish", "dealers are short gamma at 200". Each needs data the chain doesn't have: prints with exchange and side, account identity, or dealer books.

## Acceptance criteria

- Every quote shown has its provider timestamp and age, and its feed class (live / delayed / indicative).
- OI always carries its date.
- No direction, side or identity is claimed from chain data.
- A failed or empty chain marks the options section `UNAVAILABLE`. It does not hide or change the stock reading.

## Examples

**Pass:** "AAPL 2026-11-20 230C:
- bid 2.10 / ask 2.35 (quote 14:31:05 NY, delayed 15 min);
- spread 11%;
- OI 4,812 (27 Oct close);
- volume today 6,950.

Research context only."

**Fail:**
- "Unusual call buying in AAPL: bullish institutions." The data doesn't show side or identity.
- A contract scored from a quote that has no timestamp.
- A GEX "flip level" shown as support.

## Where things live

| Code | Role |
|---|---|
| `options_radar/v11_gate.py` | Production/execution gate. Do not weaken it to raise alert count. |
| `options_radar/data_fabric.py` | Provider reconciliation and source-family independence |
| `options_radar/ghazi_gex_multi.py`, `options_radar/occ_free_data.py` | OCC symbol parsing (existing parsers; do not add another) |
| `options_radar/source_permissions.py` | Gates (Cboe and Yahoo stay off) |
