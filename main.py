import os
import time
import threading
import logging
from io import BytesIO

import requests
from flask import Flask, render_template, request, jsonify, send_file
from PIL import Image, ImageDraw, ImageFont
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
FONT_PATH = os.path.join(BASE_DIR, "fonts", "PixelOperator.ttf")
SMALL_FONT_PATH = os.path.join(BASE_DIR, "fonts", "PixelOperator8.ttf")
BOLD_FONT_PATH  = os.path.join(BASE_DIR, "fonts", "PixelOperator8-Bold.ttf")
TINY_FONT_PATH  = os.path.join(BASE_DIR, "fonts", "Tom Thumb.ttf")

# Global Application State
app_state = {
    "mode": "radius",       # "radius" or "monitor"
    "callsign": "",         # Target callsign for monitor mode
    "current_flight": None, # Cache the latest flight data
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


def _fit_text(draw, text: str, font, max_px: int) -> str:
    """Truncate text until it fits within max_px wide (measured by PIL, not char count)."""
    while text:
        w = draw.textlength(text, font=font)
        if w <= max_px:
            return text
        text = text[:-1]
    return ""


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
    if not MATRIX_AVAILABLE:
        return None
        
    options = RGBMatrixOptions()
    options.rows = 32
    options.cols = 64
    options.chain_length = 1
    options.parallel = 1
    options.hardware_mapping = 'adafruit-hat'
    options.brightness = config.MATRIX_BRIGHTNESS
    
    # Optional performance tweaks (uncomment if experiencing flicker)
    # options.pwm_bits = 11
    # options.pwm_lsb_nanoseconds = 130
    # options.disable_hardware_pulsing = True
    
    return RGBMatrix(options=options)

# Global cache for AeroAPI to prevent overcharges
aeroapi_cache = {
    "callsign": "",
    "data": None,
    "time": 0
}

def fetch_aeroapi_data(callsign):
    global aeroapi_cache
    
    # Return cached data if within the polling interval and callsign hasn't changed
    now = time.time()
    if callsign == aeroapi_cache["callsign"] and now - aeroapi_cache["time"] < config.MONITOR_POLL_INTERVAL:
        return aeroapi_cache["data"]

    if not config.FLIGHTAWARE_API_KEY:
        logging.error("No FlightAware API key configured")
        return None
        
    url = f"{AEROAPI_URL}/flights/{callsign}"
    headers = {"x-apikey": config.FLIGHTAWARE_API_KEY}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        flights = data.get("flights", [])
        if not flights:
            aeroapi_cache = {"callsign": callsign, "data": None, "time": now}
            return None
            
        # Find the most relevant flight (e.g., currently en route)
        for flight in flights:
            pos = flight.get("last_position")
            if pos:
                altitude = pos.get("altitude", 0) * 100 # AeroAPI returns hundreds of feet
                speed = pos.get("groundspeed", 0) # AeroAPI returns knots
                
                result = {
                    "callsign": callsign.upper(),
                    "altitude": altitude,
                    "speed": speed
                }
                
                aeroapi_cache = {"callsign": callsign, "data": result, "time": now}
                return result
                
        # If no active flight position is found
        aeroapi_cache = {"callsign": callsign, "data": None, "time": now}
        return None

    except requests.exceptions.RequestException as e:
        logging.error(f"AeroAPI Request Error: {e}")
        return None

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
        try:
            details = fr_api.get_flight_details(closest)
            if details and isinstance(details, dict):
                closest.set_flight_details(details)
                aircraft_model = getattr(closest, "aircraft_model", None)
                if aircraft_model in NA_VALUES:
                    aircraft_model = None
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
            "airline_icao": airline_icao,
            "airline_name": AIRLINE_NAMES.get(airline_icao, ""),
            "aircraft_model": aircraft_model or aircraft_code,  # full name for web UI
            "aircraft_code": aircraft_code,  # short ICAO type for matrix (e.g. "A321")
        }

    except Exception as e:
        logging.error(f"FlightRadar24 API Error: {e}")
        return None

def _format_alt_speed(alt, spd):
    """Format altitude/speed for bottom line: '32k 450kt' (compact to fit 64px matrix)."""
    alt_str = f"{alt // 1000}k" if alt >= 1000 else str(alt)
    return f"{alt_str} {spd}kt"


def _find_logo_path(icao_code):
    """Resolve airline logo path (check logo/ and logo2/ subdirs)."""
    logos_dir = os.path.join(BASE_DIR, "assets", "logos")
    for subdir in ("logo", "logo2", ""):
        path = os.path.join(logos_dir, subdir, f"{icao_code}.png") if subdir else os.path.join(logos_dir, f"{icao_code}.png")
        if os.path.exists(path):
            return path
    return None


def render_to_matrix(matrix, flight_data):
    # Create 64x32 RGB canvas
    image = Image.new("RGB", (64, 32), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # All PixelOperator8 at 8px — 4 rows, all readable.
    # Logo (16×16) sits top-left; rows 0-1 share its column, rows 2-3 are full width.
    # Row layout: y=0 airline, y=8 callsign, y=16 route (full width), y=24 aircraft
    try:
        font = ImageFont.truetype(SMALL_FONT_PATH, 8)
    except IOError:
        font = ImageFont.load_default()

    if flight_data:
        callsign = flight_data.get("callsign", "")
        alt = flight_data.get("altitude", 0)
        spd = flight_data.get("speed", 0)
        route = flight_data.get("route", "")
        airline_name = flight_data.get("airline_name", "")

        # ICAO for logo: prefer airline_icao, else first 3 chars of callsign
        icao_code = (flight_data.get("airline_icao") or callsign[:3] or "").upper()[:3]

        # ── Logo: 16×16 in top-left ──────────────────────────────────────────
        logo_drawn = False
        if icao_code:
            logo_img = None
            logo_path = _find_logo_path(icao_code)
            if logo_path:
                try:
                    logo_img = Image.open(logo_path).convert("RGB")
                except Exception as e:
                    logging.error(f"Error loading local logo {logo_path}: {e}")
            if logo_img is None:
                logo_bytes = _fetch_logo_dev_bytes(icao_code)
                if logo_bytes:
                    try:
                        logo_img = Image.open(BytesIO(logo_bytes)).convert("RGB")
                    except Exception as e:
                        logging.warning(f"logo.dev matrix decode failed for {icao_code}: {e}")
            if logo_img is not None:
                logo_resized = logo_img.resize((16, 16), Image.LANCZOS)
                image.paste(logo_resized, (0, 0))
                logo_drawn = True

        # Rows 0-1 (y=0, y=8) share the logo column → text at x=17.
        # Rows 2-3 (y=16, y=24) are full width — logo has ended at y=15.
        logo_left = 17 if logo_drawn else 2
        full_left = 2
        logo_avail = 63 - logo_left
        full_avail = 62

        route_matrix = route.replace(" - ", "-") if route else ""
        aircraft_model_full = flight_data.get("aircraft_model") or flight_data.get("aircraft_code") or ""
        aircraft_display = _shorten_aircraft(aircraft_model_full)
        alt_spd = _format_alt_speed(alt, spd)

        WHITE  = (255, 255, 255)
        YELLOW = (255, 220, 0)
        CYAN   = (0, 200, 220)
        ORANGE = (255, 140, 0)

        # Row 0 (y=0):  Airline name — beside logo
        draw.text((logo_left, 0),
                  _fit_text(draw, airline_name or callsign, font, logo_avail),
                  font=font, fill=WHITE)

        # Row 1 (y=8):  Callsign — beside logo (short, always fits)
        if airline_name and callsign:
            draw.text((logo_left, 8),
                      _fit_text(draw, callsign, font, logo_avail),
                      font=font, fill=YELLOW)

        # Row 2 (y=16): Route — full width so long routes never get clipped
        if route_matrix:
            draw.text((full_left, 16),
                      _fit_text(draw, route_matrix, font, full_avail),
                      font=font, fill=CYAN)

        # Row 3 (y=24): Aircraft model, or alt+speed if no aircraft known
        bottom = aircraft_display or alt_spd
        if bottom:
            draw.text((full_left, 24),
                      _fit_text(draw, bottom, font, full_avail),
                      font=font, fill=ORANGE)

    else:
        # No commercial flights in range
        with state_lock:
            mode = app_state["mode"]
        msg = "Scanning..." if mode == "radius" else "Waiting..."
        draw.text((4, 12), msg, font=font, fill=(100, 100, 100))

    if matrix:
        matrix.SetImage(image.convert("RGB"))
    else:
        image.save(os.path.join(BASE_DIR, "debug_matrix.png"))

def led_daemon_loop():
    logging.info("Starting LED Matrix background thread")
    matrix = init_matrix()
    
    while True:
        try:
            with state_lock:
                current_mode = app_state["mode"]
                target_callsign = app_state["callsign"].strip().upper()
                
            # 1. Fetch Data
            if current_mode == "radius":
                flight_data = fetch_fr24_data()
            elif current_mode == "monitor" and target_callsign:
                flight_data = fetch_aeroapi_data(target_callsign)
            else:
                flight_data = None

            with state_lock:
                app_state["current_flight"] = flight_data
                if current_mode == "radius" and flight_data:
                    app_state["last_seen_flight"] = flight_data
                render_flight = flight_data if flight_data else (
                    app_state["last_seen_flight"] if current_mode == "radius" else None
                )

            # 2. Render Data
            render_to_matrix(matrix, render_flight)
            
            # 3. Sleep: 10s critical for FR24 (radius) to avoid IP-block; monitor uses 60s to avoid high AeroAPI costs
            sleep_sec = config.FR24_POLL_INTERVAL if current_mode == "radius" else config.MONITOR_POLL_INTERVAL
            time.sleep(sleep_sec)
            
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
            "current_flight": app_state["current_flight"]
        })

@app.route('/api/state', methods=['POST'])
def update_state():
    data = request.json
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
        
    with state_lock:
        if "mode" in data and data["mode"] in ["radius", "monitor"]:
            app_state["mode"] = data["mode"]
            logging.info(f"Mode switched to {app_state['mode']}")
            
        if "callsign" in data:
            app_state["callsign"] = str(data["callsign"]).upper()
            logging.info(f"Target callsign updated to {app_state['callsign']}")
            
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
    debug_path = os.path.join(BASE_DIR, "debug_matrix.png")
    if not os.path.exists(debug_path):
        return "Image not found", 404
    return send_file(debug_path, mimetype='image/png')

# Preset test flights for dev/layout testing
TEST_FLIGHTS = {
    "with_logo": {
        "callsign": "AAL1695",
        "altitude": 27000,
        "speed": 503,
        "route": "PHL - BOS",
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
        "airline_icao": "ASA",
        "airline_name": "Alaska",
        "aircraft_model": "Boeing 737 MAX 9",
        "aircraft_code": "B39M",
    },
    "no_flight": None,
}

@app.route('/debug/test-render', methods=['POST'])
def debug_test_render():
    """Render a test flight to debug_matrix.png without calling any external API."""
    data = request.json or {}
    preset = data.get("preset", "with_logo")
    flight = TEST_FLIGHTS.get(preset, TEST_FLIGHTS["with_logo"])
    render_to_matrix(None, flight)
    return jsonify({"status": "ok", "preset": preset, "flight": flight})

if __name__ == '__main__':
    # Start LED thread as a daemon (will die when main thread dies)
    led_thread = threading.Thread(target=led_daemon_loop, daemon=True)
    led_thread.start()
    
    # Run Flask server
    # Important: host='0.0.0.0' allows external connections (from mobile phone)
    # port=80 requires root privileges on Linux, use 8080 or other for local testing
    app.run(host='0.0.0.0', port=config.FLASK_PORT, debug=False, use_reloader=False)
