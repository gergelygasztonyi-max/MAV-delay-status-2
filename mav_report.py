#!/usr/bin/env python3
"""Biatorbágy morning MÁV live-status report."""
from __future__ import annotations
import json, os, urllib.error, urllib.parse, urllib.request
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Budapest")
API_URL = os.environ.get("MAV_API_URL", "https://regi-elvira.kajc10.deno.net")
STATIONS = {
    "Biatorbágy": (47.4728, 18.8231),
    "Budapest-Kelenföld": (47.4647, 19.0204),
    "Budapest-Déli": (47.5001, 19.0255),
}

def gql_query(departure_time: str, search_window: int) -> str:
    return f"""
query Plan($fromLat:Float!,$fromLon:Float!,$toLat:Float!,$toLon:Float!,$date:String!) {{
  plan(from:{{lat:$fromLat,lon:$fromLon}},to:{{lat:$toLat,lon:$toLon}},
       date:$date,time:"{departure_time}",arriveBy:false,
       numItineraries:200,searchWindow:{search_window},
       transportModes:[{{mode:RAIL}}]) {{
    routingErrors {{ code inputField }}
    itineraries {{
      startTime endTime
      legs {{
        mode realTime startTime endTime departureDelay arrivalDelay
        from {{ name departureTime }}
        to {{ name arrivalTime }}
        trip {{ gtfsId tripShortName tripHeadsign }}
        route {{ shortName longName mode }}
        agency {{ name }}
        intermediatePlaces {{ name arrivalTime departureTime
          arrival {{ estimated {{ delay }} }}
          departure {{ estimated {{ delay }} }} }}
      }}
    }}
  }}
}}
"""

def request_graphql(query: str, variables: dict) -> dict:
    params = urllib.parse.urlencode({"query": query, "variables": json.dumps(variables, separators=(",", ":"))})
    req = urllib.request.Request(f"{API_URL}?{params}", headers={"User-Agent": "MAV-delay-status-2/0.1"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            status, body = response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code != 405:
            raise RuntimeError(f"MÁV proxy HTTP {e.code}: {e.read(500).decode('utf-8','replace')}")
        payload = json.dumps({"query": query, "variables": variables}).encode()
        req = urllib.request.Request(API_URL, data=payload, headers={"Content-Type": "application/json", "User-Agent": "MAV-delay-status-2/0.1"}, method="POST")
        with urllib.request.urlopen(req, timeout=25) as response:
            status, body = response.status, response.read().decode("utf-8")
    data = json.loads(body)
    if data.get("errors"):
        raise RuntimeError("GraphQL error: " + "; ".join(str(e.get("message", e)) for e in data["errors"]))
    if not isinstance(data.get("data", {}).get("plan"), dict):
        raise RuntimeError(f"Unexpected API response (HTTP {status}): {body[:400]}")
    return data["data"]["plan"]

def local_time(value):
    return datetime.fromtimestamp(float(value) / 1000, TZ) if value is not None else None

def fmt_time(value):
    return value.strftime("%H:%M") if value else "—"

def get_report(target_date: date, window_start: time, window_end: time):
    start_dt = datetime.combine(target_date, window_start, TZ)
    end_dt = datetime.combine(target_date, window_end, TZ)
    seconds = max(60, int((end_dt - start_dt).total_seconds()))
    rows, errors = [], []
    for destination in ("Budapest-Kelenföld", "Budapest-Déli"):
        plan = request_graphql(
            gql_query(window_start.strftime("%H:%M:%S"), seconds),
            {"fromLat": STATIONS["Biatorbágy"][0], "fromLon": STATIONS["Biatorbágy"][1],
             "toLat": STATIONS[destination][0], "toLon": STATIONS[destination][1], "date": target_date.isoformat()},
        )
        errors.extend(plan.get("routingErrors") or [])
        for itinerary in plan.get("itineraries") or []:
            for leg in itinerary.get("legs") or []:
                if leg.get("mode") != "RAIL":
                    continue
                from_name = (leg.get("from") or {}).get("name", "")
                if "biatorbágy" not in from_name.casefold():
                    continue
                trip = leg.get("trip") or {}
                if not str(trip.get("gtfsId") or "").startswith("1:"):
                    continue
                live_departure = local_time(leg.get("startTime"))
                if not live_departure or not (start_dt <= live_departure <= end_dt):
                    continue
                delay_seconds = leg.get("departureDelay")
                has_live = leg.get("realTime") is True and delay_seconds is not None
                scheduled = live_departure - timedelta(seconds=float(delay_seconds)) if has_live else None
                route = leg.get("route") or {}
                rows.append({
                    "scheduled": scheduled, "live": live_departure if has_live else None,
                    "delay_minutes": round(float(delay_seconds) / 60) if has_live else None,
                    "train": trip.get("tripShortName") or route.get("shortName") or "—",
                    "headsign": trip.get("tripHeadsign") or route.get("longName") or (leg.get("to") or {}).get("name") or destination,
                    "destination": destination, "real_time": has_live, "trip_id": trip.get("gtfsId"),
                })
    unique = {}
    for row in rows:
        key = (row["trip_id"], row["scheduled"].isoformat() if row["scheduled"] else row["live"].isoformat() if row["live"] else row["headsign"])
        unique[key] = row
    return sorted(unique.values(), key=lambda r: r["scheduled"] or r["live"] or datetime.max.replace(tzinfo=TZ)), errors

def make_markdown(rows, errors, target_date):
    lines = [
        f"# Biatorbágy–Budapest MÁV reggeli státusz — {target_date.isoformat()}",
        "", f"Adatlekérés: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}", "",
        "| Menetrend szerinti indulás | Vonat | Célállomás | Élő/várható indulás | Késés |",
        "|---|---|---|---|---:|",
    ]
    for r in rows:
        live = fmt_time(r["live"]) if r["real_time"] else "élő késési adat nem elérhető"
        delay = f'{r["delay_minutes"]:+d} perc' if r["delay_minutes"] is not None else "—"
        lines.append(f'| {fmt_time(r["scheduled"])} | {r["train"]} | {r["destination"]} | {live} | {delay} |')
    if not rows:
        lines.append("| — | — | — | élő késési adat nem elérhető | — |")
    late = [r for r in rows if r["delay_minutes"] is not None and r["delay_minutes"] > 0]
    known = [r["delay_minutes"] for r in rows if r["delay_minutes"] is not None]
    lines += ["", "## Összesítés", f"- Vizsgált vonatok: {len(rows)}",
              f"- Késő vonatok (ismert, pozitív késés): {len(late)}",
              f"- Legnagyobb ismert késés: {max(known)} perc" if known else "- Legnagyobb ismert késés: nem állapítható meg"]
    if errors:
        lines += ["", "## API figyelmeztetések"] + [f'- {e.get("code", "ismeretlen hiba")} ({e.get("inputField", "mező nem ismert")})' for e in errors]
    lines += ["", "Forrás: MÁVPlusz/EMMA útvonaltervező közösségi proxyja. Nem hivatalos API; változhat vagy elérhetetlenné válhat."]
    return "\n".join(lines) + "\n"

def main():
    mode = os.environ.get("REPORT_MODE", "morning")
    now = datetime.now(TZ)
    target_date = date.fromisoformat(os.environ["REPORT_DATE"]) if os.environ.get("REPORT_DATE") else now.date()
    if mode == "validate":
        start = now.replace(second=0, microsecond=0)
        finish = start + timedelta(minutes=90)
        # Validation is deliberately near-current; past morning departures cannot validate live data.
        rows, errors = get_report(target_date, start.time().replace(tzinfo=None), finish.time().replace(tzinfo=None))
        print(f"API_VALIDATION: window={start:%H:%M}-{finish:%H:%M}, rows={len(rows)}")
        print("API_VALIDATION: routing_errors=" + json.dumps(errors, ensure_ascii=False))
        print("API_VALIDATION: sample=" + json.dumps([{k:(v.isoformat() if isinstance(v,datetime) else v) for k,v in r.items()} for r in rows[:3]], ensure_ascii=False))
        if not rows:
            raise SystemExit("Validation failed: no Biatorbágy-origin railway departures found in next 90 minutes.")
        if not any(r["real_time"] for r in rows):
            raise SystemExit("Validation incomplete: journeys found but no explicit live departure estimate exposed.")
        print("API_VALIDATION: PASS — explicit live departure estimate observed.")
        return
    rows, errors = get_report(target_date, time(5,55), time(7,10))
    report = make_markdown(rows, errors, target_date)
    print(report)
    os.makedirs("out", exist_ok=True)
    open("out/report.md", "w", encoding="utf-8").write(report)
    with open("out/report.json", "w", encoding="utf-8") as f:
        json.dump({"date": target_date.isoformat(), "fetched_at": datetime.now(TZ).isoformat(),
                   "rows": [{k:(v.isoformat() if isinstance(v,datetime) else v) for k,v in r.items()} for r in rows],
                   "routing_errors": errors}, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
