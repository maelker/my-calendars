#!/usr/bin/env python3
"""Build subscribable .ics calendars from events.csv.

Usage:
  python scripts/build_ics.py --check          # validate only (used on pull requests)
  python scripts/build_ics.py --out public     # validate + build files + index.html

Rules:
  * Only rows with status == "approved" are published.
  * Categories come from categories.csv (category, slug, calendar_name): one .ics per category.
  * Recurring events: fill `recurrence` (an RRULE, e.g. FREQ=WEEKLY;UNTIL=20271231) and optionally
    `exceptions` (dates to skip, YYYY-MM-DD separated by ';'). Each occurrence is published as its own
    event with uid "<uid>-YYYYMMDD". To change a single occurrence, add its date to `exceptions` of the
    series and add a normal row with uid "<uid>-YYYYMMDD".
  * Optional `geo` column ("lat,lon"): adds GEO + X-APPLE-STRUCTURED-LOCATION so Apple Calendar shows a map pin.
"""
import argparse, csv, sys, hashlib, json, re
from datetime import datetime, timedelta, timezone, date, time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATEGORIES = [("Concert", "concerts", "🎸 Concerts"), ("Festival", "festivals", "🎪 Festivals"),
                      ("Sport", "sports", "🏅 Sport"), ("Esport", "esports", "🎮 Esports"),
                      ("Stream", "streams", "📺 Streams"), ("Personal", "personal", "🏠 Personal"),
                      ("Other", "other", "📌 Other")]
STATUSES = {"pending", "approved", "rejected"}
ALL_NAME = "📅 All events"
DOMAIN = "my-calendars"
HORIZON_DAYS = 730      # open-ended recurrences (no UNTIL/COUNT) are published this far ahead
MAX_OCCURRENCES = 2000


def load_categories(path):
    if not Path(path).exists():
        return DEFAULT_CATEGORIES
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if (r.get("category") or "").strip():
                out.append((r["category"].strip(), (r.get("slug") or r["category"]).strip().lower(),
                            (r.get("calendar_name") or r["category"]).strip()))
    return out or DEFAULT_CATEGORIES


def check_tz_database():
    """Fail early with a clear message if this machine has no IANA timezone data
    (typical on Windows): the fix is `pip install tzdata`."""
    try:
        ZoneInfo("Europe/Paris")
    except ZoneInfoNotFoundError:
        print("ERROR: no timezone database found on this machine.\n"
              "Fix: run  pip install tzdata  (or  pip install -r requirements.txt)  and try again.\n"
              "Your events.csv is not the problem.")
        sys.exit(2)


def parse_local(text):
    """-> (naive datetime | date, is_all_day). Date-only text => all-day event."""
    text = text.strip()
    if len(text) == 10:
        return datetime.strptime(text, "%Y-%m-%d").date(), True
    return datetime.strptime(text, "%Y-%m-%d %H:%M"), False


def to_utc(naive, tzname):
    return naive.replace(tzinfo=ZoneInfo(tzname)).astimezone(timezone.utc)


def occurrences(rule, start_local, all_day, tzname, exceptions):
    """Expand an RRULE into a list of local start values (naive datetime or date)."""
    try:
        from dateutil.rrule import rrulestr
    except ImportError:
        raise ValueError("python-dateutil is missing: run  pip install python-dateutil")
    rule = rule.strip()
    if rule.upper().startswith("RRULE:"):
        rule = rule[6:]
    if all_day:
        rule = re.sub(r"UNTIL=(\d{8})(T\d{6}Z?)?", r"UNTIL=\1", rule)
        dtstart = datetime.combine(start_local, time.min)
    else:
        dtstart = start_local.replace(tzinfo=ZoneInfo(tzname))
    # A date-only UNTIL (UNTIL=20271231) on a timed event: keep every occurrence up to and including that local day.
    until_date = None
    m = re.search(r"UNTIL=(\d{8})(?![\dT])", rule, re.I)
    if m and not all_day:
        until_date = datetime.strptime(m.group(1), "%Y%m%d").date()
        rule = re.sub(r";?UNTIL=\d{8}(?![\dT])", "", rule, flags=re.I).lstrip(";")
    rr = rrulestr(rule, dtstart=dtstart)
    open_ended = until_date is None and "UNTIL=" not in rule.upper() and "COUNT=" not in rule.upper()
    horizon = datetime.now() + timedelta(days=HORIZON_DAYS)
    out = []
    for o in rr:
        local = o.replace(tzinfo=None)
        if until_date and local.date() > until_date:
            break
        if open_ended and local > horizon:
            break
        if len(out) >= MAX_OCCURRENCES:
            raise ValueError(f"more than {MAX_OCCURRENCES} occurrences: add UNTIL or COUNT")
        if local.date().isoformat() in exceptions:
            continue
        out.append(local.date() if all_day else local)
    return out


def load_events(path, categories):
    cats = {c: s for c, s, _ in categories}
    errors, events, seen = [], [], set()
    with open(path, newline="", encoding="utf-8-sig") as f:
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
            if cat not in cats:
                errors.append(f"line {n} ({uid}): category must be one of {list(cats)} (see categories.csv)")
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
                s_local, all_day = parse_local(row.get("start") or "")
                end_text = (row.get("end") or "").strip()
                if end_text:
                    e_local, e_all = parse_local(end_text)
                    if e_all != all_day:
                        raise ValueError("start and end must both be date-only or both date+time")
                else:
                    e_local = s_local if all_day else s_local + timedelta(hours=2)
                if all_day and e_local < s_local:
                    raise ValueError("end must not be before start")
                if not all_day and e_local <= s_local:
                    raise ValueError("end must be after start")
            except Exception as e:
                errors.append(f"line {n} ({uid}): bad start/end ({e}). Use YYYY-MM-DD HH:MM or YYYY-MM-DD")
                continue
            geo = (row.get("geo") or "").strip()
            if geo:
                try:
                    lat, lon = [float(x) for x in geo.replace(";", ",").split(",")]
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        raise ValueError
                    geo = f"{lat:.6f},{lon:.6f}"
                except ValueError:
                    errors.append(f"line {n} ({uid}): bad geo '{geo}' (use lat,lon e.g. 45.1885,5.7245)")
                    continue
            rule = (row.get("recurrence") or "").strip()
            exceptions = {x.strip() for x in (row.get("exceptions") or "").split(";") if x.strip()}
            for x in exceptions:
                try:
                    datetime.strptime(x, "%Y-%m-%d")
                except ValueError:
                    errors.append(f"line {n} ({uid}): bad exception date '{x}' (use YYYY-MM-DD)")
            if rule:
                try:
                    starts = occurrences(rule, s_local, all_day, tzname, exceptions)
                except Exception as e:
                    errors.append(f"line {n} ({uid}): bad recurrence ({e})")
                    continue
            else:
                starts = [s_local]
            span = e_local - s_local
            for s in starts:
                e = s + span
                if all_day:
                    start, end = s, e + timedelta(days=1)   # DTEND is exclusive for all-day events
                else:
                    start, end = to_utc(s, tzname), to_utc(e, tzname)
                suffix = f"-{s.strftime('%Y%m%d')}" if rule else ""
                events.append(dict(
                    uid=uid + suffix, cat=cat, emoji=(row.get("emoji") or "").strip(), title=title,
                    start=start, end=end, all_day=all_day,
                    location=(row.get("location") or "").strip(), geo=geo,
                    url=(row.get("url") or "").strip(),
                    notes=(row.get("notes") or "").strip(), series=bool(rule), base_uid=uid))
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
    digest = hashlib.sha1(repr((e["title"], str(e["start"]), str(e["end"]), e["location"], e.get("geo", ""), e["notes"])).encode()).hexdigest()
    seq = int(digest[:6], 16) % 100000  # changes when the event changes, so clients refresh it
    lines = ["BEGIN:VEVENT", f"UID:{e['uid']}@{DOMAIN}", f"DTSTAMP:{stamp}", f"SEQUENCE:{seq}"]
    if e["all_day"]:
        lines += [f"DTSTART;VALUE=DATE:{fmt(e['start'], True)}", f"DTEND;VALUE=DATE:{fmt(e['end'], True)}"]
    else:
        lines += [f"DTSTART:{fmt(e['start'], False)}", f"DTEND:{fmt(e['end'], False)}"]
    lines.append(f"SUMMARY:{esc(summary)}")
    if e["location"]:
        lines.append(f"LOCATION:{esc(e['location'])}")
    if e["geo"]:
        lat, lon = e["geo"].split(",")
        lines.append(f"GEO:{lat};{lon}")
        label = (e["location"] or e["title"]).replace('"', "'").replace("\n", " ")
        title = label.split(",")[0].strip()
        lines.append(f'X-APPLE-STRUCTURED-LOCATION;VALUE=URI;X-ADDRESS="{label}";X-APPLE-RADIUS=100;X-TITLE="{title}":geo:{lat},{lon}')
    desc = "\n".join(x for x in (e["notes"], e["url"]) if x)
    if desc:
        lines.append(f"DESCRIPTION:{esc(desc)}")
    if e["url"]:
        lines.append(f"URL:{e['url']}")
    lines.append("END:VEVENT")
    return lines


def sort_key(e):
    s = e["start"]
    return datetime.combine(s, time.min, timezone.utc) if e["all_day"] else s


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
<h1>My calendars</h1><p>Tap a link to subscribe, or copy the URL into "Add calendar from URL".</p><ul id="l"></ul><p><a href="view.html">📅 Voir les événements</a> · <a href="edit.html">✏️ Modifier les événements</a></p>
<script>
const items=__ITEMS__;
const base=location.href.replace(/index\\.html$/,'').replace(/\\/?$/,'/');
document.getElementById('l').innerHTML=items.map(([f,n,c])=>
 `<li><a href="${base.replace(/^https?:/,'webcal:')}${f}.ics">${n}</a> (${c} events)<br><code>${base}${f}.ics</code></li>`).join('');
</script>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="events.csv")
    ap.add_argument("--categories", default=str(ROOT / "categories.csv"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    check_tz_database()
    categories = load_categories(a.categories)
    events, errors = load_events(a.csv, categories)
    if errors:
        print("Validation errors:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    series = len({e["base_uid"] for e in events if e["series"]})
    print(f"OK: {len(events)} published events ({series} recurring series expanded)")
    if a.check or not a.out:
        return
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for cat, slug, name in categories:
        subset = [e for e in events if e["cat"] == cat]
        (out / f"{slug}.ics").write_text(calendar(name, subset), encoding="utf-8", newline="")
        index.append([slug, name, len(subset)])
    (out / "all.ics").write_text(calendar(ALL_NAME, events), encoding="utf-8", newline="")
    index.append(["all", ALL_NAME, len(events)])
    (out / "index.html").write_text(INDEX.replace("__ITEMS__", json.dumps(index, ensure_ascii=False)), encoding="utf-8")
    print("Built:", ", ".join(f"{s}.ics" for s, _, _ in index))


if __name__ == "__main__":
    main()
