#!/usr/bin/env python3
"""
Claude Cortex - Multi-Account Capacity & Rate-Limit Engine
Inspects all configured profiles, determines quota/limit utilization,
calculates reset countdowns, and automatically picks the best available account.
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone

PROFILES_DIR = os.path.expanduser("~/.claude-profiles")
CURRENT_PROFILE_FILE = os.path.join(PROFILES_DIR, "current_profile")
SHARED_CLAUDE_DIR = os.path.expanduser("~/.claude")

def parse_iso_or_epoch(val):
    if not val:
        return None
    if isinstance(val, (int, float)):
        # Epoch seconds or milliseconds
        if val > 1e11:  # milliseconds
            val = val / 1000.0
        return datetime.fromtimestamp(val, tz=timezone.utc)
    if isinstance(val, str):
        try:
            # Handle ISO format
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
    return None

def format_time_remaining(diff):
    total_sec = max(0, int(diff.total_seconds()))
    days = total_sec // 86400
    hours = (total_sec % 86400) // 3600
    minutes = (total_sec % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    elif minutes > 0:
        return f"{minutes}m"
    else:
        return f"{total_sec}s"

def check_profile(prof_name):
    prof_dir = os.path.join(PROFILES_DIR, prof_name)
    creds_path = os.path.join(prof_dir, ".credentials.json")
    claude_json_path = os.path.join(prof_dir, ".claude.json")
    mode_path = os.path.join(prof_dir, ".profile_mode")

    mode = "synced"
    if os.path.exists(mode_path):
        try:
            with open(mode_path) as f:
                mode = f.read().strip()
        except Exception:
            pass

    email = ""
    is_auth = False
    sub_type = "standard"
    tier = "default"

    # Check credentials
    if os.path.exists(creds_path):
        try:
            with open(creds_path) as f:
                c = json.load(f)
            oauth = c.get("claudeAiOauth", {})
            if oauth.get("accessToken"):
                is_auth = True
                sub_type = oauth.get("subscriptionType", "standard")
                tier = oauth.get("rateLimitTier", "default")
        except Exception:
            pass

    # Check claude.json for email
    if os.path.exists(claude_json_path):
        try:
            with open(claude_json_path) as f:
                d = json.load(f)
            email = d.get("oauthAccount", {}).get("emailAddress", "")
        except Exception:
            pass

    if not email:
        email_file = os.path.join(prof_dir, ".profile_email")
        if os.path.exists(email_file):
            try:
                with open(email_file) as f:
                    email = f.read().strip()
            except Exception:
                pass

    if not email:
        email = f"[{prof_name.upper()} Profile]"

    info = {
        "name": prof_name,
        "email": email,
        "mode": mode,
        "authenticated": is_auth,
        "subscription": sub_type,
        "tier": tier,
        "available": False,
        "utilization": 0,
        "five_hour_util": 0,
        "five_hour_resets_at": None,
        "seven_day_util": 0,
        "seven_day_resets_at": None,
        "status_detail": "",
        "resets_at": None,
        "reset_seconds": None,
        "score": 999999,  # lower is better for selection
    }

    if not is_auth:
        info["status_detail"] = "Not Authenticated (claude login " + prof_name + ")"
        info["available"] = False
        info["score"] = 1000000
        return info

    if not os.path.exists(claude_json_path):
        info["available"] = True
        info["utilization"] = 0
        info["status_detail"] = "Ready (100% capacity free)"
        info["score"] = 0
        return info

    try:
        with open(claude_json_path) as f:
            d = json.load(f)
    except Exception:
        info["available"] = True
        info["utilization"] = 0
        info["status_detail"] = "Ready"
        info["score"] = 10
        return info

    u_obj = d.get("cachedUsageUtilization")
    if not u_obj or not isinstance(u_obj, dict):
        info["available"] = True
        info["utilization"] = 0
        info["status_detail"] = "Ready (No limits recorded)"
        info["score"] = 0
        return info

    u = u_obj.get("utilization")
    if not u or not isinstance(u, dict):
        info["available"] = True
        info["utilization"] = 0
        info["status_detail"] = "Ready (No limits recorded)"
        info["score"] = 0
        return info

    now = datetime.now(timezone.utc)
    max_util = 0
    blocked = False
    earliest_reset_dt = None
    block_reason = ""

    # Check 5-hour window
    fh = u.get("five_hour") or {}
    fh_util = fh.get("utilization") or 0
    fh_reset_raw = fh.get("resets_at")
    fh_reset_dt = parse_iso_or_epoch(fh_reset_raw)

    if fh_reset_dt and now >= fh_reset_dt:
        fh_util = 0  # Period expired!
    max_util = max(max_util, fh_util)

    if fh_util >= 100:
        if fh_reset_dt and now < fh_reset_dt:
            blocked = True
            diff = fh_reset_dt - now
            block_reason = f"5-hour limit reached (resets in {format_time_remaining(diff)})"
            earliest_reset_dt = fh_reset_dt
        elif not fh_reset_dt:
            blocked = True
            block_reason = "5-hour limit reached"

    # Check 7-day window
    sd = u.get("seven_day") or {}
    sd_util = sd.get("utilization") or 0
    sd_reset_raw = sd.get("resets_at")
    sd_reset_dt = parse_iso_or_epoch(sd_reset_raw)

    if sd_reset_dt and now >= sd_reset_dt:
        sd_util = 0  # Period expired!
    max_util = max(max_util, sd_util)

    if sd_util >= 100:
        if sd_reset_dt and now < sd_reset_dt:
            blocked = True
            diff = sd_reset_dt - now
            block_reason = f"7-day limit reached (resets in {format_time_remaining(diff)})"
            if earliest_reset_dt is None or sd_reset_dt < earliest_reset_dt:
                earliest_reset_dt = sd_reset_dt
        elif not sd_reset_dt:
            blocked = True
            block_reason = "7-day limit reached"

    # Check limits array
    for lim in u.get("limits") or []:
        reset_raw = lim.get("resets_at")
        reset_dt = parse_iso_or_epoch(reset_raw)
        if reset_dt and now >= reset_dt:
            # Period expired!
            continue

        p = lim.get("percent", 0)
        sev = lim.get("severity", "normal")
        active = lim.get("is_active", False)
        max_util = max(max_util, p)

        if p >= 100 or sev == "critical" or active:
            if reset_dt and now < reset_dt:
                blocked = True
                diff = reset_dt - now
                kind = lim.get("kind", "quota")
                block_reason = f"{kind} limit active (resets in {format_time_remaining(diff)})"
                if earliest_reset_dt is None or reset_dt < earliest_reset_dt:
                    earliest_reset_dt = reset_dt
            elif not reset_dt:
                blocked = True
                block_reason = f"{lim.get('kind', 'limit')} active"

    info["five_hour_util"] = fh_util
    info["five_hour_resets_at"] = fh_reset_dt.isoformat() if fh_reset_dt else None
    info["seven_day_util"] = sd_util
    info["seven_day_resets_at"] = sd_reset_dt.isoformat() if sd_reset_dt else None

    if blocked:
        info["available"] = False
        info["utilization"] = max_util
        info["status_detail"] = block_reason
        if earliest_reset_dt:
            info["resets_at"] = earliest_reset_dt.isoformat()
            info["reset_seconds"] = int((earliest_reset_dt - now).total_seconds())
            # For score when blocked, earlier reset is better (100,000 + reset_seconds)
            info["score"] = 100000 + info["reset_seconds"]
        else:
            info["score"] = 900000
    else:
        info["available"] = True
        info["utilization"] = max_util
        info["status_detail"] = f"Available ({max_util}% used)" if max_util > 0 else "Available (100% capacity free)"
        # Score is simply utilization percentage (0 to 99)
        info["score"] = max_util

    return info

def render_bar(percent, width=10, use_color=True):
    """Renders a visually aligned Unicode block progress bar with color coding."""
    if percent is None:
        percent = 0
    p = max(0, min(100, int(percent)))
    filled = int(round(width * p / 100.0))
    empty = width - filled
    bar = "█" * filled + "░" * empty
    raw_str = f"[{bar}] {p:>3}%"
    if not use_color:
        return raw_str
    if p >= 80:
        c = "\033[1;31m"  # Red
    elif p >= 50:
        c = "\033[1;33m"  # Yellow
    else:
        c = "\033[1;32m"  # Green
    return f"{c}{raw_str}\033[0m"

def get_all_profiles():
    if not os.path.exists(PROFILES_DIR):
        return []
    profs = []
    for item in sorted(os.listdir(PROFILES_DIR)):
        full = os.path.join(PROFILES_DIR, item)
        if os.path.isdir(full) and not item.startswith("."):
            profs.append(item)
    return profs

def get_current_profile():
    if os.path.exists(CURRENT_PROFILE_FILE):
        try:
            with open(CURRENT_PROFILE_FILE) as f:
                return f.read().strip().lower()
        except Exception:
            pass
    return "vl"

def switch_to_profile(prof_name):
    with open(CURRENT_PROFILE_FILE, "w") as f:
        f.write(prof_name)
    # Sync credentials & claude.json to shared home
    src_creds = os.path.join(PROFILES_DIR, prof_name, ".credentials.json")
    src_json = os.path.join(PROFILES_DIR, prof_name, ".claude.json")
    dst_creds = os.path.join(SHARED_CLAUDE_DIR, ".credentials.json")
    dst_json = os.path.join(os.path.expanduser("~"), ".claude.json")
    if os.path.exists(src_creds):
        try:
            import shutil
            shutil.copyfile(src_creds, dst_creds)
        except Exception:
            pass
    if os.path.exists(src_json):
        try:
            import shutil
            shutil.copyfile(src_json, dst_json)
        except Exception:
            pass

def main():
    parser = argparse.ArgumentParser(description="Claude Code Multi-Account Capacity & Rate-Limit Engine")
    parser.add_argument("--json", action="store_true", help="Output raw JSON analysis")
    parser.add_argument("--best", action="store_true", help="Print only the best available profile name")
    parser.add_argument("--switch-best", action="store_true", help="Switch active profile to best available profile")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress non-essential text")
    args = parser.parse_args()

    profs = get_all_profiles()
    current = get_current_profile()

    results = []
    for p in profs:
        results.append(check_profile(p))

    # Sort results by score: lower is better
    # Available accounts (score 0-99) come first, lowest utilization wins.
    # Blocked accounts (score 100000+) come next, earliest reset wins.
    # Unauthenticated accounts come last.
    sorted_res = sorted(results, key=lambda x: x["score"])

    best_profile = None
    for r in sorted_res:
        if r["available"]:
            best_profile = r["name"]
            break

    if not best_profile:
        # If none are available, pick the authenticated one that resets earliest
        for r in sorted_res:
            if r["authenticated"]:
                best_profile = r["name"]
                break

    if not best_profile and len(profs) > 0:
        best_profile = profs[0]

    if args.json:
        out = {
            "current_profile": current,
            "best_profile": best_profile,
            "profiles": results,
        }
        print(json.dumps(out, indent=2))
        return

    if args.best:
        print(best_profile or current)
        return

    if args.switch_best:
        if best_profile:
            switch_to_profile(best_profile)
            if not args.quiet:
                print(f"Switched active profile to: {best_profile.upper()}")
        print(best_profile or current)
        return

    # Default: Pretty display
    use_color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    print("=========================================================================================================")
    print("                              Claude Code Multi-Account Capacity & Quota")
    print("=========================================================================================================")
    print(f"Active Default Profile: {current.upper()}")
    print("")
    print(f"  {'PROFILE':<8}  {'EMAIL':<26}  {'PLAN':<10}  {'5h QUOTA (100%)':<17}  {'7d QUOTA (100%)':<17}  {'STATUS'}")
    print(f"  {'-'*8}  {'-'*26}  {'-'*10}  {'-'*17}  {'-'*17}  {'-'*24}")

    for r in results:
        active_marker = " <-- ACTIVE" if r["name"] == current else ""
        avail_icon = "✓" if r["available"] else "✗"
        if r["authenticated"]:
            bar_5h = render_bar(r["five_hour_util"], width=10, use_color=use_color)
            bar_7d = render_bar(r["seven_day_util"], width=10, use_color=use_color)
        else:
            bar_5h = "[N/A]            "
            bar_7d = "[N/A]            "
        status_line = f"[{avail_icon}] {r['status_detail']}{active_marker}"
        print(f"  {r['name'].upper():<8}  {r['email'] or '[No Email]':<26}  {r['subscription'].upper():<10}  {bar_5h}  {bar_7d}  {status_line}")

    print("")
    if best_profile and best_profile != current:
        best_info = next((x for x in results if x["name"] == best_profile), None)
        if best_info and best_info["available"]:
            print(f"💡 Recommended: Switch to [{best_profile.upper()}] ({best_info['email']}) which has capacity!")
            print(f"   Command: cc continue   OR   cc switch {best_profile}")
        else:
            print("⚠️  All accounts currently have usage limits reached.")
            print(f"   Next account to reset: [{best_profile.upper()}] - {best_info['status_detail'] if best_info else ''}")
    elif best_profile and best_profile == current:
        curr_info = next((x for x in results if x["name"] == current), None)
        if curr_info and curr_info["available"]:
            print(f"✓ Current account [{current.upper()}] is healthy and has remaining capacity.")
        else:
            print("⚠️  Active account has limits reached, and no other accounts currently have free capacity.")
    print("=========================================================================================================")

if __name__ == "__main__":
    main()
