# Classical Telegram signal freshness

The alert sender uses `intraday_bar_closed_at`, computed from the last provider-derived completed 15-minute OHLC bar (start + 15m), rather than the current process clock or payload `generated_at`.

The sender fails closed for missing/naive/future timestamps, bars outside today's NYSE regular session, bars older than 45 minutes, market holidays, closed hours, broken invalidation, conflicting timeframes, and price-vs-15m-close mismatch. It shows the data provider and the completed bar time in every published message. This is a **delayed-bar research alert**, not a real-time quote, fill, or price guarantee. It does not bypass V11 option gates.

Pull-request/push validation never sends Telegram. Manual dispatch may scan outside market hours, but must not send until the U.S. regular exchange session is open. A dry-run on PR is not proof that live Telegram credentials are configured or messages delivered.
