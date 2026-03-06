#!/bin/bash
# Install flightwall systemd service on Raspberry Pi
# Run from the project directory: ./install.sh

set -e

SERVICE_NAME="flightwall"
SERVICE_FILE="flightwall.service"
SYSTEMD_DIR="/etc/systemd/system"

# Get the directory where the script lives (project root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_SRC="${SCRIPT_DIR}/${SERVICE_FILE}"

if [[ ! -f "$SERVICE_SRC" ]]; then
    echo "Error: $SERVICE_FILE not found in $SCRIPT_DIR"
    exit 1
fi

echo "Installing ${SERVICE_NAME} service..."
sudo cp "$SERVICE_SRC" "${SYSTEMD_DIR}/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}.service"
sudo systemctl start "${SERVICE_NAME}.service"

echo "Done. Service status:"
sudo systemctl status "${SERVICE_NAME}.service"
