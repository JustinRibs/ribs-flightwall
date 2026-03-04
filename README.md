# Ribs FlightWall

![Ribs FlightWall Banner](https://external-content.duckduckgo.com/iu/?u=https%3A%2F%2Fcdn.planespotters.net%2F06597%2F9a-ctg-croatia-airlines-airbus-a319-112_PlanespottersNet_1062614_40121ea29c_o.jpg&f=1&nofb=1&ipt=9e0d3fe3c556386f3e13d220f3d39ba11085d13b0f5b6beeef210f23e8d795ff)

**Ribs FlightWall** is a real-time flight tracking display and control app created by **Justin Ribs Enterprise Inc.**

It is designed to power a 64x32 LED matrix wallboard (Raspberry Pi + RGB matrix), while also giving you a modern browser-based control panel for live monitoring. The system can run in full hardware mode or in simulation mode on a normal computer for development and testing.

---

## What It Does

Ribs FlightWall continuously pulls nearby or specific-flight aviation data, formats it for compact display, and renders it to:

- a physical 64x32 RGB LED matrix (when hardware is available), or
- a live software preview image (`debug_matrix.png`) when running in dev mode.

At the same time, the web dashboard lets you switch modes, set a callsign target, and view current flight details including route, altitude, speed, and airline logo.

---

## Core Features

- **Two tracking modes**
  - **Radius Mode**: Finds the closest valid commercial flight around your configured home coordinates.
  - **Monitor Mode**: Tracks one specific flight globally by callsign.
- **Live control panel** with mode switching, callsign input, status messaging, and current flight card.
- **Automatic airline logos** via `logo.dev` proxy endpoint with in-memory caching.
- **Matrix-optimized rendering** for tiny displays with compact text fitting and data prioritization.
- **Hardware fallback simulation** when `rgbmatrix` is not installed (ideal for local development).
- **Debug/testing presets** for layout checks without hitting live APIs.

---

## Tech Stack

- Python + Flask backend
- HTML/CSS/JavaScript frontend
- PIL/Pillow image rendering for matrix frames
- Flight data sources:
  - FlightRadar24 (radius scanning)
  - FlightAware AeroAPI (callsign monitor mode)
- Optional `rgbmatrix` hardware output for Raspberry Pi LED panels

---

## Project Structure

- `main.py` - app server, API routes, LED rendering loop, and flight fetch logic
- `config.py` - environment-driven configuration
- `templates/index.html` - dashboard UI
- `static/app.js` - frontend behavior and polling
- `static/style.css` - dashboard styles
- `requirements.txt` - Python dependencies

---

## Setup

### 1) Install dependencies

```bash
pip install -r requirements.txt
```

### 2) Configure environment

Create/update your `.env` file with values like:

```env
HOME_LAT=40.0000
HOME_LON=-73.0000
FLIGHTAWARE_API_KEY=your_flightaware_key
LOGO_DEV_TOKEN=your_logo_dev_token
MATRIX_BRIGHTNESS=60
FR24_POLL_INTERVAL=10
MONITOR_POLL_INTERVAL=60
FLASK_PORT=5001
```

### 3) Run

```bash
python main.py
```

Then open:

- `http://localhost:5001` (or your configured port)

---

## Notes for Raspberry Pi / LED Matrix

- If `rgbmatrix` is installed and configured, output is sent directly to hardware.
- If not, the app runs in simulation mode and writes preview frames to `debug_matrix.png`.
- The Flask app listens on `0.0.0.0`, so it can be controlled from another device on your network.

---

## API Endpoints

- `GET /api/state` - current app mode and current tracked flight
- `POST /api/state` - update mode and/or callsign
- `GET /api/airline-logo/<icao>` - proxied airline logo PNG
- `GET /debug/matrix.png` - current rendered matrix preview image
- `POST /debug/test-render` - render one of the built-in test presets

---

## About

**Ribs FlightWall**  
Created by **Justin Ribs Enterprise Inc.**

Built for aviation enthusiasts who want a clean, always-on, glanceable flight wall display with practical controls and reliable real-time updates.
