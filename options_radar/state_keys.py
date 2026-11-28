"""Keyed tags: the only form in which owner-private events may leave a trace on the public bot-state branch.

bot-state is a public branch. Restricted data (Alpaca prices, levels, detections, outcomes) and anything
derived from it never goes there, encrypted or not: encryption is not a storage licence (owner, PHASE 4).
What may go there:
  * operational records: statuses, message counts, attempt numbers, times;
  * keyed tags: HMAC-SHA256 under ``GHAZI_STATE_HMAC_KEY``, an independent secret used for nothing else.

A tag answers one question for a holder of the key ("was this exact event already sent?") and nothing for
anyone else; the preimage (symbol, stage, minute) is recomputed from source data at run time, never stored.
There is no fallback to any other secret (the Telegram token is a transport credential, not a key). Without
the key, every caller disables its dedupe state and fails safe: no repeated alerts, no stored tags.
"""
from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterable, Mapping

ENV = "GHAZI_STATE_HMAC_KEY"
MIN_LEN = 32
SEP = "\x1f"


def state_key(env: Mapping[str, str]) -> bytes | None:
    """The independent state key, or None when absent or too short to be a real secret."""
    raw = (env.get(ENV) or "").strip()
    return raw.encode() if len(raw) >= MIN_LEN else None


def tag(key: bytes, *parts: object) -> str:
    """A 96-bit keyed tag for one event; parts are joined with a unit separator (no ambiguity)."""
    return hmac.new(key, SEP.join(str(p) for p in parts).encode(), hashlib.sha256).hexdigest()[:24]


def recover(key: bytes, tags: Iterable[str], prefix: tuple, candidates: Iterable[tuple]) -> list[tuple]:
    """The candidates whose tag (prefix + candidate) is among `tags`: how a key holder reads its own state."""
    wanted = set(tags)
    if not wanted:
        return []
    base = hmac.new(key, (SEP.join(str(p) for p in prefix) + SEP).encode(), hashlib.sha256)
    found = []
    for c in candidates:
        h = base.copy()
        h.update(SEP.join(str(p) for p in c).encode())
        if h.hexdigest()[:24] in wanted:
            found.append(c)
    return found
