#!/usr/bin/env python3
"""
Multi-Sensor Startup Script
Starts multiple sensors in parallel based on Event Mesh design

Berliner Stadtwerke - Grid Monitoring
"""

import subprocess
import sys
import time
import signal
import os

# Sensor Configuration based on Event Mesh
SENSORS = [
    # Berlin Mitte - Transformers
    {
        "id": "TRF-MIT-042",
        "district": "mitte",
        "voltage": "mv",
        "asset": "transformer",
        "name": "Transformer Mitte 042"
    },
    {
        "id": "TRF-MIT-043",
        "district": "mitte",
        "voltage": "mv",
        "asset": "transformer",
        "name": "Transformer Mitte 043"
    },
    {
        "id": "TRF-MIT-044",
        "district": "mitte",
        "voltage": "mv",
        "asset": "transformer",
        "name": "Transformer Mitte 044"
    },
    
    # Berlin Kreuzberg - Transformers
    {
        "id": "TRF-KRZ-021",
        "district": "kreuzberg",
        "voltage": "mv",
        "asset": "transformer",
        "name": "Transformer Kreuzberg 021"
    },
    {
        "id": "TRF-KRZ-022",
        "district": "kreuzberg",
        "voltage": "mv",
        "asset": "transformer",
        "name": "Transformer Kreuzberg 022"
    },
    
    # Berlin Charlottenburg - Transformers
    {
        "id": "TRF-CHA-015",
        "district": "charlottenburg",
        "voltage": "mv",
        "asset": "transformer",
        "name": "Transformer Charlottenburg 015"
    },
    
    # Berlin Prenzlauer Berg - Transformers
    {
        "id": "TRF-PRZ-031",
        "district": "prenzlauer-berg",
        "voltage": "mv",
        "asset": "transformer",
        "name": "Transformer Prenzlauer Berg 031"
    },
]

# Solace Configuration
SOLACE_CONFIG = {
    "host": "mr-connection-gu0w0pjgchg.messaging.solace.cloud",
    "port": "8883",
    "username": "solace-cloud-client",
    "password": "iejmgp94muv7m5ahsfe9b50dvb"
}

processes = []

def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    print("\n\n🛑 Stopping all sensors...")
    for process in processes:
        process.terminate()
    print("✓ All sensors stopped")
    sys.exit(0)

def start_sensor(sensor):
    """Start a single sensor process"""
    env = os.environ.copy()
    env.update({
        'SOLACE_HOST': SOLACE_CONFIG['host'],
        'SOLACE_PORT': SOLACE_CONFIG['port'],
        'SOLACE_USERNAME': SOLACE_CONFIG['username'],
        'SOLACE_PASSWORD': SOLACE_CONFIG['password'],
        'SENSOR_ID': sensor['id']
    })
    
    process = subprocess.Popen(
        ['python3', 'remote_controlled_sensor.py'],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    return process

def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  Multi-Sensor Grid Monitoring System                        ║")
    print("║  Berliner Stadtwerke                                         ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    
    # Register signal handler
    signal.signal(signal.SIGINT, signal_handler)
    
    print(f"🚀 Starting {len(SENSORS)} sensors...\n")
    
    # Start all sensors
    for i, sensor in enumerate(SENSORS, 1):
        print(f"[{i}/{len(SENSORS)}] Starting {sensor['name']} ({sensor['id']})...")
        process = start_sensor(sensor)
        processes.append(process)
        time.sleep(0.5)  # Small delay between starts
    
    print()
    print("✅ All sensors started!")
    print()
    print("📊 Active Sensors:")
    for sensor in SENSORS:
        district = sensor['district'].replace('-', ' ').title()
        print(f"  • {sensor['id']} - {district}")
    
    print()
    print("📡 Publishing to topics:")
    print(f"  bs/{{district}}/mv/transformer/powerline/statusUpdated/v1/{{sensor_id}}")
    print()
    print("⚡ Event Rate: 1 event per second per sensor")
    print(f"⚡ Total Rate: {len(SENSORS)} events per second")
    print()
    print("💡 Use Control App or CLI to control sensors")
    print("🛑 Press Ctrl+C to stop all sensors")
    print()
    
    # Keep running
    try:
        while True:
            time.sleep(1)
            # Check if any process has died
            for i, process in enumerate(processes):
                if process.poll() is not None:
                    print(f"⚠️  Sensor {SENSORS[i]['id']} has stopped")
    except KeyboardInterrupt:
        signal_handler(None, None)

if __name__ == '__main__':
    main()
