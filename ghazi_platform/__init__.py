"""GHAZI RADAR PRO — multi-user research platform (P1 alpha, feature-flagged).

A separate serving layer next to the existing static site and Telegram bot. It
does not write to `public/`, `bot-state` or any market-data state file; it only
reads the published research artifacts through the licence guard and keeps
private user data (accounts, watchlists, uploads, backtests) in its own database.

Standard library only, so it runs where the dependency-free jobs run. The
server is off unless GHAZI_PLATFORM_ENABLED=1.
"""

SCHEMA_VERSION = 1
