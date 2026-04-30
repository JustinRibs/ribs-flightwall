import json
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def _split_csv(val: str) -> list:
    """Split a comma-separated env var into a clean upper-cased list."""
    if not val:
        return []
    return [v.strip().upper() for v in val.split(",") if v.strip()]


# Home coordinates
HOME_LAT = float(os.getenv("HOME_LAT", "0.0"))
HOME_LON = float(os.getenv("HOME_LON", "0.0"))

# OpenSky API Credentials
OPENSKY_CLIENT_ID = ""
OPENSKY_CLIENT_SECRET = ""

# FlightAware API Credentials
FLIGHTAWARE_API_KEY = os.getenv("FLIGHTAWARE_API_KEY", "")

# logo.dev publishable token (for airline logos in web UI and matrix)
LOGO_DEV_TOKEN = os.getenv("LOGO_DEV_TOKEN", "")

creds_path = os.path.join(os.path.dirname(__file__), "credentials.json")
if os.path.exists(creds_path):
    try:
        with open(creds_path, "r") as f:
            creds = json.load(f)
            OPENSKY_CLIENT_ID = creds.get("clientId", "")
            OPENSKY_CLIENT_SECRET = creds.get("clientSecret", "")
    except Exception as e:
        print(f"Error reading credentials.json: {e}")

# Matrix Configuration
MATRIX_BRIGHTNESS = int(os.getenv("MATRIX_BRIGHTNESS", "60"))

# Application Settings
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))  # Seconds between monitor-mode polls
FR24_POLL_INTERVAL = int(os.getenv("FR24_POLL_INTERVAL", "10"))  # CRITICAL: 10s for FlightRadar24 to avoid IP-block
MONITOR_POLL_INTERVAL = int(os.getenv("MONITOR_POLL_INTERVAL", "60"))  # FlightAware (avoid high costs)
ARRIVALS_POLL_INTERVAL = int(os.getenv("ARRIVALS_POLL_INTERVAL", "90"))  # Arrivals board (AeroAPI)
WEATHER_POLL_INTERVAL = int(os.getenv("WEATHER_POLL_INTERVAL", "300"))  # Weather (OpenWeatherMap, 5 min)
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5003")) # Use 5001 locally, override to 80 on Pi in .env

# --- Special-flight alerts ---------------------------------------------------
# Heavies / rare aircraft that should always trigger an alert (ICAO type codes)
SPECIAL_AIRCRAFT_CODES = {
    "A388",  # A380
    "B748",  # 747-8
    "B744",  # 747-400
    "A359", "A35K",  # A350
    "B77W", "B77L", "B772", "B773", "B778", "B779",  # 777 family
    "B789", "B788", "B78X",  # 787 family
    "AN24", "AN26", "AN72", "AN12", "AN22", "AN124", "AN225",  # Antonovs
    "C5", "C5M", "C17", "K35R", "K35E",  # Heavy military transports / tankers
}
# Extra type codes via env var (comma-separated)
SPECIAL_AIRCRAFT_CODES.update(_split_csv(os.getenv("SPECIAL_AIRCRAFT_CODES", "")))

# Callsign prefixes that should always trigger an alert (3-letter operators or military patterns)
SPECIAL_CALLSIGN_PREFIXES = {
    "RCH",   # USAF Reach (Air Mobility Command)
    "AF1", "AF2",  # Air Force One/Two
    "SAM",   # Special Air Mission (POTUS/VPOTUS support)
    "EXEC",  # Executive
    "PAT",   # US Army priority air transport
    "NAVY", "ARMY", "USAF", "USCG", "MARINE",
    "BLUE", "THUNDER",  # Demo teams
}
SPECIAL_CALLSIGN_PREFIXES.update(_split_csv(os.getenv("SPECIAL_CALLSIGN_PREFIXES", "")))

# User-defined favorite callsigns (always alert + log).
FAVORITE_CALLSIGNS = set(_split_csv(os.getenv("FAVORITE_CALLSIGNS", "")))

# How long the matrix flashes when a special flight enters radius (seconds)
SPECIAL_ALERT_DURATION = int(os.getenv("SPECIAL_ALERT_DURATION", "20"))

# --- Discord ----------------------------------------------------------------
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_DAILY_SUMMARY = os.getenv("DISCORD_DAILY_SUMMARY", "1") not in ("0", "false", "False", "")
# Hour of day (0..23) at which to post the daily summary (local time on the device)
DISCORD_DAILY_SUMMARY_HOUR = int(os.getenv("DISCORD_DAILY_SUMMARY_HOUR", "20"))
DISCORD_ALERT_SPECIAL = os.getenv("DISCORD_ALERT_SPECIAL", "1") not in ("0", "false", "False", "")
