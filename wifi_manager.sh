#!/bin/bash

# NetworkManager Wi-Fi Check and Fallback Hotspot Script
# Useful for headless devices like a Raspberry Pi to allow
# configuring Wi-Fi when moving to a new network.

# Interface for Wi-Fi on Pi
INTERFACE="wlan0"
HOTSPOT_SSID="Ribs FlightWall"
HOTSPOT_PASSWORD="flightwall"

echo "Checking network connection status..."

# Wait a moment for NetworkManager to initialize on boot
sleep 10

# Check current connection state
# Options like: connected, disconnected, connecting
NM_STATE=$(nmcli -t -f STATE general)

if [[ "$NM_STATE" == "connected" ]]; then
    echo "Network is connected. Proceeding normally."
    # Optionally print current IP address
    IP_ADDRESS=$(ip -4 addr show $INTERFACE | grep -oP '(?<=inet\s)\d+(\.\d+){3}')
    echo "Current IP: $IP_ADDRESS"
    exit 0
else
    echo "Network is NOT connected. Current state: $NM_STATE"
    echo "Attempting to create a fallback Wi-Fi hotspot..."

    # Check if a hotspot connection profile already exists
    if nmcli connection show | grep -q "$HOTSPOT_SSID"; then
        echo "Hotspot profile exists. Bringing it up..."
        nmcli connection up "$HOTSPOT_SSID"
    else
        echo "Creating a new hotspot profile..."
        nmcli device wifi hotspot ifname $INTERFACE ssid "$HOTSPOT_SSID" password "$HOTSPOT_PASSWORD"
    fi
    
    # Check if hotspot creation was successful
    if [ $? -eq 0 ]; then
        echo "Hotspot '$HOTSPOT_SSID' started successfully."
        echo "Connect your device to this network and go to http://10.42.0.1" # default NM hotspot IP
    else
        echo "Failed to start the hotspot."
        exit 1
    fi
fi
