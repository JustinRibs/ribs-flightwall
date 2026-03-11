"""
SQLite database for persisting flights that pass over the home location.
Used by radius mode to build historical stats: top airlines, altitude extremes, busiest hours.
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


def get_stats():
    """
    Return stats for the Stats page:
    - top_airlines: most common airlines (last 7 days), ranked by count
    - lowest_flight: lowest altitude flight of the week
    - highest_flight: highest altitude flight of the week
    - busiest_hour: hour of day (0-23) with most flights over the week
    """
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    with _db_lock:
        with _get_conn() as conn:
            top = conn.execute("""
                SELECT airline_icao, airline_name, COUNT(*) as count
                FROM flights
                WHERE seen_at >= ?
                  AND (airline_icao IS NOT NULL AND airline_icao != '')
                GROUP BY airline_icao
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

            busiest = conn.execute("""
                SELECT CAST(strftime('%H', seen_at) AS INTEGER) as hour, COUNT(*) as count
                FROM flights
                WHERE seen_at >= ?
                GROUP BY hour
                ORDER BY count DESC
                LIMIT 1
            """, (cutoff,)).fetchone()

            total_count = conn.execute(
                "SELECT COUNT(*) FROM flights WHERE seen_at >= ?",
                (cutoff,),
            ).fetchone()[0]

    # Convert rows to dicts for JSON
    def row_to_dict(row):
        if row is None:
            return None
        return {k: row[k] for k in row.keys()}

    top_airlines = [
        {"airline_icao": r["airline_icao"], "airline_name": r["airline_name"] or r["airline_icao"], "count": r["count"]}
        for r in top
    ]
    lowest_flight = row_to_dict(lowest)
    highest_flight = row_to_dict(highest)
    busiest_hour = busiest["hour"] if busiest else None
    busiest_count = busiest["count"] if busiest else 0

    return {
        "top_airlines": top_airlines,
        "lowest_flight": lowest_flight,
        "highest_flight": highest_flight,
        "busiest_hour": busiest_hour,
        "busiest_count": busiest_count,
        "total_flights_week": total_count,
    }
