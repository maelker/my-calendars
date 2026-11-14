#!/usr/bin/env python3
"""Build subscribable .ics calendars from events.csv.

Usage:
  python scripts/build_ics.py --check          # validate only (used on pull requests)
  python scripts/build_ics.py --out public     # validate + build files + index.html
Only rows with status == "approved" are published.
"""
import argparse, csv, sys, hashlib, json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CATEGORIES = {"Concert": "concerts", "Sport": "sports", "Esport": "esports"}
STATUSES = {"pending", "approved", "rejected"}
CAL_NAMES = {"concerts": "🎸 Concerts", "sports": "🏅 Sport", "esports": "🎮 Esports", "all": "📅 All events"}
DOMAIN = "my-calendars"


def parse_when(text, tzname):
    """Return (value, is_all_day). Date-only text => all-day event."""
    text = text.strip()
    if len(text) == 10:
        return datetime.strptime(text, "%Y-%m-%d").date(), True
    local = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(tzname))
    return local.astimezone(timezone.utc), False


def load_events(path):
    errors, events, seen = [], [], set()
    with open(path, newline="", encoding="utf-8") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            uid = (row.get("uid") or "").strip()
            if not uid:
                if any((v or "").strip() for v in row.values()):
                    errors.append(f"line {n}: missing uid")
                continue
            if uid in seen:
                errors.append(f"line {n}: duplicate uid '{uid}'")
            seen.add(uid)
            status = (row.get("status") or "").strip().lower()
            if status not in STATUSES:
                errors.append(f"line {n} ({uid}): status must be one of {sorted(STATUSES)}")
                continue
            if status != "approved":
                continue
            cat = (row.get("category") or "").strip()
            if cat not in CATEGORIES:
                errors.append(f"line {n} ({uid}): category must be one of {list(CATEGORIES)}")
                continue
            title = (row.get("title") or "").strip()
            if not title:
                errors.append(f"line {n} ({uid}): missing title")
                continue
            tzname = (row.get("timezone") or "Europe/Paris").strip()
            try:
                ZoneInfo(tzname)
            except Exception:
                errors.append(f"line {n} ({uid}): unknown timezone '{tzname}'")
                continue
            try:
                start, all_day = parse_when(row.get("start") or "", tzname)
                end_text = (row.get("end") or "").strip()
                if end_text:
                    end, end_all_day = parse_when(end_text, tzname)
                    if end_all_day != all_day:
                        raise ValueError("start and end must both be date-only or both date+time")
                else:
                    end = start if all_day else start + timedelta(hours=2)
                if all_day:
                    if end < start:
                        raise ValueError("end must not be before start")
                    end = end + timedelta(days=1)  # DTEND is exclusive for all-day events
                elif end <= start:
                    raise ValueError("end must be after start")
            except Exception as e:
                errors.append(f"line {n} ({uid}): bad start/end ({e}). Use YYYY-MM-DD HH:MM or YYYY-MM-DD")
                continue
            events.append(dict(
                uid=uid, cat=cat, emoji=(row.get("emoji") or "").strip(), title=title,
                start=start, end=end, all_day=all_day,
                location=(row.get("location") or "").strip(),
                url=(row.get("url") or "").strip(),
                notes=(row.get("notes") or "").strip()))
    return events, errors


def esc(s):
    return (s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
             .replace("\r\n", "\\n").replace("\n", "\\n"))


def fold(line):
    """RFC 5545: lines max 75 octets, continuation lines start with a space."""
    if len(line.encode("utf-8")) <= 75:
        return line
    out, cur, size = [], "", 0
    for ch in line:
        b = len(ch.encode("utf-8"))
        limit = 75 if not out else 74
        if size + b > limit:
            out.append(cur)
            cur, size = "", 0
        cur += ch
        size += b
    out.append(cur)
    return "\r\n ".join(out)


def fmt(dt, all_day):
    return dt.strftime("%Y%m%d") if all_day else dt.strftime("%Y%m%dT%H%M%SZ")


def vevent(e, stamp):
    summary = f"{e['emoji']} {e['title']}".strip()
    digest = hashlib.sha1(repr((e["title"], str(e["start"]), str(e["end"]), e["location"], e["notes"])).encode()).hexdigest()
    seq = int(digest[:6], 16) % 100000  # changes when the event changes, so clients refresh it
    lines = ["BEGIN:VEVENT", f"UID:{e['uid']}@{DOMAIN}", f"DTSTAMP:{stamp}", f"SEQUENCE:{seq}"]
    if e["all_day"]:
        lines += [f"DTSTART;VALUE=DATE:{fmt(e['start'], True)}", f"DTEND;VALUE=DATE:{fmt(e['end'], True)}"]
    else:
        lines += [f"DTSTART:{fmt(e['start'], False)}", f"DTEND:{fmt(e['end'], False)}"]
    lines.append(f"SUMMARY:{esc(summary)}")
    if e["location"]:
        lines.append(f"LOCATION:{esc(e['location'])}")
    desc = "\n".join(x for x in (e["notes"], e["url"]) if x)
    if desc:
        lines.append(f"DESCRIPTION:{esc(desc)}")
    if e["url"]:
        lines.append(f"URL:{e['url']}")
    lines.append("END:VEVENT")
    return lines


def sort_key(e):
    s = e["start"]
    return datetime.combine(s, datetime.min.time(), timezone.utc) if e["all_day"] else s


def calendar(name, events):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{DOMAIN}//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{esc(name)}", "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    for e in sorted(events, key=sort_key):
        lines += vevent(e, stamp)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


INDEX = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>My calendars</title>
<style>body{font:16px/1.5 system-ui,sans-serif;max-width:560px;margin:2rem auto;padding:0 1rem}
li{margin:.6rem 0}code{font-size:.85em;word-break:break-all}</style>
<h1>My calendars</h1><p>Tap a link to subscribe, or copy the URL into "Add calendar from URL".</p><ul id="l"></ul>
<script>
const items=__ITEMS__;
const base=location.href.replace(/index\\.html$/,'').replace(/\\/?$/,'/');
document.getElementById('l').innerHTML=items.map(([f,n,c])=>
 `<li><a href="${base.replace(/^https?:/,'webcal:')}${f}.ics">${n}</a> (${c} events)<br><code>${base}${f}.ics</code></li>`).join('');
</script>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="events.csv")
    ap.add_argument("--out", default=None)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    events, errors = load_events(a.csv)
    if errors:
        print("Validation errors:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print(f"OK: {len(events)} approved events")
    if a.check or not a.out:
        return
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for cat, slug in CATEGORIES.items():
        subset = [e for e in events if e["cat"] == cat]
        (out / f"{slug}.ics").write_text(calendar(CAL_NAMES[slug], subset), encoding="utf-8", newline="")
        index.append([slug, CAL_NAMES[slug], len(subset)])
    (out / "all.ics").write_text(calendar(CAL_NAMES["all"], events), encoding="utf-8", newline="")
    index.append(["all", CAL_NAMES["all"], len(events)])
    (out / "index.html").write_text(INDEX.replace("__ITEMS__", json.dumps(index, ensure_ascii=False)), encoding="utf-8")
    print("Built:", ", ".join(f"{s}.ics" for s, _, _ in index))


if __name__ == "__main__":
    main()
