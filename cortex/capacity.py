"""
Account capacity reporting.

The previous implementation had a dangerous default: when a profile had no
``cachedUsageUtilization`` entry it reported "Ready (100% capacity free)" and
scored it as the best candidate. Missing data is not free capacity - a brand new
or long-idle profile has no cache, and an account that is actually rate-limited
looks identical to one that is wide open. ``cc continue`` would then fail over
*to* an exhausted account.

Here, unknown is reported as unknown, and an unknown profile is never chosen
automatically. Selection prefers profiles with evidence of free capacity; if
none exist, the caller is told to choose explicitly.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from . import jsonfile, profiles
from .paths import profile_dir

KNOWN_FREE = "free"
KNOWN_LIMITED = "limited"
UNKNOWN = "unknown"
UNAUTHENTICATED = "unauthenticated"


def _parse_reset(value):
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, OSError, OverflowError):
        return None


def _humanize(delta_seconds):
    if delta_seconds is None:
        return ""
    if delta_seconds <= 0:
        return "now"
    hours, rem = divmod(int(delta_seconds), 3600)
    minutes = rem // 60
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def inspect(name: str, check_auth=True):
    """Return a capacity record for one profile."""
    target = profile_dir(name)
    record = {
        "name": name,
        "email": profiles.profile_email(name),
        "mode": profiles.profile_mode(name),
        "state": UNKNOWN,
        "utilization": None,
        "resets_in": None,
        "detail": "",
    }

    if check_auth and not profiles.is_authenticated(name):
        record["state"] = UNAUTHENTICATED
        record["detail"] = f"not signed in (run: cc login {name})"
        return record

    cfg = jsonfile.read(f"{target}/.claude.json", {})
    usage = cfg.get("cachedUsageUtilization")

    if not isinstance(usage, dict) or not usage:
        # No cache is not evidence of free capacity. Say so.
        record["state"] = UNKNOWN
        record["detail"] = "no usage data recorded yet"
        return record

    pct = None
    for key in ("fiveHourUtilization", "five_hour_utilization",
                "sevenDayUtilization", "seven_day_utilization", "utilization"):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            pct = max(pct or 0, float(value))
    if pct is not None and pct <= 1.0:
        pct *= 100.0

    reset = _parse_reset(usage.get("resetsAt") or usage.get("resets_at"))
    if reset:
        record["resets_in"] = (reset - datetime.now(timezone.utc)).total_seconds()

    record["utilization"] = pct
    if pct is None:
        record["state"] = UNKNOWN
        record["detail"] = "usage data present but unreadable"
    elif pct >= 99:
        record["state"] = KNOWN_LIMITED
        record["detail"] = f"limit reached, resets in {_humanize(record['resets_in'])}"
    else:
        record["state"] = KNOWN_FREE
        record["detail"] = f"{100 - pct:.0f}% capacity remaining"
    return record


def survey(check_auth=True):
    return [inspect(n, check_auth=check_auth) for n in profiles.list_profiles()]


def best(records=None):
    """Pick a profile with evidence of free capacity, or None.

    Never returns a profile whose capacity is unknown: silently switching to an
    account that might be exhausted is worse than asking.
    """
    records = records if records is not None else survey()
    free = [r for r in records if r["state"] == KNOWN_FREE]
    if not free:
        return None
    free.sort(key=lambda r: r["utilization"] if r["utilization"] is not None else 100)
    return free[0]["name"]


BADGE = {
    KNOWN_FREE: "available",
    KNOWN_LIMITED: "LIMITED",
    UNKNOWN: "unknown",
    UNAUTHENTICATED: "signed out",
}


def render(records=None):
    records = records if records is not None else survey()
    active = profiles.active_profile()

    lines = ["=" * 74,
             "  Claude Cortex - account capacity",
             "=" * 74,
             f"  {'PROFILE':<12}{'EMAIL':<30}{'STATE':<12}DETAIL",
             f"  {'-'*11:<12}{'-'*29:<30}{'-'*11:<12}{'-'*20}"]

    for r in records:
        marker = " *" if r["name"] == active else "  "
        email = (r["email"] or "-")[:28]
        lines.append(f"{marker}{r['name']:<12}{email:<30}"
                     f"{BADGE[r['state']]:<12}{r['detail']}")

    if not records:
        lines.append("  (no profiles configured - run: cc profile add)")

    lines.append("")
    unknown = sum(1 for r in records if r["state"] == UNKNOWN)
    if unknown:
        lines.append(f"  Note: {unknown} profile(s) have no usage data. Claude Code records")
        lines.append("  usage as you work; until then capacity cannot be reported, and")
        lines.append("  these profiles are not auto-selected by 'cc continue'.")
    lines.append("=" * 74)
    return "\n".join(lines)
