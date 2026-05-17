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
# Categorized aircraft type codes (ICAO type designators). 777/787/A350 etc.
# are deliberately NOT here — they fly overhead constantly and aren't rare.

# Active-duty military fighters / attack jets.
FIGHTER_AIRCRAFT_CODES = {
    "F14",                    # Tomcat (warbirds — civilian-operated)
    "F15", "F15E",            # Eagle / Strike Eagle
    "F16",                    # Fighting Falcon
    "F18", "FA18", "F18S",    # Hornet / Super Hornet
    "F22",                    # Raptor
    "F35",                    # Lightning II
    "A10",                    # Thunderbolt II
    "AV8B",                   # Harrier
    "EUFI",                   # Eurofighter Typhoon
    "RFAL",                   # Rafale
    "T38",                    # Talon trainer
}

# Bombers and strategic / surveillance / vintage warbirds.
WARBIRD_AIRCRAFT_CODES = {
    "B1",   "B2",  "B52",     # Lancer / Spirit / Stratofortress
    "B17",  "B25", "B29",     # WWII bombers
    "P51",  "P38", "P47",     # WWII fighters
    "SPIT",                   # Spitfire
    "DC3",  "DC4", "DC6",     # Vintage props
    "CONC",                   # Concorde (😉 — for the env-overrides crowd)
    "U2",   "SR71",           # Spy planes
    "F117",                   # Nighthawk
    "AT6",                    # T-6 Texan
}

# Genuinely rare / interesting heavies and military support aircraft.
RARE_AIRCRAFT_CODES = {
    "A388",                              # A380
    "B748", "B744", "B742", "B743",      # 747 family (8/400/200/300)
    "AN12", "AN22", "AN72",              # Antonov tactical transports
    "AN124", "AN225",                    # Ruslan / Mriya
    "C5",   "C5M",                       # C-5 Galaxy
    "C17",                               # Globemaster III
    "C130", "C30J",                      # Hercules
    "K35R", "K35E", "KC10",              # Tankers
    "E3CF", "E3TF",                      # AWACS
    "E6",                                # Mercury
    "P3",   "P8",                        # Maritime patrol
    "V22",                               # Osprey
}

# Convenience set: anything in here is "special" by aircraft type alone.
SPECIAL_AIRCRAFT_CODES = (
    FIGHTER_AIRCRAFT_CODES
    | WARBIRD_AIRCRAFT_CODES
    | RARE_AIRCRAFT_CODES
)
# Extra type codes via env var (comma-separated) — get classified as "rare" by default.
_extra = set(_split_csv(os.getenv("SPECIAL_AIRCRAFT_CODES", "")))
RARE_AIRCRAFT_CODES = RARE_AIRCRAFT_CODES | _extra
SPECIAL_AIRCRAFT_CODES = SPECIAL_AIRCRAFT_CODES | _extra

# Callsign prefixes that should always trigger an alert. Military / VIP only —
# generic / common civilian-collision-prone prefixes have been removed.
SPECIAL_CALLSIGN_PREFIXES = {
    "RCH",                            # USAF Reach (Air Mobility Command)
    "AF1", "AF2",                     # Air Force One/Two
    "SAM",                            # Special Air Mission (POTUS/VPOTUS support)
    "PAT",                            # US Army priority air transport
    "NAVY", "ARMY", "USAF", "USCG", "MARINE",
    "BLUE",                           # Blue Angels (BLUE1..BLUE6)
    "THUNDER",                        # Thunderbirds
    "VADER",                          # USAF aggressors
    "REACH",                          # alt for RCH
    "DOOM",                           # B-1B nuclear standby
    "SLAM",                           # F/A-18 demo
    "VIPER",                          # F-16 demo
}
SPECIAL_CALLSIGN_PREFIXES.update(_split_csv(os.getenv("SPECIAL_CALLSIGN_PREFIXES", "")))

# User-defined favorite callsigns (always alert + log).
FAVORITE_CALLSIGNS = set(_split_csv(os.getenv("FAVORITE_CALLSIGNS", "")))

# How long the matrix flashes when a special flight enters radius (seconds)
SPECIAL_ALERT_DURATION = int(os.getenv("SPECIAL_ALERT_DURATION", "20"))

# Reason → RGB color for the persistent accent stripe + row-4 reason tag.
# Same palette as _build_alert_overlay so the strobe and the steady accent
# read as the same "language".
SPECIAL_REASON_COLORS = {
    "favorite":      (255, 200,   0),
    "vip":           (255, 255, 255),
    "military":      (130, 200,  80),
    "fighter":       (255,  60,  60),
    "warbird":       (200, 140,  60),
    "rare-aircraft": (255,   0, 200),
}

# Short on-matrix tag rendered as the 3rd slot of the row-4 cycle when a
# special flight is being tracked. Aircraft code (e.g. "F22") wins when
# available; this is the fallback by reason.
SPECIAL_REASON_TAGS = {
    "favorite":      "FAV",
    "vip":           "VIP",
    "military":      "MIL",
    "fighter":       "FTR",
    "warbird":       "WAR",
    "rare-aircraft": "RARE",
}

# Emergency squawk reasons get their own bright-red palette and bypass the
# 1-hour special-flight debounce.
EMERGENCY_SQUAWK_COLOR = (255, 30, 30)
EMERGENCY_SQUAWK_REASONS = {
    "7500": ("emergency-7500", "🚨 Hijack squawk"),
    "7600": ("emergency-7600", "🚨 Radio failure squawk"),
    "7700": ("emergency-7700", "🚨 Emergency squawk"),
}

# --- Auto night dimming -----------------------------------------------------
# Clamps matrix brightness during local night-time hours so the board isn't
# blinding at 2am. Never raises brightness above the user's manual setting.
NIGHT_DIM_ENABLED = os.getenv("NIGHT_DIM_ENABLED", "1") not in ("0", "false", "False", "")
NIGHT_DIM_START_HOUR = int(os.getenv("NIGHT_DIM_START_HOUR", "22"))  # 0..23 local
NIGHT_DIM_END_HOUR = int(os.getenv("NIGHT_DIM_END_HOUR", "6"))       # 0..23 local
NIGHT_DIM_BRIGHTNESS = max(1, min(100, int(os.getenv("NIGHT_DIM_BRIGHTNESS", "15"))))

# --- Discord ----------------------------------------------------------------
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_DAILY_SUMMARY = os.getenv("DISCORD_DAILY_SUMMARY", "1") not in ("0", "false", "False", "")
# Hour of day (0..23) at which to post the daily summary (local time on the device)
DISCORD_DAILY_SUMMARY_HOUR = int(os.getenv("DISCORD_DAILY_SUMMARY_HOUR", "20"))
DISCORD_ALERT_SPECIAL = os.getenv("DISCORD_ALERT_SPECIAL", "1") not in ("0", "false", "False", "")
