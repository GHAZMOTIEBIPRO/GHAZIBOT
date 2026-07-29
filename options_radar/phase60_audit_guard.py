from __future__ import annotations

import atexit

from . import phase60_sources

_ORIGINAL_WRITE_AUDIT = phase60_sources._write_audit
_INSTALLED = False


def _has_audit_records() -> bool:
    with phase60_sources._AUDIT_LOCK:
        return any(
            isinstance(phase60_sources._SOURCE_AUDIT.get(section), dict)
            and bool(phase60_sources._SOURCE_AUDIT[section])
            for section in ("stocks", "options")
        )


def _guarded_write_audit() -> None:
    """Do not let helper-only processes erase the scanner's persisted audit.

    Importing the package registers an atexit writer. Scripts such as
    ``apply_phase62.py`` do not fetch market data, so their in-memory audit is
    empty. Without this guard, those scripts overwrite the non-empty audit
    written by the scanner a few seconds earlier.
    """

    if not _has_audit_records():
        return
    _ORIGINAL_WRITE_AUDIT()


def install_source_audit_guard() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    atexit.unregister(_ORIGINAL_WRITE_AUDIT)
    phase60_sources._write_audit = _guarded_write_audit
    atexit.register(_guarded_write_audit)
    _INSTALLED = True
