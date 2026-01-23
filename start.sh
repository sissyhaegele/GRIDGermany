#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# GRIDGermany - Sensor Startup Script
# Showcase: Berliner Stadtwerke (BS) - 100 Sensors
# 
# Features:
# - Round-robin distribution across all districts
# - Clean shutdown with proper MQTT disconnect
# - Signal handling for Ctrl+C
# ═══════════════════════════════════════════════════════════════

cd ~/Projekte/GRIDGermany

# Solace Cloud Credentials
export SOLACE_HOST="mr-connection-gu0w0pjgchg.messaging.solace.cloud"
export SOLACE_PORT="8883"
export SOLACE_USERNAME="solace-cloud-client"
export SOLACE_PASSWORD="iejmgp94muv7m5ahsfe9b50dvb"

# Track all child PIDs for clean shutdown
CHILD_PIDS=()

# ═══════════════════════════════════════════════════════════════
# CLEAN SHUTDOWN HANDLER
# ═══════════════════════════════════════════════════════════════
cleanup() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🛑 Stopping all sensors gracefully..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Send SIGTERM to all child processes (allows graceful shutdown)
    for pid in "${CHILD_PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid" 2>/dev/null
        fi
    done
    
    # Wait a moment for graceful disconnect
    echo "⏳ Waiting for clean MQTT disconnects..."
    sleep 2
    
    # Force kill any remaining processes
    for pid in "${CHILD_PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null
        fi
    done
    
    echo "✅ All sensors stopped."
    echo ""
    exit 0
}

# Trap Ctrl+C (SIGINT) and SIGTERM
trap cleanup SIGINT SIGTERM

# ═══════════════════════════════════════════════════════════════
# SENSOR LIST - Round Robin Order (matches fleet-control.html)
# ═══════════════════════════════════════════════════════════════
SENSORS=(
    # Round 1: 1 per district (10 sensors)
    "TRF-MIT-001" "TRF-KRZ-001" "TRF-CHA-001" "TRF-PRZ-001" "TRF-FRH-001"
    "TRF-NEU-001" "TRF-TMP-001" "TRF-SCH-001" "TRF-WED-001" "TRF-SPA-001"
    
    # Round 2: 2 per district (20 sensors total)
    "TRF-MIT-002" "TRF-KRZ-002" "TRF-CHA-002" "TRF-PRZ-002" "TRF-FRH-002"
    "TRF-NEU-002" "TRF-TMP-002" "TRF-SCH-002" "TRF-WED-002" "TRF-SPA-002"
    
    # Round 3: 3 per district (30 sensors total)
    "TRF-MIT-003" "TRF-KRZ-003" "TRF-CHA-003" "TRF-PRZ-003" "TRF-FRH-003"
    "TRF-NEU-003" "TRF-TMP-003" "TRF-SCH-003" "TRF-WED-003" "TRF-SPA-003"
    
    # Round 4: 4 per district (40 sensors total)
    "TRF-MIT-004" "TRF-KRZ-004" "TRF-CHA-004" "TRF-PRZ-004" "TRF-FRH-004"
    "TRF-NEU-004" "TRF-TMP-004" "TRF-SCH-004" "TRF-WED-004" "TRF-SPA-004"
    
    # Round 5: 5 per district (50 sensors total)
    "TRF-MIT-005" "TRF-KRZ-005" "TRF-CHA-005" "TRF-PRZ-005" "TRF-FRH-005"
    "TRF-NEU-005" "TRF-TMP-005" "TRF-SCH-005" "TRF-WED-005" "TRF-SPA-005"
    
    # Round 6: 6 per district (60 sensors total)
    "TRF-MIT-006" "TRF-KRZ-006" "TRF-CHA-006" "TRF-PRZ-006" "TRF-FRH-006"
    "TRF-NEU-006" "TRF-TMP-006" "TRF-SCH-006" "TRF-WED-006" "TRF-SPA-006"
    
    # Round 7-10: Remaining sensors (larger districts get more)
    "TRF-MIT-007" "TRF-KRZ-021" "TRF-CHA-015" "TRF-PRZ-031" "TRF-FRH-007"
    "TRF-NEU-007" "TRF-TMP-007" "TRF-SCH-007" "TRF-WED-007"
    
    "TRF-MIT-008" "TRF-KRZ-022" "TRF-CHA-016" "TRF-PRZ-032" "TRF-FRH-008"
    "TRF-NEU-008" "TRF-TMP-008" "TRF-SCH-008"
    
    "TRF-MIT-009" "TRF-KRZ-023" "TRF-CHA-017" "TRF-PRZ-033" "TRF-FRH-009"
    "TRF-NEU-009"
    
    "TRF-MIT-010" "TRF-KRZ-024" "TRF-CHA-018" "TRF-PRZ-034" "TRF-FRH-010"
    "TRF-NEU-010"
    
    # Remaining larger district sensors
    "TRF-MIT-042" "TRF-KRZ-025" "TRF-CHA-019" "TRF-PRZ-035"
    "TRF-MIT-043" "TRF-KRZ-026" "TRF-CHA-020" "TRF-PRZ-036"
    "TRF-MIT-044" "TRF-MIT-045" "TRF-MIT-046"
)

# ═══════════════════════════════════════════════════════════════
# MAIN MENU
# ═══════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ⚡ GRIDGermany - Sensor Starter                             ║"
echo "║  Showcase: Berliner Stadtwerke - 100 Sensors                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Wie viele Sensoren starten?"
echo ""
echo "  1)   1 Sensor   (1 Bezirk)"
echo "  3)   3 Sensoren (3 Bezirke)"
echo "  7)   7 Sensoren (7 Bezirke)"
echo "  10) 10 Sensoren (alle 10 Bezirke)"
echo "  25) 25 Sensoren (gleichmäßig verteilt)"
echo "  50) 50 Sensoren"
echo "  100) Alle 100 Sensoren"
echo ""
read -p "Auswahl [1/3/7/10/25/50/100]: " choice

# Determine how many sensors to start
case $choice in
    1)   count=1 ;;
    3)   count=3 ;;
    7)   count=7 ;;
    10)  count=10 ;;
    25)  count=25 ;;
    50)  count=50 ;;
    100) count=100 ;;
    *)   count=7 ;;
esac

echo ""
echo "🚀 Starte $count Sensor(en)..."
echo ""

# ═══════════════════════════════════════════════════════════════
# START SENSORS
# ═══════════════════════════════════════════════════════════════
started=0
for sensor in "${SENSORS[@]}"; do
    if [ $started -ge $count ]; then
        break
    fi
    
    echo "  [$((started+1))/$count] $sensor"
    SENSOR_ID="$sensor" python3 remote_controlled_sensor.py &
    CHILD_PIDS+=($!)
    
    started=$((started+1))
    
    # Small delay to avoid connection storms
    if [ $count -gt 20 ]; then
        sleep 0.2
    else
        sleep 0.3
    fi
done

echo ""
echo "✅ $count Sensor(en) gestartet!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📡 Sensoren warten auf START Command von Fleet Control"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "⚡ Event Rate nach Start: $count events/second"
echo ""
echo "🛑 Press Ctrl+C to stop all sensors (clean disconnect)"
echo ""

# ═══════════════════════════════════════════════════════════════
# WAIT FOR CHILD PROCESSES
# ═══════════════════════════════════════════════════════════════
# This keeps the script running and allows the trap to work
wait
