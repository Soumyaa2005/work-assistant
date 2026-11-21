"""Where the data lives, plus people, clients and time helpers. The only module that knows file layout."""
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

UTC = timezone.utc


def root() -> str:
    env = os.environ.get("R3_PACK")
    if env and os.path.isdir(os.path.join(env, "data")):
        return os.path.abspath(env)
    return os.getcwd()


def store_path() -> str:
    return os.environ.get("ASSIST_STORE") or os.path.join(os.getcwd(), ".assist_store.sqlite")


def read_jsonl(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def day_records(day: int) -> list[dict]:
    return read_jsonl(os.path.join(root(), "data", "days", f"day-{day:02d}.jsonl"))


def day_feedback(day: int) -> list[dict]:
    return read_jsonl(os.path.join(root(), "data", "feedback", f"day-{day:02d}.jsonl"))


@lru_cache(maxsize=1)
def people() -> dict[str, dict]:
    """id -> {id, name, role, team, zone, org}. Handles both org-keyed and flat layouts."""
    p = os.path.join(root(), "data", "people.json")
    out: dict[str, dict] = {}
    if not os.path.isfile(p):
        return out
    raw = json.load(open(p, encoding="utf-8"))
    if isinstance(raw, dict):
        for org, v in raw.items():
            for person in (v.get("people", []) if isinstance(v, dict) else []):
                out[person["id"]] = {**person, "org": org}
    else:
        for person in raw:
            out[person["id"]] = {**person, "org": person.get("org", "org_kp")}
    return out


@lru_cache(maxsize=1)
def clients() -> list[dict]:
    p = os.path.join(root(), "data", "clients.json")
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else []


def org_of(pid: str) -> str:
    return people().get(pid, {}).get("org", "org_kp")


def name_of(pid: str | None) -> str:
    return people().get(pid or "", {}).get("name") or (pid or "someone")


def first_name(pid: str | None) -> str:
    return name_of(pid).split()[0]


def zone_of(pid: str) -> ZoneInfo:
    try:
        return ZoneInfo(people().get(pid, {}).get("zone") or "Asia/Kolkata")
    except Exception:
        return ZoneInfo("Asia/Kolkata")


def parse_ts(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_date(ts: str, pid: str) -> date:
    return parse_ts(ts).astimezone(zone_of(pid)).date()


def local_midnight_utc(d: date, pid: str) -> str:
    return iso(datetime(d.year, d.month, d.day, tzinfo=zone_of(pid)))


def fmt_day(d: date | str) -> str:
    """6 Nov"""
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return f"{d.day} {d.strftime('%b')}"


_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_WEEKDAYS = {n: i for i, n in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}


def parse_day_month(s: str, year: int) -> str | None:
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3})[a-z]*\b", s)
    if m and m.group(2).lower() in _MONTHS:
        return f"{year:04d}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return None


def next_weekday(d: date, name: str, strictly_after: bool) -> date | None:
    wd = _WEEKDAYS.get(name.lower())
    if wd is None:
        return None
    delta = (wd - d.weekday()) % 7
    if delta == 0 and strictly_after:
        delta = 7
    return d + timedelta(days=delta)


def can_see(person: str, rec: dict) -> bool:
    """Same org only; private to author; restricted to listed readers."""
    if rec["org"] != org_of(person):
        return False
    v = rec.get("visibility", "team")
    if v == "private":
        return rec.get("author") == person
    if v == "restricted":
        return person in (rec.get("readers") or [])
    return True
