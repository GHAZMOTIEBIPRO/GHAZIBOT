# BLACK BOX Omega — Free Autonomy Mode

This repository's default operating policy is **zero-cost and no-touch**.

## Invariants

1. `FREE_AUTONOMY_MODE` defaults to enabled.
2. No trading alert path may require a paid market-data subscription to remain operational.
3. Alpaca equity streaming is forced to the free `IEX` feed while free autonomy is enabled.
4. Alpaca options streaming is forced to the free `indicative` feed while free autonomy is enabled.
5. Indicative/delayed/unofficial option data remains context/research grade. It must never be relabelled as OPRA, NBBO, confirmed sweep, buyer-initiated flow, or execution-grade evidence.
6. Existing strict provider-readiness and hard-blocker rules remain authoritative. Free mode may produce zero option alerts when data quality is insufficient; safety is preferred over inventing confidence.
7. Provider failures use automatic fallback/circuit-breaker behavior. A single provider outage must not require operator intervention when another permitted source is usable.
8. Radar-health monitoring is transition-based. It notifies on meaningful degradation/recovery, not every scheduled cycle.
9. Health checks inspect the latest completed radar run and payload freshness so an older successful artifact cannot hide a newer failure.
10. Closed markets are quiet. No stale Friday/weekend payload may be promoted into a current alert.

## Hosting policy

GitHub Actions is used for repository automation, scheduled scans, validation, state persistence, and Telegram delivery. Free Autonomy Mode does **not** try to turn GitHub-hosted runners into a permanent 24/7 application server.

The stream gateway remains available for bounded or suitable-host execution, but the autonomous free production path does not require a persistent WebSocket host. This keeps the repository operational without asking the user to create or maintain another hosting account.

## User experience

The user is not expected to:

- keep a laptop or phone application running;
- manually start a scan each day;
- approve individual provider failovers;
- inspect GitHub to learn whether a missing Telegram alert means "no opportunity" or "system failure";
- buy OPRA/SIP or another paid feed for the bot to continue operating.

A qualified opportunity is delivered automatically. A meaningful system degradation is reported automatically. Normal no-signal periods remain silent.

## Future upgrades

A paid feed or persistent commercial host may only be introduced as a separate, explicit opt-in architecture. It must never silently replace or become a requirement of Free Autonomy Mode.
