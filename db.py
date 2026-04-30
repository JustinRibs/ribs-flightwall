"""
SQLite database for persisting flights that pass over the home location.
Used by radius mode to build historical stats: top airlines, altitude extremes, busiest hours,
aircraft leaderboards, top routes, calendar heatmaps, and on-this-day records.
"""
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

# Database path (in project directory)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "flights.db")

_db_lock = threading.Lock()

# Minimum seconds between recording the same callsign (avoids 50 records for one slow pass)
RECORD_COOLDOWN_SEC = 90
_last_recorded = {"callsign": "", "time": 0.0}


@contextmanager
def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create the flights table if it doesn't exist."""
    with _db_lock:
        with _get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS flights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    callsign TEXT NOT NULL,
                    airline_icao TEXT,
                    airline_name TEXT,
                    altitude INTEGER,
                    speed INTEGER,
                    origin_iata TEXT,
                    dest_iata TEXT,
                    route TEXT,
                    aircraft_model TEXT,
                    aircraft_code TEXT,
                    seen_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_flights_seen_at ON flights(seen_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_flights_airline ON flights(airline_icao)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_flights_aircraft ON flights(aircraft_code)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS special_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    callsign TEXT NOT NULL,
                    airline_icao TEXT,
                    aircraft_code TEXT,
                    aircraft_model TEXT,
                    route TEXT,
                    reason TEXT NOT NULL,
                    seen_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_seen_at ON special_alerts(seen_at)")


def record_flight(flight_data: dict) -> bool:
    """
    Record a flight pass. Returns True if recorded, False if skipped (cooldown).
    Only records in radius mode; flight_data should match fetch_fr24_data() format.
    """
    if not flight_data or not isinstance(flight_data, dict):
        return False

    callsign = (flight_data.get("callsign") or "").strip().upper()
    if not callsign:
        return False

    import time
    now = time.time()
    with _db_lock:
        if callsign == _last_recorded["callsign"] and (now - _last_recorded["time"]) < RECORD_COOLDOWN_SEC:
            return False
        _last_recorded["callsign"] = callsign
        _last_recorded["time"] = now

    seen_at = datetime.now().isoformat()
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO flights (callsign, airline_icao, airline_name, altitude, speed,
                                origin_iata, dest_iata, route, aircraft_model, aircraft_code, seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                callsign,
                (flight_data.get("airline_icao") or "").strip().upper()[:3] or None,
                (flight_data.get("airline_name") or "").strip() or None,
                flight_data.get("altitude"),
                flight_data.get("speed"),
                (flight_data.get("origin_iata") or "").strip().upper()[:3] or None,
                (flight_data.get("dest_iata") or "").strip().upper()[:3] or None,
                (flight_data.get("route") or "").strip() or None,
                (flight_data.get("aircraft_model") or "").strip() or None,
                (flight_data.get("aircraft_code") or "").strip().upper() or None,
                seen_at,
            ),
        )
    return True


def record_special_alert(flight_data: dict, reason: str) -> None:
    """Record a special-flight alert (rare aircraft, military, favorite, etc.)."""
    if not flight_data:
        return
    callsign = (flight_data.get("callsign") or "").strip().upper()
    if not callsign:
        return
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO special_alerts
                (callsign, airline_icao, aircraft_code, aircraft_model, route, reason, seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                callsign,
                (flight_data.get("airline_icao") or "").strip().upper()[:3] or None,
                (flight_data.get("aircraft_code") or "").strip().upper() or None,
                (flight_data.get("aircraft_model") or "").strip() or None,
                (flight_data.get("route") or "").strip() or None,
                reason,
                datetime.now().isoformat(),
            ),
        )


def list_recent_alerts(limit: int = 20) -> list:
    with _db_lock:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT callsign, airline_icao, aircraft_code, aircraft_model, route, reason, seen_at "
                "FROM special_alerts ORDER BY seen_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


# Map period codes to a (cutoff_iso, label) tuple. "all" returns a far-past cutoff.
def _period_cutoff(period: str) -> str:
    period = (period or "week").lower()
    if period == "day":
        return (datetime.now() - timedelta(days=1)).isoformat()
    if period == "month":
        return (datetime.now() - timedelta(days=30)).isoformat()
    if period == "year":
        return (datetime.now() - timedelta(days=365)).isoformat()
    if period == "all":
        return "1970-01-01"
    # default week
    return (datetime.now() - timedelta(days=7)).isoformat()


def get_stats(period: str = "week"):
    """
    Return rich stats for the Stats page, scoped to the given period.

    Period values: "day", "week", "month", "year", "all". Defaults to "week".

    Returns:
      - period
      - total_flights
      - top_airlines (top 15)
      - top_aircraft (top 15)
      - top_routes (top 15)
      - lowest_flight, highest_flight, fastest_flight
      - busiest_hour, busiest_count
      - hourly_histogram (24 buckets, 0..23)
    """
    cutoff = _period_cutoff(period)

    with _db_lock:
        with _get_conn() as conn:
            top_airlines_rows = conn.execute("""
                SELECT airline_icao, airline_name, COUNT(*) as count
                FROM flights
                WHERE seen_at >= ?
                  AND (airline_icao IS NOT NULL AND airline_icao != '')
                GROUP BY airline_icao
                ORDER BY count DESC
                LIMIT 15
            """, (cutoff,)).fetchall()

            top_aircraft_rows = conn.execute("""
                SELECT aircraft_code, aircraft_model, COUNT(*) as count
                FROM flights
                WHERE seen_at >= ?
                  AND aircraft_code IS NOT NULL
                  AND aircraft_code != ''
                GROUP BY aircraft_code
                ORDER BY count DESC
                LIMIT 15
            """, (cutoff,)).fetchall()

            top_routes_rows = conn.execute("""
                SELECT origin_iata, dest_iata, COUNT(*) as count
                FROM flights
                WHERE seen_at >= ?
                  AND origin_iata IS NOT NULL AND origin_iata != ''
                  AND dest_iata   IS NOT NULL AND dest_iata   != ''
                GROUP BY origin_iata, dest_iata
                ORDER BY count DESC
                LIMIT 15
            """, (cutoff,)).fetchall()

            lowest = conn.execute("""
                SELECT callsign, airline_icao, airline_name, altitude, route, seen_at
                FROM flights
                WHERE seen_at >= ? AND altitude IS NOT NULL AND altitude > 0
                ORDER BY altitude ASC
                LIMIT 1
            """, (cutoff,)).fetchone()

            highest = conn.execute("""
                SELECT callsign, airline_icao, airline_name, altitude, route, seen_at
                FROM flights
                WHERE seen_at >= ? AND altitude IS NOT NULL
                ORDER BY altitude DESC
                LIMIT 1
            """, (cutoff,)).fetchone()

            fastest = conn.execute("""
                SELECT callsign, airline_icao, airline_name, speed, route, seen_at
                FROM flights
                WHERE seen_at >= ? AND speed IS NOT NULL
                ORDER BY speed DESC
                LIMIT 1
            """, (cutoff,)).fetchone()

            histogram_rows = conn.execute("""
                SELECT CAST(strftime('%H', seen_at) AS INTEGER) as hour, COUNT(*) as count
                FROM flights
                WHERE seen_at >= ?
                GROUP BY hour
            """, (cutoff,)).fetchall()

            total_count = conn.execute(
                "SELECT COUNT(*) FROM flights WHERE seen_at >= ?",
                (cutoff,),
            ).fetchone()[0]

    def row_to_dict(row):
        if row is None:
            return None
        return {k: row[k] for k in row.keys()}

    top_airlines = [
        {"airline_icao": r["airline_icao"], "airline_name": r["airline_name"] or r["airline_icao"], "count": r["count"]}
        for r in top_airlines_rows
    ]
    top_aircraft = [
        {"aircraft_code": r["aircraft_code"], "aircraft_model": r["aircraft_model"] or r["aircraft_code"], "count": r["count"]}
        for r in top_aircraft_rows
    ]
    top_routes = [
        {"origin": r["origin_iata"], "dest": r["dest_iata"], "count": r["count"]}
        for r in top_routes_rows
    ]

    histogram = [0] * 24
    for r in histogram_rows:
        h = r["hour"]
        if h is not None and 0 <= h < 24:
            histogram[h] = r["count"]
    busiest_hour = None
    busiest_count = 0
    for h, c in enumerate(histogram):
        if c > busiest_count:
            busiest_hour = h
            busiest_count = c

    return {
        "period": period,
        "total_flights": total_count,
        # Backwards-compatible alias used by older callers
        "total_flights_week": total_count,
        "top_airlines": top_airlines,
        "top_aircraft": top_aircraft,
        "top_routes": top_routes,
        "lowest_flight": row_to_dict(lowest),
        "highest_flight": row_to_dict(highest),
        "fastest_flight": row_to_dict(fastest),
        "busiest_hour": busiest_hour,
        "busiest_count": busiest_count,
        "hourly_histogram": histogram,
    }


def get_calendar(days: int = 90):
    """
    Return per-day flight counts for the last `days` days, oldest first.
    [{ "date": "YYYY-MM-DD", "count": int }, ...]
    """
    days = max(1, min(int(days or 90), 366))
    start = (datetime.now() - timedelta(days=days - 1)).date()
    cutoff = start.isoformat()
    with _db_lock:
        with _get_conn() as conn:
            rows = conn.execute("""
                SELECT substr(seen_at, 1, 10) as day, COUNT(*) as count
                FROM flights
                WHERE seen_at >= ?
                GROUP BY day
            """, (cutoff,)).fetchall()
    counts = {r["day"]: r["count"] for r in rows}
    out = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        out.append({"date": d, "count": counts.get(d, 0)})
    return out


def get_on_this_day():
    """
    Return a tiny "on this day" recap based on the same calendar month/day in prior years.

    {
        "today_count":   <int>,
        "history_count": <int>,           # total flights on this MM-DD across all prior years
        "first_seen":    {"date": "...", "callsign": "..."},  # earliest flight in DB
        "current_streak_days": <int>,     # consecutive days with at least 1 flight ending today
    }
    """
    today = datetime.now().date()
    today_iso = today.isoformat()
    md = today.strftime("%m-%d")

    with _db_lock:
        with _get_conn() as conn:
            today_count = conn.execute(
                "SELECT COUNT(*) FROM flights WHERE substr(seen_at, 1, 10) = ?",
                (today_iso,),
            ).fetchone()[0]

            history_count = conn.execute(
                "SELECT COUNT(*) FROM flights WHERE substr(seen_at, 6, 5) = ? AND substr(seen_at, 1, 10) != ?",
                (md, today_iso),
            ).fetchone()[0]

            first = conn.execute(
                "SELECT seen_at, callsign FROM flights ORDER BY seen_at ASC LIMIT 1"
            ).fetchone()

            # Streak: walk back day-by-day until a day with no flights
            day_rows = conn.execute("""
                SELECT DISTINCT substr(seen_at, 1, 10) as day
                FROM flights
                WHERE seen_at >= ?
                ORDER BY day DESC
            """, ((today - timedelta(days=120)).isoformat(),)).fetchall()
    seen_days = {r["day"] for r in day_rows}
    streak = 0
    cursor = today
    while cursor.isoformat() in seen_days:
        streak += 1
        cursor = cursor - timedelta(days=1)

    first_seen = None
    if first:
        first_seen = {"date": (first["seen_at"] or "")[:10], "callsign": first["callsign"]}

    return {
        "today_count": today_count,
        "history_count": history_count,
        "first_seen": first_seen,
        "current_streak_days": streak,
    }


def get_heatmap_grid(width: int = 60, height: int = 24, days: int = 7):
    """
    Build a width×height "density grid" of flights from the last `days` days, where:
      - x axis: hour-of-day buckets (0..23 mapped across width)
      - y axis: altitude bands (0=low altitude near top, height-1=high altitude near bottom)

    Returns a list of `height` rows, each a list of `width` ints (raw counts).
    Used by the matrix heatmap mode and by the dashboard heatmap calendar fallback.
    """
    width = max(8, int(width))
    height = max(4, int(height))
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    grid = [[0] * width for _ in range(height)]

    with _db_lock:
        with _get_conn() as conn:
            rows = conn.execute("""
                SELECT
                    CAST(strftime('%H', seen_at) AS INTEGER) as hour,
                    altitude
                FROM flights
                WHERE seen_at >= ?
            """, (cutoff,)).fetchall()

    for r in rows:
        hour = r["hour"]
        alt = r["altitude"] or 0
        if hour is None:
            continue
        # x: 24 hours mapped across `width` columns
        x = int(hour * width / 24)
        if x >= width:
            x = width - 1
        # y: 0..45000 ft mapped across `height` rows (clamped). 0 = highest band (top of matrix).
        if alt <= 0:
            band = height - 1
        else:
            ratio = max(0.0, min(1.0, alt / 45000.0))
            band = int((1.0 - ratio) * (height - 1))
            band = max(0, min(height - 1, band))
        grid[band][x] += 1

    return grid


def get_db_size_bytes() -> int:
    try:
        return os.path.getsize(DB_PATH)
    except OSError:
        return 0


def get_total_flight_count() -> int:
    with _db_lock:
        with _get_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
