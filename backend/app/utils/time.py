"""Shared datetime helpers — single source of truth for API timestamp output.

Root cause of the frontend "wrong time" bug:
- DB columns use ``server_default=func.now()`` which stores *naive* datetimes
  (SQLite ``CURRENT_TIMESTAMP`` = UTC wall-clock, no tzinfo).
- API handlers serialized them with ``dt.isoformat()`` → e.g.
  ``"2026-09-03T20:18:30"`` with NO offset.
- JS ``new Date("2026-09-03T20:18:30")`` parses offset-less strings as
  **browser-local time**. In an IST browser the UTC instant 20:18Z was
  rendered as 20:18 IST instead of the correct 01:48 IST (+5:30) — 5.5h behind.

Fix: every API timestamp goes through :func:`utc_iso`, which treats naive
datetimes as UTC (matching what the DB stores) and always emits an
offset-aware ISO-8601 string (``+00:00``). The frontend then converts to
``Asia/Kolkata`` explicitly via ``timeZone`` instead of relying on the
browser default.
"""
from datetime import datetime, timezone
from typing import Optional


def utc_iso(dt: Optional[datetime]) -> Optional[str]:
    """Serialize a datetime as offset-aware UTC ISO-8601.

    Naive datetimes are assumed to already be UTC (DB ``func.now()``).
    Aware datetimes are converted to UTC.
    Returns ``None`` for ``None`` input.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()
