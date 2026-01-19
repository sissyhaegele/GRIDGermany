#!/bin/bash
# Quick Start: 3 Sensors
# Berliner Stadtwerke - Grid Monitoring

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Quick Start: 3 Sensors                                      ║"
echo "║  Berliner Stadtwerke                                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Solace Configuration
export SOLACE_HOST="mr-connection-gu0w0pjgchg.messaging.solace.cloud"
export SOLACE_PORT="8883"
export SOLACE_USERNAME="solace-cloud-client"
export SOLACE_PASSWORD="iejmgp94muv7m5ahsfe9b50dvb"

echo "🚀 Starting 3 sensors..."
echo ""

# Sensor 1: Mitte
echo "[1/3] Starting TRF-MIT-042 (Mitte)..."
export SENSOR_ID="TRF-MIT-042"
python3 remote_controlled_sensor.py > logs/sensor-mit-042.log 2>&1 &
sleep 1

# Sensor 2: Kreuzberg
echo "[2/3] Starting TRF-KRZ-021 (Kreuzberg)..."
export SENSOR_ID="TRF-KRZ-021"
python3 remote_controlled_sensor.py > logs/sensor-krz-021.log 2>&1 &
sleep 1

# Sensor 3: Charlottenburg
echo "[3/3] Starting TRF-CHA-015 (Charlottenburg)..."
export SENSOR_ID="TRF-CHA-015"
python3 remote_controlled_sensor.py > logs/sensor-cha-015.log 2>&1 &
sleep 1

echo ""
echo "✅ 3 sensors started!"
echo ""
echo "📊 Active Sensors:"
echo "  • TRF-MIT-042 (Berlin Mitte)"
echo "  • TRF-KRZ-021 (Berlin Kreuzberg)"
echo "  • TRF-CHA-015 (Berlin Charlottenburg)"
echo ""
echo "⚡ Event Rate: 1 event per second per sensor"
echo "⚡ Total Rate: 3 events per second"
echo ""
echo "📋 Logs in: logs/sensor-*.log"
echo "🛑 Stop all: ./stop-all-sensors.sh"
echo ""
