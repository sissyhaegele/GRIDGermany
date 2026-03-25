#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# BS GRID - Sensor Startup Script (Autostart)
# Berliner Stadtwerke POC
# ═══════════════════════════════════════════════════════════════

cd ~/Projekte/GRIDGermany

# All Sensor IDs (Round-Robin über 10 Distrikte)
ALL_SENSORS=(
    "TRF-MIT-001" "TRF-KRZ-001" "TRF-CHA-001" "TRF-PRZ-001" "TRF-FRH-001"
    "TRF-NEU-001" "TRF-TMP-001" "TRF-SCH-001" "TRF-WED-001" "TRF-SPA-001"
    "TRF-MIT-002" "TRF-KRZ-002" "TRF-CHA-002" "TRF-PRZ-002" "TRF-FRH-002"
    "TRF-NEU-002" "TRF-TMP-002" "TRF-SCH-002" "TRF-WED-002" "TRF-SPA-002"
    "TRF-MIT-003" "TRF-KRZ-003" "TRF-CHA-003" "TRF-PRZ-003" "TRF-FRH-003"
    "TRF-NEU-003" "TRF-TMP-003" "TRF-SCH-003" "TRF-WED-003" "TRF-SPA-003"
    "TRF-MIT-004" "TRF-KRZ-004" "TRF-CHA-004" "TRF-PRZ-004" "TRF-FRH-004"
    "TRF-NEU-004" "TRF-TMP-004" "TRF-SCH-004" "TRF-WED-004" "TRF-SPA-004"
    "TRF-MIT-005" "TRF-KRZ-005" "TRF-CHA-005" "TRF-PRZ-005" "TRF-FRH-005"
    "TRF-NEU-005" "TRF-TMP-005" "TRF-SCH-005" "TRF-WED-005" "TRF-SPA-005"
    "TRF-MIT-006" "TRF-KRZ-006" "TRF-CHA-006" "TRF-PRZ-006" "TRF-FRH-006"
    "TRF-NEU-006" "TRF-TMP-006" "TRF-SCH-006" "TRF-WED-006" "TRF-SPA-006"
    "TRF-MIT-007" "TRF-KRZ-007" "TRF-CHA-007" "TRF-PRZ-007" "TRF-FRH-007"
    "TRF-NEU-007" "TRF-TMP-007" "TRF-SCH-007" "TRF-WED-007" "TRF-SPA-007"
    "TRF-MIT-008" "TRF-KRZ-008" "TRF-CHA-008" "TRF-PRZ-008" "TRF-FRH-008"
    "TRF-NEU-008" "TRF-TMP-008" "TRF-SCH-008" "TRF-WED-008" "TRF-SPA-008"
    "TRF-MIT-009" "TRF-KRZ-009" "TRF-CHA-009" "TRF-PRZ-009" "TRF-FRH-009"
    "TRF-NEU-009" "TRF-TMP-009" "TRF-SCH-009" "TRF-WED-009" "TRF-SPA-009"
    "TRF-MIT-010" "TRF-KRZ-010" "TRF-CHA-010" "TRF-PRZ-010" "TRF-FRH-010"
    "TRF-NEU-010" "TRF-TMP-010" "TRF-SCH-010" "TRF-WED-010" "TRF-SPA-010"
)

PIDS=()

cleanup() {
    echo ""
    echo "🛑 Stopping all sensors gracefully..."
    for pid in "${PIDS[@]}"; do
        kill -SIGTERM "$pid" 2>/dev/null
    done
    echo "⏳ Waiting for clean MQTT disconnects..."
    sleep 2
    for pid in "${PIDS[@]}"; do
        kill -SIGKILL "$pid" 2>/dev/null
    done
    echo "✅ All sensors stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ⚡ BS GRID - Sensor Starter                                 ║"
echo "║  Berliner Stadtwerke - Autostart Mode                        ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Wie viele Sensoren starten?"
echo ""
echo "  1)   1 Sensor"
echo "  2)   7 Sensoren"
echo "  3)  10 Sensoren"
echo "  4)  25 Sensoren"
echo "  5)  50 Sensoren"
echo "  6) 100 Sensoren"
echo ""
read -p "Auswahl [1-6]: " choice

case $choice in
    1) COUNT=1 ;;
    2) COUNT=7 ;;
    3) COUNT=10 ;;
    4) COUNT=25 ;;
    5) COUNT=50 ;;
    6) COUNT=100 ;;
    *) echo "Ungültige Auswahl"; exit 1 ;;
esac

echo ""
echo "🚀 Starte $COUNT Sensoren..."
echo ""

for i in $(seq 0 $((COUNT - 1))); do
    SENSOR_ID="${ALL_SENSORS[$i]}"
    SENSOR_ID="$SENSOR_ID" python3 remote_controlled_sensor.py --autostart > /dev/null 2>&1 &
    PIDS+=($!)
    echo "  ✅ $SENSOR_ID gestartet (PID: ${PIDS[-1]})"
    sleep 0.1
done

echo ""
echo "✅ $COUNT Sensoren laufen. Ctrl+C zum Beenden."
echo ""

wait
