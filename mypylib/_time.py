from __future__ import annotations

import time
from datetime import datetime, timedelta


def _plural(n: int, word: str) -> str:
    """Return ``"{n} {word}"`` or ``"{n} {word}s"`` depending on *n*."""
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def get_timestamp() -> int:
    """Return the current UNIX timestamp as an integer.

    :return: Seconds since epoch.
    """
    return int(time.time())


def timestamp2datetime(timestamp: int, format: str = "%d.%m.%Y %H:%M:%S") -> str:
    """Convert a UNIX timestamp to a formatted local-time string.

    :param timestamp: Seconds since epoch.
    :param format: :func:`time.strftime` format string.
    :return: Formatted datetime string.
    """
    return time.strftime(format, time.localtime(timestamp))


def timeago(timestamp: int | datetime | None = None) -> str:
    """Return a human-readable "time ago" string.

    :param timestamp: UNIX timestamp, :class:`~datetime.datetime`,
        or ``None`` for zero diff.
    :return: Relative time string (e.g. ``"3 minutes ago"``).
    """
    now = datetime.now()
    if isinstance(timestamp, datetime):
        diff = now - timestamp
    elif isinstance(timestamp, int) and not isinstance(timestamp, bool):
        diff = now - datetime.fromtimestamp(timestamp)
    else:
        diff = timedelta(0)

    second_diff = diff.seconds
    day_diff = diff.days

    if day_diff < 0:
        return ""

    if day_diff == 0:
        if second_diff < 10:
            return "just now"
        if second_diff < 60:
            return f"{_plural(second_diff, 'second')} ago"
        if second_diff < 120:
            return "a minute ago"
        if second_diff < 3600:
            return f"{_plural(second_diff // 60, 'minute')} ago"
        if second_diff < 7200:
            return "an hour ago"
        if second_diff < 86400:
            return f"{_plural(second_diff // 3600, 'hour')} ago"
    if day_diff < 31:
        return f"{_plural(day_diff, 'day')} ago"
    if day_diff < 365:
        return f"{_plural(day_diff // 30, 'month')} ago"
    return f"{_plural(day_diff // 365, 'year')} ago"


def time2human(diff: int | float) -> str:
    """Convert a duration in seconds to a human-readable string.

    :param diff: Duration in seconds.
    :return: String like ``"5 minutes"`` or ``"3 days"``.
    """
    dt = timedelta(seconds=diff)
    if dt.days < 0:
        return ""

    if dt.days == 0:
        if dt.seconds < 60:
            return _plural(dt.seconds, "second")
        if dt.seconds < 3600:
            return _plural(dt.seconds // 60, "minute")
        if dt.seconds < 86400:
            return _plural(dt.seconds // 3600, "hour")
    return _plural(dt.days, "day")
