import json
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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
FLASK_PORT = int(os.getenv("FLASK_PORT", "5001")) # Use 5001 locally, override to 80 on Pi in .env
