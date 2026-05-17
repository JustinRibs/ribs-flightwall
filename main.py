import math
import os
import re
import subprocess
import tempfile
import time
import threading
import logging
from io import BytesIO

import requests
import db
from flask import Flask, render_template, request, jsonify, send_file
from PIL import Image, ImageDraw, ImageFont, BdfFontFile
import config

# FlightRadar24 API for radius mode (replaces OpenSky)
try:
    from FlightRadar24 import FlightRadar24API
    fr_api = FlightRadar24API()
    FR24_AVAILABLE = True
except ImportError:
    FR24_AVAILABLE = False
    fr_api = None

# Try to import rgbmatrix, fallback to dummy for development on non-Pi systems
try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
    MATRIX_AVAILABLE = True
except ImportError:
    MATRIX_AVAILABLE = False
    logging.warning("rgbmatrix library not found. Running in simulation mode without hardware matrix.")

# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize Flask
app = Flask(__name__)

# Font paths (relative to project directory)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(BASE_DIR, "assets", "fonts")


def load_bdf_font(bdf_path: str):
    """Convert a .bdf font to .pil on first run, then load and return it."""
    pil_path = os.path.splitext(bdf_path)[0] + ".pil"
    if not os.path.exists(pil_path):
        with open(bdf_path, "rb") as fp:
            bdf = BdfFontFile.BdfFontFile(fp)
            bdf.save(pil_path)
    return ImageFont.load(pil_path)


FONT_6X10   = load_bdf_font(os.path.join(FONTS_DIR, "6x10.bdf"))
FONT_5X8    = load_bdf_font(os.path.join(FONTS_DIR, "5x8.bdf"))
FONT_THUMB  = load_bdf_font(os.path.join(FONTS_DIR, "tom-thumb.bdf"))

# Matrix brightness persistence file
BRIGHTNESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".matrix_brightness")

def _load_matrix_brightness() -> int:
    """Load saved brightness from file, or fall back to config."""
    try:
        if os.path.exists(BRIGHTNESS_FILE):
            with open(BRIGHTNESS_FILE, "r") as f:
                val = int(f.read().strip())
                return max(1, min(100, val))
    except (ValueError, OSError):
        pass
    return config.MATRIX_BRIGHTNESS


# Global Application State
app_state = {
    "mode": "radius",       # "radius", "monitor", "arrivals", or "text"
    "callsign": "",         # Target callsign for monitor mode
    "airport": "",          # Target airport IATA/ICAO for arrivals mode (e.g. JFK, KJFK)
    "text_message": "",     # Message for text mode
    "text_color": "#00FF00", # Hex color for text mode
    "current_flight": None, # Cache the latest flight data
    "current_arrivals": [], # List of arrivals for arrivals mode
    "current_weather": None, # Cache for weather mode
    "last_seen_flight": None, # Last flight seen in radius mode (shown when nothing in range)
    "last_seen_at": None,     # Timestamp when last_seen_flight was recorded
    "matrix_brightness": _load_matrix_brightness(),
}
state_lock = threading.Lock()

# Constants
AEROAPI_URL = "https://aeroapi.flightaware.com/aeroapi"

# Airline ICAO → website domain for logo.dev lookups
AIRLINE_DOMAINS = {
    # US Majors
    "AAL": "aa.com",
    "UAL": "united.com",
    "DAL": "delta.com",
    "SWA": "southwest.com",
    "JBU": "jetblue.com",
    "ASA": "alaskaair.com",
    "FFT": "flyfrontier.com",
    "NKS": "spirit.com",
    "HAL": "hawaiianairlines.com",
    # Europe
    "BAW": "britishairways.com",
    "AFR": "airfrance.com",
    "DLH": "lufthansa.com",
    "KLM": "klm.com",
    "IBE": "iberia.com",
    "VLG": "vueling.com",
    "EZY": "easyjet.com",
    "RYR": "ryanair.com",
    "WZZ": "wizzair.com",
    "SAS": "flysas.com",
    "FIN": "finnair.com",
    "THY": "turkishairlines.com",
    "EIN": "aerlingus.com",
    "VIR": "virginatlantic.com",
    "BEL": "brusselsairlines.com",
    # Middle East
    "UAE": "emirates.com",
    "QTR": "qatarairways.com",
    "ETD": "etihad.com",
    "ELY": "elal.com",
    # Asia-Pacific
    "SIA": "singaporeair.com",
    "KAL": "koreanair.com",
    "JAL": "jal.com",
    "ANA": "ana.co.jp",
    "CPA": "cathaypacific.com",
    "MAS": "malaysiaairlines.com",
    "THA": "thaiairways.com",
    "QFA": "qantas.com",
    "AIC": "airindia.in",
    # Americas
    "AVA": "avianca.com",
    "GLO": "voegol.com.br",
    "TAM": "latam.com",
    "LAN": "latam.com",
    "ACA": "aircanada.com",
    "WJA": "westjet.com",
    "AMX": "aeromexico.com",
}

# Airline ICAO → short display name for matrix row 0
AIRLINE_NAMES = {
    "AAL": "American", "UAL": "United",    "DAL": "Delta",
    "SWA": "Southwest","JBU": "JetBlue",   "ASA": "Alaska",
    "FFT": "Frontier",  "NKS": "Spirit",    "HAL": "Hawaiian",
    "BAW": "Brit Air",  "AFR": "Air France","DLH": "Lufthansa",
    "KLM": "KLM",       "IBE": "Iberia",    "VLG": "Vueling",
    "EZY": "easyJet",   "RYR": "Ryanair",   "WZZ": "Wizz Air",
    "SAS": "SAS",       "FIN": "Finnair",   "THY": "Turkish",
    "EIN": "Aer Lingus","VIR": "Virgin Atl","BEL": "Brussels",
    "UAE": "Emirates",  "QTR": "Qatar",     "ETD": "Etihad",
    "ELY": "El Al",     "SIA": "Singapore", "KAL": "Korean Air",
    "JAL": "JAL",       "ANA": "ANA",       "CPA": "Cathay",
    "MAS": "Malaysia",  "THA": "Thai",      "QFA": "Qantas",
    "AIC": "Air India", "AVA": "Avianca",   "ACA": "Air Canada",
    "WJA": "WestJet",   "AMX": "Aeromexico","GLO": "Gol",
    "TAM": "LATAM",     "LAN": "LATAM",
}

# ICAO aircraft type → short friendly name for matrix bottom row
AIRCRAFT_NAMES = {
    # Airbus
    "A318": "A318", "A319": "A319", "A320": "A320", "A321": "A321",
    "A19N": "A319neo", "A20N": "A320neo", "A21N": "A321neo",
    "A332": "A330-200", "A333": "A330-300", "A338": "A330-800", "A339": "A330-900",
    "A342": "A340-200", "A343": "A340-300",
    "A359": "A350-900", "A35K": "A350-1000",
    "A388": "A380",
    # Boeing
    "B712": "717",
    "B732": "737-200", "B733": "737-300", "B734": "737-400", "B735": "737-500",
    "B736": "737-600", "B737": "737-700", "B738": "737-800", "B739": "737-900",
    "B37M": "737 MAX 7", "B38M": "737 MAX 8", "B39M": "737 MAX 9", "B3XM": "737 MAX 10",
    "B741": "747-100", "B742": "747-200", "B743": "747-300", "B744": "747-400", "B748": "747-8",
    "B752": "757-200", "B753": "757-300",
    "B762": "767-200", "B763": "767-300", "B764": "767-400",
    "B772": "777-200", "B77L": "777-200LR", "B773": "777-300", "B77W": "777-300ER",
    "B778": "777X-8", "B779": "777X-9",
    "B788": "787-8", "B789": "787-9", "B78X": "787-10",
    # Embraer
    "E135": "ERJ-135", "E145": "ERJ-145",
    "E170": "E170", "E175": "E175", "E190": "E190", "E195": "E195",
    "E75L": "E175-E2", "E75S": "E175", "E7W": "E190-E2", "E290": "E195-E2",
    # Bombardier / CRJ
    "CRJ1": "CRJ-100", "CRJ2": "CRJ-200", "CRJ7": "CRJ-700",
    "CRJ9": "CRJ-900", "CRJX": "CRJ-1000",
    # Dash 8 / ATR
    "DH8A": "Dash 8-100", "DH8B": "Dash 8-200", "DH8C": "Dash 8-300", "DH8D": "Dash 8-400",
    "AT45": "ATR 42", "AT76": "ATR 72",
    # Legacy / other
    "MD11": "MD-11", "MD82": "MD-82", "MD83": "MD-83", "MD88": "MD-88", "MD90": "MD-90",
    "DC9": "DC-9", "DC10": "DC-10",
    "C208": "Cessna Caravan", "PC12": "Pilatus PC-12",
}

# IATA → short airport/city name for matrix bottom row (max 9 chars to fit at x=2)
AIRPORT_NAMES = {
    # New York area
    "JFK": "New York", "LGA": "New York", "EWR": "Newark",
    "ISP": "Islip",    "HPN": "White Plns","FRG": "Farmingdl",
    # East Coast
    "BOS": "Boston",   "PHL": "Philly",    "DCA": "Wash DCA",
    "IAD": "Wash IAD", "BWI": "Baltimore", "RDU": "Raleigh",
    "CLT": "Charlotte","ATL": "Atlanta",   "MCO": "Orlando",
    "TPA": "Tampa",    "MIA": "Miami",     "FLL": "Ft Lauder",
    "PBI": "Palm Bch",
    # Midwest
    "ORD": "Chicago",  "MDW": "Chi Midway","DTW": "Detroit",
    "MSP": "Mnpls",    "MCI": "K City",    "STL": "St Louis",
    "CMH": "Columbus", "CLE": "Cleveland", "IND": "Indy",
    # South / Central
    "DFW": "Dallas FW","DAL": "Dallas",    "IAH": "Houston",
    "HOU": "Houston",  "MSY": "N Orleans", "MEM": "Memphis",
    "BNA": "Nashville",
    # Mountain / West
    "DEN": "Denver",   "SLC": "Salt Lake", "PHX": "Phoenix",
    "LAS": "Las Vegas","ABQ": "Albuquer",
    # West Coast
    "LAX": "L Angeles","SFO": "San Fran",  "SJC": "San Jose",
    "OAK": "Oakland",  "SEA": "Seattle",   "PDX": "Portland",
    "SAN": "San Diego","SMF": "Sacramnto", "SNA": "Orng Cnty",
    # Hawaii / Alaska
    "HNL": "Honolulu", "OGG": "Maui",      "KOA": "Kona",
    "ANC": "Anchorage",
    # Canada
    "YYZ": "Toronto",  "YVR": "Vancouver", "YUL": "Montreal",
    "YYC": "Calgary",
    # Mexico / Caribbean
    "MEX": "Mexico Cty","CUN": "Cancun",   "SJU": "San Juan",
    "NAS": "Nassau",
    # Europe
    "LHR": "London",   "LGW": "London LGW","CDG": "Paris CDG",
    "ORY": "Paris",    "AMS": "Amsterdam", "FRA": "Frankfurt",
    "MAD": "Madrid",   "BCN": "Barcelona", "FCO": "Rome",
    "MXP": "Milan",    "ZRH": "Zurich",    "VIE": "Vienna",
    "MUC": "Munich",   "BRU": "Brussels",  "CPH": "Copenhgn",
    "OSL": "Oslo",     "ARN": "Stockholm", "HEL": "Helsinki",
    "DUB": "Dublin",   "MAN": "Manchester","EDI": "Edinburgh",
    "IST": "Istanbul", "SAW": "Istanbul",
    # Middle East / Africa
    "DXB": "Dubai",    "AUH": "Abu Dhabi", "DOH": "Doha",
    "TLV": "Tel Aviv", "CAI": "Cairo",     "JNB": "Joburg",
    "CPT": "Cape Town","ADD": "Addis Abba",
    # Asia-Pacific
    "SIN": "Singapore","HKG": "Hong Kong", "NRT": "Tokyo NRT",
    "HND": "Tokyo HND","KIX": "Osaka",     "ICN": "Seoul",
    "PEK": "Beijing",  "PVG": "Shanghai",  "CTU": "Chengdu",
    "BKK": "Bangkok",  "KUL": "KL",        "CGK": "Jakarta",
    "MNL": "Manila",   "DEL": "New Delhi", "BOM": "Mumbai",
    "SYD": "Sydney",   "MEL": "Melbourne", "BNE": "Brisbane",
    # South America
    "GRU": "Sao Paulo","GIG": "Rio",       "BOG": "Bogota",
    "SCL": "Santiago", "LIM": "Lima",      "EZE": "B Aires",
}

# Nearby airports (user knows these) — show the *other* airport's full name on matrix Line 2
NEARBY_AIRPORTS = {"LGA", "JFK", "ISP", "EWR"}

# In-memory cache for logo.dev raw bytes — shared by web route and matrix renderer
# Keys: ICAO code (str). Values: bytes on success, None on failure.
logodev_cache: dict = {}


def _shorten_aircraft(model: str) -> str:
    """Strip manufacturer prefix for compact matrix display: 'Boeing 737 MAX 9' → '737 MAX 9'."""
    if not model:
        return ""
    for prefix in ("Boeing ", "Airbus ", "Embraer ", "Bombardier ", "McDonnell Douglas ", "ATR "):
        if model.startswith(prefix):
            return model[len(prefix):]
    return model


def _shorten_airport_name(name: str) -> str:
    """Shorten common words in airport names to fit better on matrix."""
    if not name:
        return ""
    name = name.replace("International Airport", "Intl")
    name = name.replace("International", "Intl")
    name = name.replace("Airport", "")
    return name.replace("  ", " ").strip()


def _draw_scrolling_text(image: Image.Image, text: str, font, fill: tuple, x: int, y: int, max_w: int, current_time: float):
    """Draw text that smoothly scrolls horizontally if it exceeds max_w."""
    if not text:
        return
        
    # Measure full width
    temp_img = Image.new("RGB", (1, 1))
    temp_draw = ImageDraw.Draw(temp_img)
    text_w = temp_draw.textlength(text, font=font)
    
    if text_w <= max_w:
        # Fits perfectly, draw directly
        draw = ImageDraw.Draw(image)
        draw.text((x, y), text, font=font, fill=fill)
        return
        
    # Text is too long, we need to scroll
    overflow = text_w - max_w
    
    # Scrolling config
    scroll_speed = 15.0  # pixels per second
    pause_time = 1.5     # seconds to pause at ends
    
    scroll_duration = overflow / scroll_speed
    cycle_time = pause_time + scroll_duration + pause_time
    
    # Calculate current position in the cycle
    cycle_pos = current_time % cycle_time
    
    if cycle_pos < pause_time:
        offset_x = 0
    elif cycle_pos < pause_time + scroll_duration:
        offset_x = -((cycle_pos - pause_time) * scroll_speed)
    else:
        offset_x = -overflow
        
    # Draw onto a temporary clipping canvas
    clip_canvas = Image.new("RGBA", (max_w, 16), (0, 0, 0, 0))
    clip_draw = ImageDraw.Draw(clip_canvas)
    clip_draw.text((int(offset_x), 0), text, font=font, fill=(fill[0], fill[1], fill[2], 255))
    
    # Paste the clipped text onto the main image
    image.paste(clip_canvas, (x, y), clip_canvas)


def _get_logo_dev_url(icao_code: str) -> str | None:
    """Return logo.dev image URL for the given airline ICAO, or None if unknown/unconfigured."""
    if not config.LOGO_DEV_TOKEN:
        return None
    domain = AIRLINE_DOMAINS.get(icao_code.upper())
    if not domain:
        return None
    return f"https://img.logo.dev/{domain}?token={config.LOGO_DEV_TOKEN}&format=png&size=128"


def _fetch_logo_dev_bytes(icao_code: str) -> bytes | None:
    """Fetch and cache raw PNG bytes from logo.dev for the given airline ICAO."""
    icao_code = icao_code.upper()
    if icao_code in logodev_cache:
        return logodev_cache[icao_code]
    url = _get_logo_dev_url(icao_code)
    if not url:
        logodev_cache[icao_code] = None
        return None
    t0 = time.time()
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        logodev_cache[icao_code] = resp.content
        _record_health("logodev", True, int((time.time() - t0) * 1000))
        logging.info(f"logo.dev: cached logo for {icao_code}")
        return resp.content
    except Exception as e:
        _record_health("logodev", False, int((time.time() - t0) * 1000), str(e))
        logging.warning(f"logo.dev fetch failed for {icao_code}: {e}")
        logodev_cache[icao_code] = None
        return None


# FR24 commercial filter: ignore flights with N/A or missing origin/destination
NA_VALUES = (None, "", "N/A", "n/a")

def init_matrix():
    """Initialize the 64x32 LED matrix for Adafruit RGB Matrix Bonnet on Pi Zero 2 W."""
    if not MATRIX_AVAILABLE:
        return None

    options = RGBMatrixOptions()
    options.rows = 32
    options.cols = 64
    options.hardware_mapping = 'adafruit-hat'  # CRITICAL for the Bonnet
    options.gpio_slowdown = 2                  # Required to prevent flickering on Pi Zero 2 W
    options.panel_type = 'FM6126A'
    options.drop_privileges = False            # Required to run Flask and GPIO simultaneously as root
    options.brightness = config.MATRIX_BRIGHTNESS

    return RGBMatrix(options=options)

# Global cache for AeroAPI to prevent overcharges
aeroapi_cache = {
    "callsign": "",
    "data": None,
    "time": 0
}

# Cache for arrivals board (airport -> list of flight dicts)
arrivals_cache = {
    "airport": "",
    "data": [],
    "time": 0
}

# Cache for weather data (OpenWeatherMap)
weather_cache = {"data": None, "time": 0}

def fetch_aeroapi_data(callsign):
    """
    Fetch flight position for a callsign via AeroAPI. The /flights/{ident} summary
    does not include last_position, so we find En Route flights and call the
    /flights/{fa_flight_id}/position endpoint for live position data.
    """
    global aeroapi_cache

    # Return cached data if within the polling interval and callsign hasn't changed
    now = time.time()
    if callsign == aeroapi_cache["callsign"] and now - aeroapi_cache["time"] < config.MONITOR_POLL_INTERVAL:
        return aeroapi_cache["data"]

    if not config.FLIGHTAWARE_API_KEY:
        logging.error("No FlightAware API key configured")
        return None

    headers = {"x-apikey": config.FLIGHTAWARE_API_KEY}
    callsign_upper = callsign.strip().upper()
    t0 = time.time()

    try:
        # Step 1: Get flights for this ident (ident_type=designator forces callsign, not registration)
        list_url = f"{AEROAPI_URL}/flights/{callsign_upper}"
        list_resp = requests.get(
            list_url, headers=headers,
            params={"ident_type": "designator"},
            timeout=10
        )
        _bump_aero_call_counter()
        list_resp.raise_for_status()
        list_data = list_resp.json()
        flights = list_data.get("flights", [])

        if not flights:
            aeroapi_cache = {"callsign": callsign_upper, "data": None, "time": now}
            _record_health("aero", True, int((time.time() - t0) * 1000))
            logging.info(f"AeroAPI: No flights found for {callsign_upper}")
            return None

        # Step 2: Find an En Route flight (summary endpoint does NOT include last_position)
        enroute = [
            f for f in flights
            if f.get("status") and "En Route" in str(f.get("status", ""))
        ]

        # If no En Route, try any flight's position endpoint (scheduled may have projected position)
        candidates = enroute if enroute else flights[:3]

        for flight in candidates:
            fa_flight_id = flight.get("fa_flight_id")
            if not fa_flight_id:
                continue

            # Step 3: Fetch position — only this endpoint returns last_position
            pos_url = f"{AEROAPI_URL}/flights/{fa_flight_id}/position"
            pos_resp = requests.get(pos_url, headers=headers, timeout=10)
            _bump_aero_call_counter()
            pos_resp.raise_for_status()
            pos_data = pos_resp.json()
            pos = pos_data.get("last_position")

            if not pos:
                continue

            altitude = pos.get("altitude", 0) * 100  # AeroAPI returns hundreds of feet
            speed = pos.get("groundspeed", 0)  # knots

            origin = pos_data.get("origin") or {}
            destination = pos_data.get("destination") or {}
            orig_iata = (origin.get("code_iata") or "").strip().upper() if isinstance(origin, dict) else ""
            dest_iata = (destination.get("code_iata") or "").strip().upper() if isinstance(destination, dict) else ""
            orig_name = (origin.get("name") or "").strip() if isinstance(origin, dict) else ""
            dest_name = (destination.get("name") or "").strip() if isinstance(destination, dict) else ""
            
            if not orig_iata:
                orig_iata = (origin.get("code_icao") or "").strip().upper()[:3] if isinstance(origin, dict) else ""
            if not dest_iata:
                dest_iata = (destination.get("code_icao") or "").strip().upper()[:3] if isinstance(destination, dict) else ""

            # Derive airline ICAO from ident (e.g. UAL4 -> UAL)
            operator = (flight.get("operator_icao") or flight.get("operator") or callsign_upper[:3] or "").strip().upper()[:3]

            result = {
                "callsign": (pos_data.get("ident") or callsign_upper).strip().upper(),
                "altitude": int(altitude),
                "speed": int(speed),
                "route": f"{orig_iata} - {dest_iata}" if orig_iata and dest_iata else "",
                "origin_iata": orig_iata,
                "dest_iata": dest_iata,
                "origin_name": orig_name,
                "dest_name": dest_name,
                "airline_icao": operator,
                "airline_name": AIRLINE_NAMES.get(operator, ""),
            }

            aeroapi_cache = {"callsign": callsign_upper, "data": result, "time": now}
            _record_health("aero", True, int((time.time() - t0) * 1000))
            logging.info(f"AeroAPI: Found {result['callsign']} at {altitude}ft, {speed}kt ({orig_iata}-{dest_iata})")
            return result

        aeroapi_cache = {"callsign": callsign_upper, "data": None, "time": now}
        _record_health("aero", True, int((time.time() - t0) * 1000))
        logging.info(f"AeroAPI: No active position for {callsign_upper} (flights may be scheduled/arrived)")
        return None

    except requests.exceptions.RequestException as e:
        _record_health("aero", False, int((time.time() - t0) * 1000), str(e))
        logging.error(f"AeroAPI Request Error: {e}")
        return None


def fetch_arrivals_data(airport_code: str):
    """
    Fetch scheduled arrivals for an airport via AeroAPI /airports/{id}/flights/scheduled_arrivals.
    Returns a list of flight dicts with callsign, origin, eta, airline_icao, aircraft_type.
    """
    global arrivals_cache

    airport = (airport_code or "").strip().upper()
    if not airport:
        return []

    now = time.time()
    if airport == arrivals_cache["airport"] and now - arrivals_cache["time"] < config.ARRIVALS_POLL_INTERVAL:
        return arrivals_cache["data"]

    if not config.FLIGHTAWARE_API_KEY:
        logging.error("No FlightAware API key configured for arrivals")
        return []

    headers = {"x-apikey": config.FLIGHTAWARE_API_KEY}
    url = f"{AEROAPI_URL}/airports/{airport}/flights/scheduled_arrivals"

    try:
        resp = requests.get(
            url,
            headers=headers,
            params={"type": "Airline", "max_pages": 1},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        raw_arrivals = data.get("scheduled_arrivals", [])

        # Take next ~10 arrivals, normalize to our format
        result = []
        for f in raw_arrivals[:10]:
            ident = (f.get("ident") or "").strip().upper()
            operator_icao = (f.get("operator_icao") or f.get("operator") or ident[:3] or "").strip().upper()[:3]

            origin = f.get("origin") or {}
            dest = f.get("destination") or {}
            orig_iata = (origin.get("code_iata") or origin.get("code_icao") or "").strip().upper()
            if len(orig_iata) > 3:
                orig_iata = orig_iata[:3]
            dest_iata = (dest.get("code_iata") or dest.get("code_icao") or "").strip().upper()
            if len(dest_iata) > 3:
                dest_iata = dest_iata[:3]

            eta_str = f.get("estimated_on") or f.get("scheduled_on") or ""
            eta_display = ""
            if eta_str:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(eta_str.replace("Z", "+00:00"))
                    # Format as "2:45 PM" (strip leading zero from hour)
                    h = dt.hour % 12 or 12
                    m = dt.minute
                    eta_display = f"{h}:{m:02d} {'AM' if dt.hour < 12 else 'PM'}"
                except Exception:
                    eta_display = eta_str[:16] if len(eta_str) > 16 else eta_str

            aircraft = (f.get("aircraft_type") or "").strip().upper()

            result.append({
                "callsign": ident,
                "origin_iata": orig_iata or "???",
                "dest_iata": dest_iata or airport[:3],
                "airline_icao": operator_icao,
                "airline_name": AIRLINE_NAMES.get(operator_icao, ""),
                "aircraft_code": aircraft,
                "eta": eta_display,
                "route": f"{orig_iata} - {dest_iata}" if orig_iata and dest_iata else f"From {orig_iata}",
            })

        arrivals_cache = {"airport": airport, "data": result, "time": now}
        logging.info(f"Arrivals: loaded {len(result)} for {airport}")
        return result

    except requests.exceptions.RequestException as e:
        logging.error(f"AeroAPI Arrivals Error: {e}")
        return arrivals_cache["data"] if arrivals_cache["airport"] == airport else []


def fetch_weather_data():
    """
    Fetch current weather from OpenWeatherMap using HOME_LAT/HOME_LON.
    Returns a normalized dict or None. Caches for WEATHER_POLL_INTERVAL seconds.
    On API error, returns stale cached data rather than None.
    """
    global weather_cache

    now = time.time()
    if weather_cache["data"] is not None and now - weather_cache["time"] < config.WEATHER_POLL_INTERVAL:
        return weather_cache["data"]

    if not config.OPENWEATHER_API_KEY:
        logging.error("No OpenWeatherMap API key configured (OPENWEATHER_API_KEY)")
        return weather_cache["data"]

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "lat": config.HOME_LAT,
        "lon": config.HOME_LON,
        "appid": config.OPENWEATHER_API_KEY,
        "units": "imperial",
    }

    t0 = time.time()
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        raw = resp.json()

        result = {
            "temp_f": round(raw["main"]["temp"]),
            "feels_f": round(raw["main"]["feels_like"]),
            "humidity": raw["main"]["humidity"],
            "wind_mph": round(raw["wind"]["speed"]),
            "wind_deg": raw["wind"].get("deg", 0),
            "condition": raw["weather"][0]["main"],
            "description": raw["weather"][0]["description"],
            "condition_id": raw["weather"][0]["id"],
            "icon_code": raw["weather"][0]["icon"],
            "city": raw.get("name", ""),
            "is_day": raw["weather"][0]["icon"].endswith("d"),
        }

        weather_cache = {"data": result, "time": now}
        _record_health("weather", True, int((time.time() - t0) * 1000))
        logging.info(
            f"Weather: {result['temp_f']}°F, {result['condition']} ({result['description']}), "
            f"wind {result['wind_mph']}mph, humidity {result['humidity']}%"
        )
        return result

    except requests.exceptions.RequestException as e:
        _record_health("weather", False, int((time.time() - t0) * 1000), str(e))
        logging.error(f"OpenWeatherMap Error: {e}")
        return weather_cache["data"]


def _is_valid_commercial(flight):
    """Check if flight has both origin and destination IATA (filters out FRG/local traffic)."""
    orig = getattr(flight, "origin_airport_iata", None)
    dest = getattr(flight, "destination_airport_iata", None)
    if orig in NA_VALUES or dest in NA_VALUES:
        return False
    orig = str(orig).strip().upper() if orig else ""
    dest = str(dest).strip().upper() if dest else ""
    return len(orig) == 3 and len(dest) == 3


def _classify_fr24_object(flight) -> str | None:
    """
    Same as _classify_special_flight but operates on a raw FR24 flight object,
    so we can decide *before* fetching detailed route info. Lets us keep the
    FRG / N/A-route filter for commercial traffic while still surfacing rare
    aircraft that depart from or arrive at FRG.
    """
    if flight is None:
        return None
    callsign = (getattr(flight, "callsign", "") or "").strip().upper()
    aircraft_code = (getattr(flight, "aircraft_code", "") or "").strip().upper()
    return _classify_special_flight({"callsign": callsign, "aircraft_code": aircraft_code})


def fetch_fr24_data():
    """Fetch closest commercial flight within 10km of Farmingdale using FlightRadar24."""
    if not FR24_AVAILABLE or not fr_api:
        logging.error("FlightRadar24API not available")
        return None

    t0 = time.time()
    try:
        # 10-mile radius around home (~16093m)
        bounds = fr_api.get_bounds_by_point(
            config.HOME_LAT, config.HOME_LON, 16093
        )
        flights = fr_api.get_flights(bounds=bounds)

        # Filter:
        #   - Commercial flights need both origin+dest IATA AND altitude >= 2500 ft
        #     (drops FRG/local GA noise).
        #   - Special flights (fighters/warbirds/rare/military) bypass the IATA
        #     requirement and use a lower 500-ft floor so we still catch them
        #     departing or arriving at FRG, KFRG pattern work, low passes, etc.
        qualified = []
        for f in flights or []:
            alt = getattr(f, "altitude", None)
            if alt is None or not isinstance(alt, (int, float)):
                continue
            special_reason = _classify_fr24_object(f)
            if special_reason:
                if alt < 500:
                    continue
            else:
                if not _is_valid_commercial(f):
                    continue
                if alt < 2500:
                    continue
            qualified.append(f)

        if not qualified:
            _record_health("fr24", True, int((time.time() - t0) * 1000))
            return None

        # Pick closest to HOME (Entity.get_distance_from needs lat/lon attributes)
        from types import SimpleNamespace
        home_pos = SimpleNamespace(latitude=config.HOME_LAT, longitude=config.HOME_LON)
        closest = min(qualified, key=lambda f: f.get_distance_from(home_pos))
        distance_km = round(closest.get_distance_from(home_pos), 1)

        # Get route details (can timeout or return incomplete JSON)
        orig = str(closest.origin_airport_iata or "").strip().upper()
        dest = str(closest.destination_airport_iata or "").strip().upper()
        route = f"{orig} - {dest}" if orig and dest else ""

        aircraft_model = None
        orig_name = ""
        dest_name = ""
        try:
            details = fr_api.get_flight_details(closest)
            if details and isinstance(details, dict):
                closest.set_flight_details(details)
                aircraft_model = getattr(closest, "aircraft_model", None)
                if aircraft_model in NA_VALUES:
                    aircraft_model = None
                
                # Extract airport names
                airport_info = details.get("airport", {})
                if airport_info:
                    orig_info = airport_info.get("origin") or {}
                    dest_info = airport_info.get("destination") or {}
                    orig_name = (orig_info.get("name") or "").strip()
                    dest_name = (dest_info.get("name") or "").strip()
        except Exception as e:
            logging.warning(f"get_flight_details timeout/incomplete for {closest.callsign}: {e}")
            # Continue with basic data - we have route from list response

        alt = closest.altitude
        spd = closest.ground_speed
        if alt is None:
            alt = 0
        if spd is None:
            spd = 0

        aircraft_code = (getattr(closest, "aircraft_code", None) or "").strip().upper()

        airline_icao = (closest.airline_icao or "").strip().upper()[:3] if closest.airline_icao else ""

        _record_health("fr24", True, int((time.time() - t0) * 1000))
        return {
            "callsign": (closest.callsign or "").strip().upper(),
            "altitude": int(alt),
            "speed": int(spd),
            "route": route,
            "origin_iata": orig,
            "dest_iata": dest,
            "origin_name": orig_name,
            "dest_name": dest_name,
            "airline_icao": airline_icao,
            "airline_name": AIRLINE_NAMES.get(airline_icao, ""),
            "aircraft_model": aircraft_model or aircraft_code,  # full name for web UI
            "aircraft_code": aircraft_code,  # short ICAO type for matrix (e.g. "A321")
            "heading": int(getattr(closest, "heading", 0) or 0) % 360,
            "vertical_speed": int(getattr(closest, "vertical_speed", 0) or 0),
            "distance_km": distance_km,
        }

    except Exception as e:
        _record_health("fr24", False, int((time.time() - t0) * 1000), str(e))
        logging.error(f"FlightRadar24 API Error: {e}")
        return None

def _format_alt_speed(alt, spd):
    """Build compact altitude/speed variants from verbose to minimal."""
    alt_str = f"{alt // 1000}k" if alt >= 1000 else str(alt)
    spd_mph = int(round((spd or 0) * 1.15078))
    return [
        f"Alt{alt_str} Spd{spd_mph}mph",
        f"Alt{alt_str} Spd{spd_mph}",
        f"Alt{alt_str} Sp{spd_mph}",
        f"A{alt_str} S{spd_mph}",
        f"{alt_str} {spd_mph}",
    ]

def _format_altitude(alt):
    """Compact altitude for matrix row: '32kft' or '800ft'."""
    if alt >= 1000:
        return f"{alt // 1000}kft"
    return f"{alt}ft"


def _find_logo_path(icao_code):
    """Resolve airline logo path (check logo/ and logo2/ subdirs)."""
    logos_dir = os.path.join(BASE_DIR, "assets", "logos")
    for subdir in ("logo", "logo2", ""):
        path = os.path.join(logos_dir, subdir, f"{icao_code}.png") if subdir else os.path.join(logos_dir, f"{icao_code}.png")
        if os.path.exists(path):
            return path
    return None



def _draw_sharp(image: Image.Image, xy, text: str, font, color: tuple):
    """Render text with no anti-aliasing by thresholding the alpha channel."""
    if not text:
        return
    tmp = Image.new("RGBA", image.size, (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp)
    tmp_draw.text(xy, text, font=font, fill=(*color, 255))
    _, _, _, a = tmp.split()
    a = a.point(lambda p: 255 if p > 127 else 0)
    color_layer = Image.new("RGB", image.size, color)
    image.paste(color_layer, mask=a)


def _square_crop(img: Image.Image) -> Image.Image:
    """Center-crop image to a square."""
    w, h = img.size
    s = min(w, h)
    left = (w - s) // 2
    top = (h - s) // 2
    return img.crop((left, top, left + s, top + s))


def _draw_arrow_prefix(image: Image.Image, x: int, y: int, arrow_up: bool, color: tuple):
    """Draw a 5×6 pixel up or down arrow at (x, y). Arrow occupies columns x..x+4."""
    draw = ImageDraw.Draw(image)
    cx = x + 2  # center column
    if arrow_up:
        draw.point((cx,     y),     fill=color)
        draw.point((cx - 1, y + 1), fill=color)
        draw.point((cx,     y + 1), fill=color)
        draw.point((cx + 1, y + 1), fill=color)
        for dx in range(-2, 3):
            draw.point((cx + dx, y + 2), fill=color)
        draw.point((cx, y + 3), fill=color)
        draw.point((cx, y + 4), fill=color)
        draw.point((cx, y + 5), fill=color)
    else:
        draw.point((cx, y),     fill=color)
        draw.point((cx, y + 1), fill=color)
        draw.point((cx, y + 2), fill=color)
        for dx in range(-2, 3):
            draw.point((cx + dx, y + 3), fill=color)
        draw.point((cx - 1, y + 4), fill=color)
        draw.point((cx,     y + 4), fill=color)
        draw.point((cx + 1, y + 4), fill=color)
        draw.point((cx,     y + 5), fill=color)


def _build_heatmap_image(current_time: float) -> Image.Image:
    """
    64×32 LED heatmap of the last 7 days of flights.
    Layout:
      y=0..6:  thin header ("AIR HEAT 7D" + tiny pulse)
      y=7..30: density grid (24 hour columns × 24 altitude bands → resampled to 60×24 area).
              Top rows = high altitude, bottom rows = low altitude.
      x=0..3:  reserved for altitude axis labels (faint).
    Colors fade from cool (few) to hot (many).
    """
    image = Image.new("RGB", (64, 32), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Header
    pulse = 0.55 + 0.45 * abs(math.sin(2 * math.pi * current_time / 4.0))
    header_color = (int(80 * pulse), int(220 * pulse), int(255 * pulse))
    _draw_sharp(image, (1, 0), "AIR HEAT 7D", FONT_THUMB, header_color)

    try:
        grid = db.get_heatmap_grid(width=60, height=24, days=7)
    except Exception as e:
        logging.warning(f"heatmap grid query failed: {e}")
        _draw_sharp(image, (8, 14), "NO DATA", FONT_5X8, (120, 120, 120))
        return image

    # Find max for normalization
    max_val = 0
    for row in grid:
        for v in row:
            if v > max_val:
                max_val = v

    if max_val <= 0:
        _draw_sharp(image, (8, 14), "NO DATA", FONT_5X8, (120, 120, 120))
        # subtle axis ticks
        for y in range(7, 31, 4):
            draw.point((0, y), fill=(40, 40, 40))
        return image

    # Render grid into rows 7..30 (24 rows tall), columns 4..63 (60 wide)
    grid_top = 7
    grid_left = 4
    for y, row in enumerate(grid):
        for x, v in enumerate(row):
            if v <= 0:
                continue
            ratio = v / max_val
            # Cool→Hot palette: dark blue → cyan → yellow → red
            if ratio < 0.25:
                t = ratio / 0.25
                color = (
                    int(20 * (1 - t) + 0 * t),
                    int(40 * (1 - t) + 180 * t),
                    int(120 * (1 - t) + 255 * t),
                )
            elif ratio < 0.55:
                t = (ratio - 0.25) / 0.30
                color = (
                    int(0 * (1 - t) + 255 * t),
                    int(180 * (1 - t) + 220 * t),
                    int(255 * (1 - t) + 60 * t),
                )
            elif ratio < 0.85:
                t = (ratio - 0.55) / 0.30
                color = (
                    int(255 * (1 - t) + 255 * t),
                    int(220 * (1 - t) + 120 * t),
                    int(60 * (1 - t) + 0 * t),
                )
            else:
                t = (ratio - 0.85) / 0.15
                color = (
                    255,
                    int(120 * (1 - t) + 30 * t),
                    int(0 * (1 - t) + 30 * t),
                )
            draw.point((grid_left + x, grid_top + y), fill=color)

    # Faint altitude tick on left (y=7 high, y=30 low)
    draw.point((0, grid_top), fill=(40, 80, 120))
    draw.point((0, grid_top + 11), fill=(40, 80, 120))
    draw.point((0, 30), fill=(40, 80, 120))

    return image


# --- Special-flight alerts --------------------------------------------------

# Recently-alerted callsigns: callsign -> {"first": time, "until": time, "reason": str}
special_alert_state = {
    "active": {},     # currently flashing
    "seen": {},       # debounce: callsign -> last alert timestamp
}


def _classify_special_flight(flight_data) -> str | None:
    """
    Return a short human reason if the flight is genuinely special, else None.
    Reasons: "favorite", "vip", "military", "fighter", "warbird", "rare-aircraft".
    Common widebodies (777/787/A350) are intentionally not flagged.
    """
    if not flight_data:
        return None
    callsign = (flight_data.get("callsign") or "").strip().upper()
    aircraft_code = (flight_data.get("aircraft_code") or "").strip().upper()

    if callsign and callsign in config.FAVORITE_CALLSIGNS:
        return "favorite"

    # VIP callsigns beat everything else
    if callsign:
        for prefix in ("AF1", "AF2", "SAM"):
            if callsign.startswith(prefix):
                return "vip"

    # Aircraft-type tags (fighter / warbird / rare) are more specific than a
    # generic "military" callsign prefix, so they take priority.
    if aircraft_code:
        if aircraft_code in config.FIGHTER_AIRCRAFT_CODES:
            return "fighter"
        if aircraft_code in config.WARBIRD_AIRCRAFT_CODES:
            return "warbird"
        if aircraft_code in config.RARE_AIRCRAFT_CODES:
            return "rare-aircraft"

    if callsign:
        for prefix in config.SPECIAL_CALLSIGN_PREFIXES:
            if prefix and callsign.startswith(prefix):
                return "military"

    return None


def _record_special_alert_once(flight_data, reason: str) -> bool:
    """
    Trigger an alert for this flight if we haven't recently. Returns True if newly triggered.
    Debounced by callsign for 1 hour.
    """
    callsign = (flight_data.get("callsign") or "").strip().upper()
    if not callsign:
        return False

    now = time.time()
    last = special_alert_state["seen"].get(callsign, 0)
    if now - last < 3600:
        return False
    special_alert_state["seen"][callsign] = now
    special_alert_state["active"][callsign] = {
        "first": now,
        "until": now + max(2, config.SPECIAL_ALERT_DURATION),
        "reason": reason,
        "flight": dict(flight_data),
    }
    try:
        db.record_special_alert(flight_data, reason)
    except Exception as e:
        logging.warning(f"DB special alert write failed: {e}")
    return True


def _purge_expired_alerts():
    now = time.time()
    expired = [k for k, v in special_alert_state["active"].items() if v.get("until", 0) <= now]
    for k in expired:
        special_alert_state["active"].pop(k, None)


def _active_alert():
    """Return the highest-priority currently-active alert dict, or None."""
    _purge_expired_alerts()
    if not special_alert_state["active"]:
        return None
    # Newest first
    return max(
        special_alert_state["active"].values(),
        key=lambda a: a.get("first", 0),
    )


def _build_alert_overlay(image: Image.Image, alert: dict, current_time: float) -> Image.Image:
    """Overlay a flashing border + 'SPECIAL' tag on top of the given matrix image."""
    if not alert:
        return image
    # 2 Hz strobe
    on = (int(current_time * 2)) % 2 == 0
    if not on:
        return image

    reason = alert.get("reason", "")
    palette = {
        "favorite":      (255,  60, 220),
        "vip":           (255, 220,   0),
        "military":      ( 60, 200,  80),
        "fighter":       (255,  60,  60),
        "warbird":       (200, 140,  60),
        "rare-aircraft": ( 80, 220, 255),
    }
    color = palette.get(reason, (255, 80, 80))

    draw = ImageDraw.Draw(image)
    # Border
    draw.rectangle([0, 0, 63, 31], outline=color, width=1)
    return image


# --- Discord ---------------------------------------------------------------

discord_state = {
    "last_summary_day": "",  # ISO date of last daily summary post
}


def _discord_post(content: str, embeds: list | None = None) -> bool:
    """Post a message to the configured Discord webhook. Returns True on success."""
    if not config.DISCORD_WEBHOOK_URL:
        return False
    payload = {"content": content[:1900], "username": "Ribs FlightWall"}
    if embeds:
        payload["embeds"] = embeds
    try:
        resp = requests.post(config.DISCORD_WEBHOOK_URL, json=payload, timeout=8)
        if resp.status_code >= 400:
            logging.warning(f"Discord webhook {resp.status_code}: {resp.text[:200]}")
            return False
        return True
    except requests.RequestException as e:
        logging.warning(f"Discord webhook failed: {e}")
        return False


def _format_special_alert_for_discord(alert: dict) -> tuple[str, list]:
    f = alert.get("flight") or {}
    callsign = f.get("callsign") or "?"
    reason = alert.get("reason", "")
    pretty_reason = {
        "favorite":      "⭐ Favorite",
        "vip":           "🎩 VIP",
        "military":      "🪖 Military",
        "fighter":       "🛩️ Fighter jet",
        "warbird":       "🏛️ Warbird",
        "rare-aircraft": "✨ Rare aircraft",
    }.get(reason, reason)
    title = f"Special flight overhead — {pretty_reason}"
    desc = f"**{callsign}**"
    aircraft = f.get("aircraft_model") or f.get("aircraft_code")
    if aircraft:
        desc += f" • {aircraft}"
    if f.get("route"):
        desc += f"\nRoute: `{f['route']}`"
    if f.get("altitude") is not None:
        alt = f["altitude"]
        desc += f"\nAlt: {alt//1000}k ft" if alt >= 1000 else f"\nAlt: {alt} ft"
    return title, [{"title": title, "description": desc, "color": 0x4CC2FF}]


def _post_daily_summary_if_due():
    """If we're past DISCORD_DAILY_SUMMARY_HOUR and haven't posted today, post and remember."""
    if not (config.DISCORD_WEBHOOK_URL and config.DISCORD_DAILY_SUMMARY):
        return
    now = time.localtime()
    today = time.strftime("%Y-%m-%d", now)
    if discord_state["last_summary_day"] == today:
        return
    if now.tm_hour < config.DISCORD_DAILY_SUMMARY_HOUR:
        return
    try:
        stats = db.get_stats(period="day")
    except Exception as e:
        logging.warning(f"daily summary: stats query failed: {e}")
        return
    total = stats.get("total_flights", 0)
    top_airline = (stats.get("top_airlines") or [{}])[0]
    top_aircraft = (stats.get("top_aircraft") or [{}])[0]
    busiest = stats.get("busiest_hour")
    high = stats.get("highest_flight") or {}
    low = stats.get("lowest_flight") or {}

    lines = [f"**Daily Airspace Summary — {today}**", f"✈️ {total} flights overhead today."]
    if top_airline.get("airline_name"):
        lines.append(f"• Most common airline: **{top_airline['airline_name']}** ({top_airline.get('count', 0)})")
    if top_aircraft.get("aircraft_model"):
        lines.append(f"• Most common aircraft: **{top_aircraft['aircraft_model']}** ({top_aircraft.get('count', 0)})")
    if busiest is not None:
        h12 = busiest % 12 or 12
        ampm = "AM" if busiest < 12 else "PM"
        lines.append(f"• Busiest hour: {h12}:00 {ampm} ({stats.get('busiest_count', 0)} flights)")
    if low.get("altitude"):
        lines.append(f"• Lowest: {low['callsign']} @ {low['altitude']} ft")
    if high.get("altitude"):
        lines.append(f"• Highest: {high['callsign']} @ {high['altitude']} ft")
    if total == 0:
        lines.append("(Quiet day — nothing recorded.)")

    if _discord_post("\n".join(lines)):
        discord_state["last_summary_day"] = today


# --- Health metrics --------------------------------------------------------

health_state = {
    "fr24":    {"last_ok": 0.0, "last_err": "", "calls": 0, "errors": 0, "last_latency_ms": 0},
    "aero":    {"last_ok": 0.0, "last_err": "", "calls": 0, "errors": 0, "last_latency_ms": 0},
    "weather": {"last_ok": 0.0, "last_err": "", "calls": 0, "errors": 0, "last_latency_ms": 0},
    "logodev": {"last_ok": 0.0, "last_err": "", "calls": 0, "errors": 0, "last_latency_ms": 0},
    "started_at": time.time(),
    "aero_calls_today": {"day": "", "count": 0},  # daily AeroAPI cost tracker
}


def _record_health(source: str, ok: bool, latency_ms: int = 0, err: str = ""):
    s = health_state.get(source)
    if s is None:
        return
    s["calls"] += 1
    s["last_latency_ms"] = latency_ms
    if ok:
        s["last_ok"] = time.time()
        s["last_err"] = ""
    else:
        s["errors"] += 1
        s["last_err"] = (err or "")[:200]


def _bump_aero_call_counter():
    """AeroAPI is billed per request; track daily count for the health page."""
    today = time.strftime("%Y-%m-%d")
    s = health_state["aero_calls_today"]
    if s["day"] != today:
        s["day"] = today
        s["count"] = 0
    s["count"] += 1


# --- .env editor ------------------------------------------------------------

ENV_PATH = os.path.join(BASE_DIR, ".env")
# Whitelist of keys editable from the OTA settings page. NEVER expose API keys with credentials in raw form.
ENV_EDITABLE_KEYS = [
    "HOME_LAT",
    "HOME_LON",
    "MATRIX_BRIGHTNESS",
    "FR24_POLL_INTERVAL",
    "MONITOR_POLL_INTERVAL",
    "ARRIVALS_POLL_INTERVAL",
    "WEATHER_POLL_INTERVAL",
    "FAVORITE_CALLSIGNS",
    "SPECIAL_AIRCRAFT_CODES",
    "SPECIAL_CALLSIGN_PREFIXES",
    "SPECIAL_ALERT_DURATION",
    "DISCORD_WEBHOOK_URL",
    "DISCORD_DAILY_SUMMARY",
    "DISCORD_DAILY_SUMMARY_HOUR",
    "DISCORD_ALERT_SPECIAL",
    "FLIGHTAWARE_API_KEY",
    "OPENWEATHER_API_KEY",
    "LOGO_DEV_TOKEN",
]
ENV_SECRET_KEYS = {"FLIGHTAWARE_API_KEY", "OPENWEATHER_API_KEY", "LOGO_DEV_TOKEN", "DISCORD_WEBHOOK_URL"}


def _read_env_file() -> dict:
    """Parse .env into {KEY: value}. Tolerant of comments / blank lines."""
    out = {}
    if not os.path.exists(ENV_PATH):
        return out
    try:
        with open(ENV_PATH, "r") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                out[k] = v
    except OSError as e:
        logging.warning(f"read .env failed: {e}")
    return out


def _write_env_file(updates: dict) -> None:
    """
    Merge `updates` into .env, preserving comments and unknown keys. Only keys in
    ENV_EDITABLE_KEYS are accepted; anything else is silently dropped.
    """
    safe = {k: ("" if v is None else str(v)) for k, v in updates.items() if k in ENV_EDITABLE_KEYS}
    existing_lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            existing_lines = f.readlines()
    seen = set()
    new_lines = []
    for raw in existing_lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        k, _, _ = stripped.partition("=")
        k = k.strip()
        if k in safe:
            new_lines.append(f"{k}={safe[k]}")
            seen.add(k)
        else:
            new_lines.append(line)
    for k, v in safe.items():
        if k not in seen:
            new_lines.append(f"{k}={v}")
    with open(ENV_PATH, "w") as f:
        f.write("\n".join(new_lines).rstrip() + "\n")


def _build_flight_image(flight_data, current_time: float, mode_hint: str = "") -> Image.Image:
    """Pixel-perfect 64x32 layout: logo left (0-16) | 4 lines text right (x=19+), FONT_5X8."""
    image = Image.new("RGB", (64, 32), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    if not flight_data:
        time_str = time.strftime("%I:%M %p").lstrip("0")

        temp_img = Image.new("RGB", (1, 1))
        temp_draw = ImageDraw.Draw(temp_img)
        w = temp_draw.textlength(time_str, font=FONT_6X10)

        x = max(0, (64 - int(w)) // 2)
        draw.text((x, 4), time_str, font=FONT_6X10, fill=(100, 100, 100))

        if mode_hint == "radius":
            hint = "SCANNING"
        elif mode_hint == "monitor":
            hint = "WAITING"
        else:
            hint = ""
        if hint:
            hw = int(ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(hint, font=FONT_THUMB))
            _draw_sharp(image, ((64 - hw) // 2, 24), hint, FONT_THUMB, (60, 60, 60))
        return image

    callsign      = (flight_data.get("callsign") or "").strip().upper()
    
    # Show airline name only, fall back to raw callsign if name unavailable
    icao_code = (flight_data.get("airline_icao") or callsign[:3] or "").upper()[:3]
    airline_name = flight_data.get("airline_name") or AIRLINE_NAMES.get(icao_code, "")
    display_callsign = airline_name or callsign

    origin        = (flight_data.get("origin_iata") or flight_data.get("origin") or "").strip().upper() or "N/A"
    dest          = (flight_data.get("dest_iata") or flight_data.get("destination") or "").strip().upper() or "N/A"
    alt           = flight_data.get("altitude", 0) or 0
    spd           = flight_data.get("speed", 0) or 0
    alt_k          = f"{alt // 1000}k" if alt >= 1000 else str(alt)
    spd_mph        = int(round((spd or 0) * 1.15078))
    aircraft_code  = (flight_data.get("aircraft_code") or "").strip().upper()
    aircraft_model = (flight_data.get("aircraft_model") or "").strip()
    heading        = flight_data.get("heading", 0) or 0
    vertical_speed = flight_data.get("vertical_speed", 0) or 0
    distance_km    = flight_data.get("distance_km", None)

    # --- Right zone text: 4 lines (FONT_5X8 5x8), single cycling line ---
    TEXT_X = 19
    TEXT_W = 64 - TEXT_X  # 45px

    # Line 1 (y=0): Airline Name + Flight Number (Yellow)
    _draw_scrolling_text(image, display_callsign, FONT_5X8, (255, 220, 0), TEXT_X, 0, TEXT_W, current_time)

    # Line 2 (y=8): Route (Cyan) - always static
    route_text = f"{origin} - {dest}"
    _draw_scrolling_text(image, route_text, FONT_5X8, (0, 220, 255), TEXT_X, 8, TEXT_W, current_time % 8.0)

    # Line 3 (y=16): Altitude left (climb color), Speed right (yellow) — fixed, no scrolling
    if vertical_speed > 200:
        alt_color = (0, 255, 100)    # climbing: bright green
    elif vertical_speed < -200:
        alt_color = (255, 100, 0)    # descending: orange-red
    else:
        alt_color = (0, 220, 0)      # level: steady green
    spd_text = f"{spd_mph}m"
    spd_w = int(draw.textlength(spd_text, font=FONT_5X8))
    _draw_sharp(image, (TEXT_X, 16), alt_k, FONT_5X8, alt_color)
    _draw_sharp(image, (63 - spd_w, 16), spd_text, FONT_5X8, (255, 220, 0))
    alt_spd_text = f"{alt_k} {spd_mph}m"  # kept for line 4 fallback

    # Line 4 (y=19): Single cycling line - Aircraft code vs From/To airport name
    origin_name_raw = flight_data.get("origin_name", "") or AIRPORT_NAMES.get(origin, "")
    dest_name_raw = flight_data.get("dest_name", "") or AIRPORT_NAMES.get(dest, "")
    origin_name = _shorten_airport_name(origin_name_raw)
    dest_name = _shorten_airport_name(dest_name_raw)
    dest_nearby = dest in NEARBY_AIRPORTS
    origin_nearby = origin in NEARBY_AIRPORTS

    name_arrow_up = True  # True = up arrow ("To"), False = down arrow ("From")
    if dest_nearby and not origin_nearby and origin_name:
        name_line = origin_name
        name_arrow_up = False
    elif origin_nearby and not dest_nearby and dest_name:
        name_line = dest_name
        name_arrow_up = True
    elif (dest_nearby and origin_nearby) or (not origin_name and not dest_name):
        name_line = ""
    else:
        name_line = dest_name if dest_name else ""

    cycle = int(current_time / 12.0) % 2
    local_time_4 = current_time % 12.0
    aircraft_display = AIRCRAFT_NAMES.get(aircraft_code) or aircraft_code
    if cycle == 0:
        # Aircraft name (Magenta) or alt/speed fallback
        if aircraft_display:
            _draw_scrolling_text(image, aircraft_display, FONT_5X8, (255, 0, 255), TEXT_X, 24, TEXT_W, local_time_4)
        else:
            _draw_scrolling_text(image, alt_spd_text, FONT_5X8, (0, 220, 0), TEXT_X, 24, TEXT_W, local_time_4)
    else:
        # Airport name (Cyan) with arrow prefix, or aircraft/alt fallback
        if name_line:
            _draw_arrow_prefix(image, TEXT_X, 24, name_arrow_up, (0, 220, 255))
            _draw_scrolling_text(image, name_line, FONT_5X8, (0, 220, 255), TEXT_X + 7, 24, TEXT_W - 7, local_time_4)
        elif aircraft_display:
            _draw_scrolling_text(image, aircraft_display, FONT_5X8, (255, 0, 255), TEXT_X, 24, TEXT_W, local_time_4)
        else:
            _draw_scrolling_text(image, alt_spd_text, FONT_5X8, (0, 220, 0), TEXT_X, 24, TEXT_W, local_time_4)

    # --- Left zone: airline logo (0-16), vertically centered at y=8 ---
    icao_code = (flight_data.get("airline_icao") or callsign[:3] or "").upper()[:3]
    logo_img = None
    if icao_code:
        logo_path = _find_logo_path(icao_code)
        if logo_path:
            try:
                logo_img = Image.open(logo_path).convert("RGBA")
            except Exception as e:
                logging.error(f"Error loading logo {logo_path}: {e}")
        if logo_img is None:
            logo_bytes = _fetch_logo_dev_bytes(icao_code)
            if logo_bytes:
                try:
                    logo_img = Image.open(BytesIO(logo_bytes)).convert("RGBA")
                except Exception as e:
                    logging.warning(f"logo.dev decode failed for {icao_code}: {e}")

    if logo_img is not None:
        # Resize so longest side = 16, preserve aspect ratio, no blur
        lw, lh = logo_img.size
        if lw >= lh:
            new_w, new_h = 16, max(1, round(lh * 16 / lw))
        else:
            new_w, new_h = max(1, round(lw * 16 / lh)), 16
        logo_img = logo_img.resize((new_w, new_h), Image.Resampling.NEAREST)

        # Center in a 16x16 RGBA container
        centered = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        paste_x = (16 - new_w) // 2
        paste_y = (16 - new_h) // 2
        centered.paste(logo_img, (paste_x, paste_y), logo_img)

        # Paste onto canvas at (0, 8) using alpha as mask
        image.paste(centered, (0, 8), centered)

    # --- Cardinal direction: bottom-left dead zone (y=25) ---
    _CARDINALS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    cardinal = _CARDINALS[int((heading + 22.5) / 45) % 8]
    _draw_sharp(image, (1, 25), cardinal, FONT_THUMB, (0, 180, 200))

    return image


def _build_arrivals_image(arrivals: list, airport_code: str, current_time: float) -> Image.Image:
    """
    Build a retro arrivals-board style 64x32 image.
    Cycles through arrivals, showing one flight at a time. Header: "{AIRPORT} ARRIVALS"
    """
    image = Image.new("RGB", (64, 32), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    airport = (airport_code or "").strip().upper()[:3]
    if not airport:
        # Fallback: clock
        time_str = time.strftime("%I:%M %p").lstrip("0")
        draw.text((16, 10), time_str, font=FONT_6X10, fill=(100, 100, 100))
        return image

    if not arrivals:
        header = f"{airport} ARR"
        _draw_scrolling_text(image, header, FONT_6X10, (255, 220, 0), 0, 2, 64, current_time)
        draw.text((4, 14), "No arrivals", font=FONT_5X8, fill=(100, 100, 100))
        return image

    # Cycle through flights every 6 seconds
    cycle_sec = 6.0
    idx = int(current_time / cycle_sec) % len(arrivals)
    flight = arrivals[idx]

    callsign = (flight.get("callsign") or "").strip().upper()
    origin = (flight.get("origin_iata") or "???").strip().upper()
    eta = (flight.get("eta") or "").strip()
    airline_icao = (flight.get("airline_icao") or "").strip().upper()[:3]

    # Line 0: Header "{AIRPORT} ARRIVALS" (scrolling if needed)
    header = f"{airport} ARRIVALS"
    _draw_scrolling_text(image, header, FONT_5X8, (255, 220, 0), 0, 1, 64, current_time)

    # Line 1: Flight + origin (e.g. "AAL1695  PHL")
    row1 = f"{callsign}  {origin}"
    _draw_scrolling_text(image, row1, FONT_5X8, (0, 220, 255), 0, 11, 64, current_time)

    # Line 2: ETA (e.g. "ETA 2:45 PM")
    row2 = f"ETA {eta}" if eta else ""
    _draw_scrolling_text(image, row2, FONT_5X8, (0, 220, 0), 0, 21, 64, current_time)

    # Optional: small airline logo on the left (8x8 area) if we have space
    if airline_icao:
        logo_bytes = _fetch_logo_dev_bytes(airline_icao)
        if logo_bytes:
            try:
                logo_img = Image.open(BytesIO(logo_bytes)).convert("RGBA")
                lw, lh = logo_img.size
                scale = min(8.0 / lw, 8.0 / lh, 1.0)
                nw, nh = max(1, int(lw * scale)), max(1, int(lh * scale))
                logo_img = logo_img.resize((nw, nh), Image.Resampling.NEAREST)
                centered = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
                px, py = (8 - nw) // 2, (8 - nh) // 2
                centered.paste(logo_img, (px, py), logo_img)
                image.paste(centered, (56, 12), centered)
            except Exception:
                pass

    return image


def _build_text_image(message: str, color_hex: str, current_time: float) -> Image.Image:
    """
    Build a 64x32 image showing the user's custom text, vertically centered.
    Short text is centered; long text scrolls across the full width.
    """
    image = Image.new("RGB", (64, 32), (0, 0, 0))

    if not message:
        time_str = time.strftime("%I:%M %p").lstrip("0")
        draw = ImageDraw.Draw(image)
        temp_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        w = int(temp_draw.textlength(time_str, font=FONT_6X10))
        x = max(0, (64 - w) // 2)
        y = (32 - 10) // 2
        draw.text((x, y), time_str, font=FONT_6X10, fill=(100, 100, 100))
        return image

    try:
        h = color_hex.lstrip("#")
        color = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        color = (0, 220, 0)

    font = FONT_6X10
    temp_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    text_w = int(temp_draw.textlength(message, font=font))
    y = (32 - 10) // 2  # vertically centered for 10px-tall font

    if text_w <= 64:
        draw = ImageDraw.Draw(image)
        x = (64 - text_w) // 2
        draw.text((x, y), message, font=font, fill=color)
    else:
        _draw_scrolling_text(image, message, font, color, 0, y, 64, current_time)

    return image


def _temp_color(temp_f: int, condition_id: int) -> tuple:
    """Map temperature + condition code to a dominant LED RGB color."""
    if temp_f <= 20:
        base = (30, 100, 220)
    elif temp_f <= 35:
        base = (60, 160, 230)
    elif temp_f <= 50:
        base = (80, 200, 200)
    elif temp_f <= 65:
        base = (100, 220, 120)
    elif temp_f <= 75:
        base = (200, 230, 80)
    elif temp_f <= 85:
        base = (255, 200, 0)
    elif temp_f <= 95:
        base = (255, 140, 0)
    else:
        base = (255, 60, 0)

    if 200 <= condition_id <= 232:   # Thunderstorm → magenta shift
        return (min(255, base[0] + 60), max(0, base[1] - 60), min(255, base[2] + 80))
    elif 300 <= condition_id <= 531:  # Rain/Drizzle → blue shift
        return (max(0, base[0] - 40), max(0, base[1] - 20), min(255, base[2] + 60))
    elif 600 <= condition_id <= 622:  # Snow → icy white-blue
        return (160, 200, 255)
    elif 700 <= condition_id <= 781:  # Fog/Haze/Mist → gray
        return (140, 150, 160)
    return base


def _wind_cardinal(deg: int) -> str:
    """Convert wind degrees to a 1-2 char cardinal direction string."""
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[int((deg + 22.5) / 45) % 8]


def _draw_weather_icon(draw: ImageDraw.ImageDraw, ox: int, oy: int, condition_id: int, is_day: bool):
    """
    Draw a 10×10 pixel-art weather icon at image position (ox, oy).
    Covers ox..ox+9, oy..oy+9.
    """
    SUN  = (255, 210,   0)
    MOON = (180, 195, 215)
    CLD  = (150, 155, 165)
    RAIN = ( 70, 130, 220)
    SNOW = (190, 215, 255)
    BOLT = (255, 235,   0)

    cx = ox + 4
    cy = oy + 4

    def sun():
        draw.ellipse([cx-2, cy-2, cx+2, cy+2], fill=SUN)
        for dx, dy in [(0,-4),(0,4),(-4,0),(4,0),(-3,-3),(3,-3),(-3,3),(3,3)]:
            draw.point((cx+dx, cy+dy), fill=SUN)

    def moon():
        draw.ellipse([cx-3, cy-3, cx+3, cy+3], fill=MOON)
        draw.ellipse([cx-1, cy-4, cx+4, cy+2], fill=(0, 0, 0))  # carve crescent

    def cloud(x, y, color=CLD):
        # Top center at (x, y); spans ~9px wide × 7px tall
        draw.ellipse([x-4, y+2, x+0, y+6], fill=color)   # left lobe
        draw.ellipse([x-2, y+0, x+2, y+4], fill=color)   # center bump
        draw.ellipse([x+0, y+2, x+4, y+6], fill=color)   # right lobe
        draw.rectangle([x-4, y+4, x+4, y+6], fill=color) # fill base

    if 200 <= condition_id <= 232:          # Thunderstorm
        cloud(cx, oy)
        draw.line([(cx, oy+7), (cx-1, oy+8)], fill=BOLT)
        draw.line([(cx-1, oy+8), (cx, oy+8)], fill=BOLT)
        draw.line([(cx, oy+8), (cx-1, oy+9)], fill=BOLT)
    elif 300 <= condition_id <= 531:        # Rain / Drizzle
        cloud(cx, oy)
        for dx in (-2, 0, 2):
            draw.point((cx+dx,   oy+7), fill=RAIN)
            draw.point((cx+dx+1, oy+8), fill=RAIN)
    elif 600 <= condition_id <= 622:        # Snow
        cloud(cx, oy)
        for dx in (-2, 0, 2):
            draw.point((cx+dx, oy+7), fill=SNOW)
            draw.point((cx+dx, oy+9), fill=SNOW)
    elif 700 <= condition_id <= 781:        # Fog / Mist / Haze
        for dy in (1, 4, 7):
            draw.line([(cx-4, oy+dy), (cx+4, oy+dy)], fill=CLD)
    elif condition_id == 800:               # Clear sky
        sun() if is_day else moon()
    elif condition_id == 801:               # Few clouds (sun peeking)
        if is_day:
            draw.ellipse([cx-4, cy-4, cx-1, cy-1], fill=SUN)
        cloud(cx+1, oy, color=(145, 150, 160))
    else:                                   # 802-804 Cloudy / Overcast
        cloud(cx-1, oy,   color=(120, 125, 135))
        cloud(cx+1, oy+2, color=(95, 100, 110))


def _build_weather_image(weather: dict, current_time: float) -> Image.Image:
    """
    Build a 64x32 weather display image.

    Layout:
      x=0-1 : animated breathing stripe (theme color, sine pulse)
      y=1-10: temperature — FONT_6X10, centered, shimmering theme color
      y=13-20: condition description — FONT_5X8, scrolling, lightened theme color
      y=23-30: humidity (left, FONT_THUMB label + FONT_5X8 value)
               wind (right-aligned, FONT_5X8, speed-coded color)
    """
    image = Image.new("RGB", (64, 32), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    if not weather:
        time_str = time.strftime("%I:%M %p").lstrip("0")
        w = int(draw.textlength(time_str, font=FONT_6X10))
        draw.text(((64 - w) // 2, 11), time_str, font=FONT_6X10, fill=(100, 100, 100))
        _draw_sharp(image, (18, 24), "WEATHER", FONT_THUMB, (50, 50, 50))
        return image

    temp_f = weather.get("temp_f", 0)
    humidity = weather.get("humidity", 0)
    wind_mph = weather.get("wind_mph", 0)
    wind_deg = weather.get("wind_deg", 0)
    condition_id = weather.get("condition_id", 800)
    description = weather.get("description", "").title()
    is_day = weather.get("is_day", True)

    theme = _temp_color(temp_f, condition_id)

    # Breathing side stripe (x=0-1, full height)
    pulse = 0.45 + 0.25 * math.sin(2 * math.pi * current_time / 3.0)
    stripe = (int(theme[0] * pulse), int(theme[1] * pulse), int(theme[2] * pulse))
    for y in range(32):
        draw.point((0, y), fill=stripe)
        draw.point((1, y), fill=stripe)

    # Weather icon: x=3-12, y=1-10
    _draw_weather_icon(draw, 3, 1, condition_id, is_day)

    # Row A: Temperature (y=1, FONT_6X10, animated shimmer) — centered in x=14-63 (50px)
    shimmer = 0.88 + 0.12 * math.sin(2 * math.pi * current_time / 4.0)
    temp_color = (
        min(255, int(theme[0] * shimmer)),
        min(255, int(theme[1] * shimmer)),
        min(255, int(theme[2] * shimmer)),
    )
    temp_str = f"{temp_f}\u00b0"
    temp_w = int(draw.textlength(temp_str, font=FONT_6X10))
    temp_x = max(14, 14 + (50 - temp_w) // 2)
    _draw_sharp(image, (temp_x, 1), temp_str, FONT_6X10, temp_color)

    # Row B: Condition description (y=13, FONT_5X8, scrolling)
    desc_color = (
        min(255, int(theme[0] * 0.6 + 100)),
        min(255, int(theme[1] * 0.6 + 100)),
        min(255, int(theme[2] * 0.6 + 100)),
    )
    _draw_scrolling_text(image, description, FONT_5X8, desc_color, 3, 13, 61, current_time)

    # Row C: Humidity (left) + Wind (right), y=23
    _draw_sharp(image, (3, 23), f"{humidity}%", FONT_5X8, (0, 200, 220))

    wind_dir = _wind_cardinal(wind_deg)
    wind_str = f"{wind_dir} {wind_mph}m"
    if wind_mph < 5:
        wind_color = (120, 120, 80)
    elif wind_mph < 15:
        wind_color = (200, 180, 60)
    elif wind_mph < 25:
        wind_color = (240, 140, 40)
    else:
        wind_color = (255, 80, 80)
    wind_w = int(draw.textlength(wind_str, font=FONT_5X8))
    _draw_sharp(image, (63 - wind_w, 23), wind_str, FONT_5X8, wind_color)

    return image


DEBUG_IMAGE_PATH = os.path.join(tempfile.gettempdir(), "ribs-flight-monitor_debug_matrix.png")


def _display_image(matrix, image: Image.Image):
    """Push image to the hardware matrix, or save as debug PNG in simulation mode."""
    if matrix:
        matrix.SetImage(image.convert("RGB"))
    else:
        image.save(DEBUG_IMAGE_PATH)


def render_to_matrix(matrix, flight_data, current_time: float = 0.0, mode_hint: str = ""):
    """Backward-compatible wrapper: build and display the flight image."""
    _display_image(matrix, _build_flight_image(flight_data, current_time, mode_hint=mode_hint))


def led_daemon_loop():
    logging.info("Starting LED Matrix background thread")
    matrix = init_matrix()

    while True:
        try:
            with state_lock:
                current_mode = app_state["mode"]
                target_callsign = app_state["callsign"].strip().upper()
                target_airport = app_state["airport"].strip().upper()
                text_message = app_state["text_message"]
                text_color = app_state["text_color"]

            # 1. Fetch Data
            weather_data = None
            if current_mode == "radius":
                flight_data = fetch_fr24_data()
                arrivals_data = []
            elif current_mode == "monitor" and target_callsign:
                flight_data = fetch_aeroapi_data(target_callsign)
                arrivals_data = []
            elif current_mode == "arrivals" and target_airport:
                arrivals_data = fetch_arrivals_data(target_airport)
                flight_data = None
            elif current_mode == "blank":
                flight_data = None
                arrivals_data = []
            elif current_mode == "weather":
                weather_data = fetch_weather_data()
                flight_data = None
                arrivals_data = []
            elif current_mode == "heatmap":
                # Heatmap is purely DB-driven; still scan radius so logging / alerts keep working
                flight_data = fetch_fr24_data()
                arrivals_data = []
            else:
                flight_data = None
                arrivals_data = []

            with state_lock:
                app_state["current_flight"] = flight_data
                app_state["current_arrivals"] = arrivals_data
                if current_mode == "weather":
                    app_state["current_weather"] = weather_data
                if current_mode in ("radius", "heatmap") and flight_data:
                    app_state["last_seen_flight"] = flight_data
                    app_state["last_seen_at"] = time.time()
                    try:
                        db.record_flight(flight_data)
                    except Exception as e:
                        logging.warning(f"Failed to record flight to DB: {e}")
                    # Special-flight detection
                    reason = _classify_special_flight(flight_data)
                    if reason and _record_special_alert_once(flight_data, reason):
                        logging.info(f"SPECIAL ALERT [{reason}] {flight_data.get('callsign')}")
                        if config.DISCORD_ALERT_SPECIAL:
                            try:
                                _, embeds = _format_special_alert_for_discord(
                                    {"reason": reason, "flight": flight_data}
                                )
                                _discord_post("", embeds=embeds)
                            except Exception as e:
                                logging.warning(f"discord alert failed: {e}")
                render_flight = flight_data if flight_data else (
                    app_state["last_seen_flight"] if current_mode == "radius" else None
                )
                render_arrivals = arrivals_data
                render_airport = target_airport
                render_weather = weather_data

            # 2. Display initial frame, then hold for poll interval, rebuilding on frame tick
            if current_mode == "radius":
                sleep_sec = config.FR24_POLL_INTERVAL
            elif current_mode == "monitor":
                sleep_sec = config.MONITOR_POLL_INTERVAL
            elif current_mode == "text":
                sleep_sec = 5.0  # no API polling needed; just animate
            elif current_mode == "blank":
                sleep_sec = 5.0  # no API polling needed
            elif current_mode == "weather":
                sleep_sec = config.WEATHER_POLL_INTERVAL
            elif current_mode == "heatmap":
                sleep_sec = config.FR24_POLL_INTERVAL
            else:
                sleep_sec = config.ARRIVALS_POLL_INTERVAL

            # Daily Discord summary check
            try:
                _post_daily_summary_if_due()
            except Exception as e:
                logging.warning(f"daily summary check failed: {e}")

            poll_start = time.monotonic()
            while time.monotonic() - poll_start < sleep_sec:
                current_time = time.time()
                # Apply brightness from app_state (runtime adjustable via Settings)
                if matrix:
                    with state_lock:
                        b = app_state.get("matrix_brightness")
                    if b is not None:
                        try:
                            matrix.brightness = max(1, min(100, int(b)))
                        except (AttributeError, TypeError):
                            pass
                if current_mode == "blank":
                    frame = Image.new("RGB", (64, 32), (0, 0, 0))
                elif current_mode == "arrivals":
                    frame = _build_arrivals_image(render_arrivals, render_airport, current_time)
                elif current_mode == "text":
                    with state_lock:
                        text_message = app_state["text_message"]
                        text_color = app_state["text_color"]
                    frame = _build_text_image(text_message, text_color, current_time)
                elif current_mode == "weather":
                    frame = _build_weather_image(render_weather, current_time)
                elif current_mode == "heatmap":
                    frame = _build_heatmap_image(current_time)
                else:
                    frame = _build_flight_image(render_flight, current_time, mode_hint=current_mode)

                # Special-flight alert overlay (any mode that shows a flight)
                if current_mode in ("radius", "heatmap", "monitor"):
                    alert = _active_alert()
                    if alert:
                        frame = _build_alert_overlay(frame, alert, current_time)

                _display_image(matrix, frame)
                time.sleep(0.05)  # ~20 FPS for smooth scrolling

        except Exception as e:
            logging.error(f"Exception in LED daemon loop: {e}")
            time.sleep(config.FR24_POLL_INTERVAL)

# --- Flask Routes ---

@app.route('/')
def index():
    return render_template('index.html', matrix_available=MATRIX_AVAILABLE)

@app.route('/api/state', methods=['GET'])
def get_state():
    with state_lock:
        return jsonify({
            "mode": app_state["mode"],
            "callsign": app_state["callsign"],
            "airport": app_state["airport"],
            "text_message": app_state["text_message"],
            "text_color": app_state["text_color"],
            "current_flight": app_state["current_flight"],
            "current_arrivals": app_state["current_arrivals"],
            "current_weather": app_state["current_weather"],
            "last_seen_flight": app_state["last_seen_flight"],
            "last_seen_at": app_state["last_seen_at"],
        })

@app.route('/api/state', methods=['POST'])
def update_state():
    data = request.json
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
        
    with state_lock:
        if "mode" in data and data["mode"] in ["radius", "monitor", "arrivals", "text", "blank", "weather", "heatmap"]:
            app_state["mode"] = data["mode"]
            logging.info(f"Mode switched to {app_state['mode']}")

        if "callsign" in data:
            app_state["callsign"] = str(data["callsign"]).upper()
            logging.info(f"Target callsign updated to {app_state['callsign']}")

        if "airport" in data:
            app_state["airport"] = str(data["airport"]).upper().strip()
            logging.info(f"Target airport updated to {app_state['airport']}")

        if "text_message" in data:
            app_state["text_message"] = str(data["text_message"]).strip()
            logging.info(f"Text message updated to: {app_state['text_message']}")

        if "text_color" in data:
            raw = str(data["text_color"]).strip()
            if re.fullmatch(r'#[0-9A-Fa-f]{6}', raw):
                app_state["text_color"] = raw
                logging.info(f"Text color updated to {raw}")
            
    return jsonify({"status": "success"})

@app.route('/api/airline-logo/<icao>')
def airline_logo(icao):
    """Proxy airline logo from logo.dev (caches in memory). Returns 404 if unknown/unconfigured."""
    icao = icao.upper()[:3]
    logo_bytes = _fetch_logo_dev_bytes(icao)
    if not logo_bytes:
        return "", 404
    return send_file(BytesIO(logo_bytes), mimetype="image/png")


@app.route('/stats')
def stats_page():
    return render_template('stats.html', matrix_available=MATRIX_AVAILABLE)


@app.route('/api/stats')
def api_stats():
    """Return stats for the Stats page. Optional ?period=day|week|month|year|all."""
    period = request.args.get("period", "week")
    try:
        return jsonify(db.get_stats(period=period))
    except Exception as e:
        logging.error(f"Stats API error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/calendar')
def api_calendar():
    """Daily flight counts for the heatmap calendar."""
    try:
        days = int(request.args.get("days", "90"))
    except ValueError:
        days = 90
    try:
        return jsonify({"days": db.get_calendar(days=days)})
    except Exception as e:
        logging.error(f"Calendar API error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/on-this-day')
def api_on_this_day():
    try:
        return jsonify(db.get_on_this_day())
    except Exception as e:
        logging.error(f"On-this-day API error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/alerts')
def api_alerts():
    try:
        recent = db.list_recent_alerts(limit=int(request.args.get("limit", "20")))
    except Exception as e:
        logging.error(f"Alerts API error: {e}")
        return jsonify({"error": str(e)}), 500
    _purge_expired_alerts()
    active = []
    for cs, a in special_alert_state["active"].items():
        active.append({
            "callsign": cs,
            "reason": a.get("reason"),
            "first": a.get("first"),
            "until": a.get("until"),
            "flight": a.get("flight", {}),
        })
    return jsonify({"active": active, "recent": recent})


@app.route('/api/health')
def api_health():
    now = time.time()
    sources = {}
    for k in ("fr24", "aero", "weather", "logodev"):
        s = health_state.get(k, {})
        sources[k] = {
            "calls": s.get("calls", 0),
            "errors": s.get("errors", 0),
            "last_latency_ms": s.get("last_latency_ms", 0),
            "last_ok_age_sec": int(now - s["last_ok"]) if s.get("last_ok") else None,
            "last_err": s.get("last_err", ""),
        }

    aero_today = health_state.get("aero_calls_today", {})
    today = time.strftime("%Y-%m-%d")
    aero_count_today = aero_today.get("count", 0) if aero_today.get("day") == today else 0

    db_size = 0
    db_count = 0
    try:
        db_size = db.get_db_size_bytes()
        db_count = db.get_total_flight_count()
    except Exception as e:
        logging.warning(f"db health failed: {e}")

    with state_lock:
        cur_mode = app_state.get("mode")

    return jsonify({
        "uptime_sec": int(now - health_state.get("started_at", now)),
        "mode": cur_mode,
        "matrix_available": MATRIX_AVAILABLE,
        "fr24_available": FR24_AVAILABLE,
        "sources": sources,
        "aero_calls_today": aero_count_today,
        "db_bytes": db_size,
        "db_total_flights": db_count,
        "active_alerts": len(special_alert_state.get("active", {})),
        "config_keys_set": {
            "FLIGHTAWARE_API_KEY": bool(config.FLIGHTAWARE_API_KEY),
            "OPENWEATHER_API_KEY": bool(config.OPENWEATHER_API_KEY),
            "LOGO_DEV_TOKEN": bool(config.LOGO_DEV_TOKEN),
            "DISCORD_WEBHOOK_URL": bool(config.DISCORD_WEBHOOK_URL),
            "HOME_SET": (config.HOME_LAT != 0.0 or config.HOME_LON != 0.0),
        },
    })


@app.route('/health')
def health_page():
    return render_template('health.html', matrix_available=MATRIX_AVAILABLE)


@app.route('/api/env', methods=['GET'])
def api_env_get():
    """Return current values for editable env keys. Secrets are returned masked."""
    raw = _read_env_file()
    out = []
    for k in ENV_EDITABLE_KEYS:
        v = raw.get(k, "")
        masked = bool(v) and k in ENV_SECRET_KEYS
        out.append({
            "key": k,
            "value": "" if masked else v,
            "is_secret": k in ENV_SECRET_KEYS,
            "is_set": bool(v),
        })
    return jsonify({"vars": out, "path": ENV_PATH})


@app.route('/api/env', methods=['POST'])
def api_env_post():
    data = request.json or {}
    updates = data.get("updates") or {}
    if not isinstance(updates, dict):
        return jsonify({"error": "updates must be an object"}), 400

    safe = {}
    for k, v in updates.items():
        if k not in ENV_EDITABLE_KEYS:
            continue
        # For secrets, treat empty string as "leave unchanged" so masked GETs round-trip safely
        if k in ENV_SECRET_KEYS and (v is None or str(v).strip() == ""):
            continue
        safe[k] = "" if v is None else str(v)

    if not safe:
        return jsonify({"ok": True, "updated": [], "note": "Nothing to update."})

    # Preserve unchanged secrets by reading their current values back in
    if any(k in ENV_SECRET_KEYS for k in ENV_EDITABLE_KEYS):
        existing = _read_env_file()
        for k in ENV_EDITABLE_KEYS:
            if k in ENV_SECRET_KEYS and k not in safe and k in existing:
                safe[k] = existing[k]

    try:
        _write_env_file(safe)
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    restart = bool(data.get("restart"))
    if restart:
        _schedule_restart()
    return jsonify({
        "ok": True,
        "updated": [k for k in updates.keys() if k in ENV_EDITABLE_KEYS],
        "restarting": restart,
    })


@app.route('/api/discord/test', methods=['POST'])
def api_discord_test():
    if not config.DISCORD_WEBHOOK_URL:
        return jsonify({"ok": False, "error": "No DISCORD_WEBHOOK_URL configured"}), 400
    ok = _discord_post("👋 Ribs FlightWall test ping — webhook is wired up.")
    return jsonify({"ok": ok})


@app.route('/api/discord/summary', methods=['POST'])
def api_discord_summary():
    """Force-post the daily summary now (ignores time-of-day gate)."""
    discord_state["last_summary_day"] = ""  # reset gate so the helper actually runs
    # Temporarily allow ignoring hour by faking the localtime check
    try:
        stats = db.get_stats(period="day")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    total = stats.get("total_flights", 0)
    msg = [f"**Manual Airspace Summary**", f"✈️ {total} flights overhead today."]
    top_airline = (stats.get("top_airlines") or [{}])[0]
    if top_airline.get("airline_name"):
        msg.append(f"• Top airline: **{top_airline['airline_name']}** ({top_airline.get('count', 0)})")
    top_aircraft = (stats.get("top_aircraft") or [{}])[0]
    if top_aircraft.get("aircraft_model"):
        msg.append(f"• Top aircraft: **{top_aircraft['aircraft_model']}** ({top_aircraft.get('count', 0)})")
    ok = _discord_post("\n".join(msg))
    return jsonify({"ok": ok})


@app.route('/debug/matrix.png')
def debug_matrix():
    if not os.path.exists(DEBUG_IMAGE_PATH):
        return "Image not found", 404
    return send_file(DEBUG_IMAGE_PATH, mimetype='image/png')


# --- Settings ---

SERVICE_NAME = "flightwall"  # systemd service name (flightwall.service)


def _schedule_restart():
    """Schedule systemctl restart in a background thread (allows HTTP response to be sent first)."""
    def _restart():
        time.sleep(1.5)
        try:
            subprocess.run(["sudo", "systemctl", "restart", SERVICE_NAME], check=True, capture_output=True, text=True)
            logging.info("flightwall service restarted successfully")
        except FileNotFoundError:
            logging.warning("systemctl not found (likely not on Raspberry Pi)")
        except subprocess.CalledProcessError as e:
            logging.error(f"systemctl restart failed: {e.stderr or e}")

    thread = threading.Thread(target=_restart, daemon=True)
    thread.start()


@app.route('/settings')
def settings_page():
    return render_template('settings.html', matrix_available=MATRIX_AVAILABLE)


@app.route('/api/matrix-brightness', methods=['GET'])
def api_matrix_brightness_get():
    with state_lock:
        return jsonify({"brightness": app_state["matrix_brightness"]})


@app.route('/api/matrix-brightness', methods=['POST'])
def api_matrix_brightness_post():
    data = request.json or {}
    with state_lock:
        current = app_state["matrix_brightness"]

    # Support delta (e.g. { "delta": -5 }) or absolute { "brightness": 50 }
    if "delta" in data:
        try:
            delta = int(data["delta"])
            val = max(1, min(100, current + delta))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid delta"}), 400
    elif "brightness" in data:
        try:
            val = max(1, min(100, int(data["brightness"])))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid brightness"}), 400
    else:
        return jsonify({"error": "Provide delta or brightness"}), 400

    with state_lock:
        app_state["matrix_brightness"] = val

    try:
        with open(BRIGHTNESS_FILE, "w") as f:
            f.write(str(val))
    except OSError as e:
        logging.warning(f"Could not persist matrix brightness: {e}")

    return jsonify({"brightness": val})


@app.route('/api/update-and-restart', methods=['POST'])
def api_update_and_restart():
    """
    Run git pull in the project directory, then restart the flightwall systemd service.
    Returns git output. Service restart happens ~1.5s after response is sent.
    """
    try:
        repo_dir = BASE_DIR
        result = subprocess.run(
            ["git", "pull"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""

        if result.returncode != 0:
            return jsonify({
                "ok": False,
                "message": "git pull failed",
                "stdout": stdout,
                "stderr": stderr,
                "returncode": result.returncode,
            }), 500

        _schedule_restart()
        return jsonify({
            "ok": True,
            "message": "Updated successfully. Service restarting in a few seconds…",
            "stdout": stdout.strip() or "(no output)",
        })
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "message": "git pull timed out"}), 500
    except FileNotFoundError:
        return jsonify({"ok": False, "message": "git not found"}), 500
    except Exception as e:
        logging.error(f"update-and-restart error: {e}")
        return jsonify({"ok": False, "message": str(e)}), 500

# Preset test flights for dev/layout testing
TEST_FLIGHTS = {
    "with_logo": {
        "callsign": "AAL1695",
        "altitude": 27000,
        "speed": 503,
        "route": "PHL - BOS",
        "origin_name": "Philadelphia International Airport",
        "dest_name": "Boston Logan International Airport",
        "airline_icao": "AAL",
        "airline_name": "American",
        "aircraft_model": "Boeing 737 MAX 8",
        "aircraft_code": "B38M",
    },
    "no_logo": {
        "callsign": "N12345",
        "altitude": 8500,
        "speed": 210,
        "route": "FRG - ACK",
        "origin_name": "Republic Airport",
        "dest_name": "Nantucket Memorial Airport",
        "airline_icao": "",
        "airline_name": "",
        "aircraft_model": "Cessna 172",
        "aircraft_code": "C172",
    },
    "long_text": {
        "callsign": "ASA401",
        "altitude": 35000,
        "speed": 480,
        "route": "PDX - LAX",
        "origin_name": "Portland International Airport",
        "dest_name": "Los Angeles International Airport",
        "airline_icao": "ASA",
        "airline_name": "Alaska",
        "aircraft_model": "Boeing 737 MAX 9",
        "aircraft_code": "B39M",
    },
    "no_flight": None,
}

# Sample arrivals for debug/test (arrivals board layout)
TEST_ARRIVALS = [
    {"callsign": "AAL1695", "origin_iata": "PHL", "eta": "2:45 PM", "airline_icao": "AAL"},
    {"callsign": "UAL456", "origin_iata": "ORD", "eta": "3:12 PM", "airline_icao": "UAL"},
    {"callsign": "DAL789", "origin_iata": "ATL", "eta": "3:30 PM", "airline_icao": "DAL"},
]

@app.route('/debug/test-render', methods=['POST'])
def debug_test_render():
    """Render a test flight or arrivals board to debug_matrix.png without calling any external API."""
    data = request.json or {}
    preset = data.get("preset", "with_logo")
    simulated_time = time.time()

    if preset == "arrivals":
        _display_image(None, _build_arrivals_image(TEST_ARRIVALS, "JFK", simulated_time))
        return jsonify({"status": "ok", "preset": preset, "arrivals": TEST_ARRIVALS})

    flight = TEST_FLIGHTS.get(preset, TEST_FLIGHTS["with_logo"])
    render_to_matrix(None, flight, simulated_time)
    return jsonify({"status": "ok", "preset": preset, "flight": flight})

if __name__ == '__main__':
    db.init_db()
    # Start LED thread as a daemon (will die when main thread dies)
    led_thread = threading.Thread(target=led_daemon_loop, daemon=True)
    led_thread.start()
    
    # Run Flask server
    # Important: host='0.0.0.0' allows external connections (from mobile phone)
    # port=80 requires root privileges on Linux, use 8080 or other for local testing
    app.run(host='0.0.0.0', port=config.FLASK_PORT, debug=False, use_reloader=False)
