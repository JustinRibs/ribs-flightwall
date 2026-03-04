import math
import time

import requests

import config
from main import get_opensky_token, OPENSKY_URL


def haversine_miles(lat1, lon1, lat2, lon2):
    r_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)
    ) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    km = r_km * c
    return km * 0.621371


def fetch_opensky_within_radius(radius_miles=5.0):
    token = get_opensky_token()
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    lat0 = config.HOME_LAT
    lon0 = config.HOME_LON

    deg_per_mile_lat = 1.0 / 69.0
    lat_delta = radius_miles * deg_per_mile_lat

    deg_per_mile_lon = 1.0 / (69.172 * math.cos(math.radians(lat0)))
    lon_delta = radius_miles * deg_per_mile_lon

    params = {
        "lamin": lat0 - lat_delta,
        "lamax": lat0 + lat_delta,
        "lomin": lon0 - lon_delta,
        "lomax": lon0 + lon_delta,
    }

    print(f"Querying OpenSky with bbox (approx {radius_miles} mi radius):")
    print(
        f"  lat: {params['lamin']:.5f} .. {params['lamax']:.5f}, "
        f"lon: {params['lomin']:.5f} .. {params['lomax']:.5f}"
    )

    resp = requests.get(OPENSKY_URL, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    states = data.get("states") or []
    print(f"\nTotal states in bbox: {len(states)}\n")

    results = []
    for s in states:
        try:
            callsign = (s[1] or "").strip()
            lon = s[5]
            lat = s[6]
            alt_m = s[7]
            on_ground = s[8]
            vel_ms = s[9]

            if lat is None or lon is None:
                continue

            dist = haversine_miles(lat0, lon0, lat, lon)
            if dist > radius_miles:
                continue

            alt_ft = int(alt_m * 3.28084) if alt_m is not None else 0
            speed_kts = int(vel_ms * 1.94384) if vel_ms is not None else 0

            results.append(
                {
                    "icao24": s[0],
                    "callsign": callsign,
                    "lat": lat,
                    "lon": lon,
                    "altitude_ft": alt_ft,
                    "speed_kts": speed_kts,
                    "on_ground": bool(on_ground),
                    "distance_miles": dist,
                }
            )
        except (IndexError, TypeError):
            continue

    results.sort(key=lambda r: r["distance_miles"])
    return results


if __name__ == "__main__":
    try:
        flights = fetch_opensky_within_radius(5.0)
        if not flights:
            print("No aircraft found within 5 miles.")
        else:
            print("Aircraft within 5 miles:\n")
            for f in flights:
                print(
                    f"{f['callsign'] or 'N/A':<8} "
                    f"icao24={f['icao24']}  "
                    f"dist={f['distance_miles']:.2f} mi  "
                    f"alt={f['altitude_ft']} ft  "
                    f"spd={f['speed_kts']} kt  "
                    f"lat={f['lat']:.5f} lon={f['lon']:.5f}  "
                    f"{'GROUND' if f['on_ground'] else 'AIR'}"
                )
    except Exception as e:
        print("Error querying OpenSky:", e)

