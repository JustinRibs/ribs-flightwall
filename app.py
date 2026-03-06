#!/usr/bin/env python3
"""
Deployment entry point for Raspberry Pi with Adafruit RGB Matrix Bonnet.
Runs the flight tracker web dashboard on port 80 for network access.
"""
import threading

from main import app, led_daemon_loop

if __name__ == '__main__':
    # Start LED matrix daemon thread
    led_thread = threading.Thread(target=led_daemon_loop, daemon=True)
    led_thread.start()

    # Run Flask on 0.0.0.0:80 for LAN access (e.g. from phone via Pi IP/hostname)
    app.run(host='0.0.0.0', port=80, debug=False, use_reloader=False)
