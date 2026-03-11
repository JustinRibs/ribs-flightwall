import os
import tempfile
import time
import threading
import logging
from io import BytesIO

import requests
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

# Global Application State
app_state = {
    "mode": "radius",       # "radius", "monitor", or "arrivals"
    "callsign": "",         # Target callsign for monitor mode
    "airport": "",          # Target airport IATA/ICAO for arrivals mode (e.g. JFK, KJFK)
    "current_flight": None, # Cache the latest flight data
    "current_arrivals": [], # List of arrivals for arrivals mode
    "last_seen_flight": None # Last flight seen in radius mode (shown when nothing in range)
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
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        logodev_cache[icao_code] = resp.content
        logging.info(f"logo.dev: cached logo for {icao_code}")
        return resp.content
    except Exception as e:
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

    try:
        # Step 1: Get flights for this ident (ident_type=designator forces callsign, not registration)
        list_url = f"{AEROAPI_URL}/flights/{callsign_upper}"
        list_resp = requests.get(
            list_url, headers=headers,
            params={"ident_type": "designator"},
            timeout=10
        )
        list_resp.raise_for_status()
        list_data = list_resp.json()
        flights = list_data.get("flights", [])

        if not flights:
            aeroapi_cache = {"callsign": callsign_upper, "data": None, "time": now}
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
            logging.info(f"AeroAPI: Found {result['callsign']} at {altitude}ft, {speed}kt ({orig_iata}-{dest_iata})")
            return result

        aeroapi_cache = {"callsign": callsign_upper, "data": None, "time": now}
        logging.info(f"AeroAPI: No active position for {callsign_upper} (flights may be scheduled/arrived)")
        return None

    except requests.exceptions.RequestException as e:
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


def _is_valid_commercial(flight):
    """Check if flight has both origin and destination IATA (filters out FRG/local traffic)."""
    orig = getattr(flight, "origin_airport_iata", None)
    dest = getattr(flight, "destination_airport_iata", None)
    if orig in NA_VALUES or dest in NA_VALUES:
        return False
    orig = str(orig).strip().upper() if orig else ""
    dest = str(dest).strip().upper() if dest else ""
    return len(orig) == 3 and len(dest) == 3


def fetch_fr24_data():
    """Fetch closest commercial flight within 10km of Farmingdale using FlightRadar24."""
    if not FR24_AVAILABLE or not fr_api:
        logging.error("FlightRadar24API not available")
        return None

    try:
        # 10-mile radius around home (~16093m)
        bounds = fr_api.get_bounds_by_point(
            config.HOME_LAT, config.HOME_LON, 16093
        )
        flights = fr_api.get_flights(bounds=bounds)

        # Filter: commercial (origin+dest IATA), altitude >= 2500 ft
        qualified = []
        for f in flights or []:
            if not _is_valid_commercial(f):
                continue
            alt = getattr(f, "altitude", None)
            if alt is None or (isinstance(alt, (int, float)) and alt < 2500):
                continue
            qualified.append(f)

        if not qualified:
            return None

        # Pick closest to HOME (Entity.get_distance_from needs lat/lon attributes)
        from types import SimpleNamespace
        home_pos = SimpleNamespace(latitude=config.HOME_LAT, longitude=config.HOME_LON)
        closest = min(qualified, key=lambda f: f.get_distance_from(home_pos))

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
        }

    except Exception as e:
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


def _build_flight_image(flight_data, current_time: float) -> Image.Image:
    """Pixel-perfect 64x32 layout: logo left (0-16) | text right (x=19+)."""
    image = Image.new("RGB", (64, 32), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    if not flight_data:
        time_str = time.strftime("%I:%M %p").lstrip("0")
        
        temp_img = Image.new("RGB", (1, 1))
        temp_draw = ImageDraw.Draw(temp_img)
        w = temp_draw.textlength(time_str, font=FONT_6X10)
        
        x = max(0, (64 - int(w)) // 2)
        y = (32 - 10) // 2  # Approximate vertical center for 6x10 font
        
        draw.text((x, y), time_str, font=FONT_6X10, fill=(100, 100, 100))
        return image

    callsign      = (flight_data.get("callsign") or "").strip().upper()
    
    # Try to resolve full airline name + flight number
    icao_code = (flight_data.get("airline_icao") or callsign[:3] or "").upper()[:3]
    airline_name = flight_data.get("airline_name") or AIRLINE_NAMES.get(icao_code, "")
    if airline_name and callsign.startswith(icao_code):
        flight_num = callsign[len(icao_code):]
        display_callsign = f"{airline_name} {flight_num}".strip()
    elif airline_name:
        display_callsign = airline_name
    else:
        display_callsign = callsign

    origin        = (flight_data.get("origin_iata") or flight_data.get("origin") or "").strip().upper() or "N/A"
    dest          = (flight_data.get("dest_iata") or flight_data.get("destination") or "").strip().upper() or "N/A"
    alt           = flight_data.get("altitude", 0) or 0
    spd           = flight_data.get("speed", 0) or 0
    alt_k         = f"{alt // 1000}k" if alt >= 1000 else str(alt)
    spd_kt        = int(round(spd))
    aircraft_code = (flight_data.get("aircraft_code") or "").strip().upper()

    # --- Right zone text: 3 lines ---
    TEXT_X = 19
    TEXT_W = 64 - TEXT_X  # 45px

    # Line 1 (y=2): Airline Name + Flight Number (FONT_5X8, Yellow)
    _draw_scrolling_text(image, display_callsign, FONT_5X8, (255, 220, 0), TEXT_X, 2, TEXT_W, current_time)
    
    # Line 2 (y=12): Route (FONT_5X8, Cyan) or Full Destination Name
    dest_name_raw = flight_data.get("dest_name", "")
    dest_name = _shorten_airport_name(dest_name_raw)
    
    # Alternate every 8 seconds
    route_cycle = int(current_time / 8.0) % 2
    local_time = current_time % 8.0
    
    if route_cycle == 1 and dest_name:
        _draw_scrolling_text(image, f"To: {dest_name}", FONT_5X8, (0, 220, 255), TEXT_X, 12, TEXT_W, local_time)
    else:
        route_text = f"{origin} - {dest}"
        _draw_scrolling_text(image, route_text, FONT_5X8, (0, 220, 255), TEXT_X, 12, TEXT_W, local_time)

    # Line 3 (y=22): Alternating Alt/Speed vs Aircraft (FONT_5X8)
    cycle = int(current_time / 6.0) % 2
    local_time_3 = current_time % 6.0
    
    if cycle == 0:
        # Altitude and Speed (Green)
        alt_spd_text = f"{alt_k} {spd_kt}kt"
        _draw_scrolling_text(image, alt_spd_text, FONT_5X8, (0, 220, 0), TEXT_X, 22, TEXT_W, local_time_3)
    else:
        # Aircraft Code (Magenta)
        if aircraft_code:
            _draw_scrolling_text(image, aircraft_code, FONT_5X8, (255, 0, 255), TEXT_X, 22, TEXT_W, local_time_3)
        else:
            # Fallback to alt/spd if no aircraft code
            alt_spd_text = f"{alt_k} {spd_kt}kt"
            _draw_scrolling_text(image, alt_spd_text, FONT_5X8, (0, 220, 0), TEXT_X, 22, TEXT_W, local_time_3)

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


DEBUG_IMAGE_PATH = os.path.join(tempfile.gettempdir(), "ribs-flight-monitor_debug_matrix.png")


def _display_image(matrix, image: Image.Image):
    """Push image to the hardware matrix, or save as debug PNG in simulation mode."""
    if matrix:
        matrix.SetImage(image.convert("RGB"))
    else:
        image.save(DEBUG_IMAGE_PATH)


def render_to_matrix(matrix, flight_data, current_time: float = 0.0):
    """Backward-compatible wrapper: build and display the flight image."""
    _display_image(matrix, _build_flight_image(flight_data, current_time))


def led_daemon_loop():
    logging.info("Starting LED Matrix background thread")
    matrix = init_matrix()

    while True:
        try:
            with state_lock:
                current_mode = app_state["mode"]
                target_callsign = app_state["callsign"].strip().upper()
                target_airport = app_state["airport"].strip().upper()

            # 1. Fetch Data
            if current_mode == "radius":
                flight_data = fetch_fr24_data()
                arrivals_data = []
            elif current_mode == "monitor" and target_callsign:
                flight_data = fetch_aeroapi_data(target_callsign)
                arrivals_data = []
            elif current_mode == "arrivals" and target_airport:
                arrivals_data = fetch_arrivals_data(target_airport)
                flight_data = None
            else:
                flight_data = None
                arrivals_data = []

            with state_lock:
                app_state["current_flight"] = flight_data
                app_state["current_arrivals"] = arrivals_data
                if current_mode == "radius" and flight_data:
                    app_state["last_seen_flight"] = flight_data
                render_flight = flight_data if flight_data else (
                    app_state["last_seen_flight"] if current_mode == "radius" else None
                )
                render_arrivals = arrivals_data
                render_airport = target_airport

            # 2. Display initial frame, then hold for poll interval, rebuilding on frame tick
            if current_mode == "radius":
                sleep_sec = config.FR24_POLL_INTERVAL
            elif current_mode == "monitor":
                sleep_sec = config.MONITOR_POLL_INTERVAL
            else:
                sleep_sec = config.ARRIVALS_POLL_INTERVAL

            poll_start = time.monotonic()
            while time.monotonic() - poll_start < sleep_sec:
                current_time = time.time()
                if current_mode == "arrivals":
                    _display_image(matrix, _build_arrivals_image(render_arrivals, render_airport, current_time))
                else:
                    _display_image(matrix, _build_flight_image(render_flight, current_time))
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
            "current_flight": app_state["current_flight"],
            "current_arrivals": app_state["current_arrivals"]
        })

@app.route('/api/state', methods=['POST'])
def update_state():
    data = request.json
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
        
    with state_lock:
        if "mode" in data and data["mode"] in ["radius", "monitor", "arrivals"]:
            app_state["mode"] = data["mode"]
            logging.info(f"Mode switched to {app_state['mode']}")
            
        if "callsign" in data:
            app_state["callsign"] = str(data["callsign"]).upper()
            logging.info(f"Target callsign updated to {app_state['callsign']}")
            
        if "airport" in data:
            app_state["airport"] = str(data["airport"]).upper().strip()
            logging.info(f"Target airport updated to {app_state['airport']}")
            
    return jsonify({"status": "success"})

@app.route('/api/airline-logo/<icao>')
def airline_logo(icao):
    """Proxy airline logo from logo.dev (caches in memory). Returns 404 if unknown/unconfigured."""
    icao = icao.upper()[:3]
    logo_bytes = _fetch_logo_dev_bytes(icao)
    if not logo_bytes:
        return "", 404
    return send_file(BytesIO(logo_bytes), mimetype="image/png")


@app.route('/debug/matrix.png')
def debug_matrix():
    if not os.path.exists(DEBUG_IMAGE_PATH):
        return "Image not found", 404
    return send_file(DEBUG_IMAGE_PATH, mimetype='image/png')

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
    # Start LED thread as a daemon (will die when main thread dies)
    led_thread = threading.Thread(target=led_daemon_loop, daemon=True)
    led_thread.start()
    
    # Run Flask server
    # Important: host='0.0.0.0' allows external connections (from mobile phone)
    # port=80 requires root privileges on Linux, use 8080 or other for local testing
    app.run(host='0.0.0.0', port=config.FLASK_PORT, debug=False, use_reloader=False)
