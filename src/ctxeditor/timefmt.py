"""UTC storage and viewer-local display of timestamps."""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_STORE = "%Y-%m-%dT%H:%M:%S.%fZ"


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime(_STORE)


def parse_utc(iso: str) -> datetime:
    return datetime.strptime(iso, _STORE).replace(tzinfo=UTC)


def valid_zone(tz_name: str | None) -> str | None:
    """The IANA name if it is a real zone, else None (callers fall back to UTC)."""
    if not tz_name:
        return None
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None
    return tz_name


def format_local(iso_utc: str | None, tz_name: str | None) -> str:
    """e.g. "Oct 19, 2026, 4:05 PM" in the viewer's timezone (UTC when the zone is unknown)."""
    if not iso_utc:
        return "-"
    zone = ZoneInfo(valid_zone(tz_name) or "UTC")
    local = parse_utc(iso_utc).astimezone(zone)
    hour = local.hour % 12 or 12
    return f"{local:%b} {local.day}, {local.year}, {hour}:{local:%M} {'AM' if local.hour < 12 else 'PM'}"
