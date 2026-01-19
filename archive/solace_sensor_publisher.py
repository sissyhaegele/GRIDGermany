#!/usr/bin/env python3
"""
Berliner Stadtwerke Power Sensor Simulator - Solace Edition
Simulates realistic power grid sensor data and publishes to Solace PubSub+ broker
"""

import json
import time
import os
import paho.mqtt.client as mqtt
from power_sensor_simulator import PowerSensorSimulator

class SolaceSensorPublisher:
    """Publishes sensor data to Solace PubSub+ via MQTT"""
    
    def __init__(self, broker_host: str, broker_port: int = 1883,
                 username: str = None, password: str = None):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.username = username
        self.password = password
        self.client = None
        self.connected = False
        
    def connect(self):
        """Connect to Solace broker via MQTT"""
        self.client = mqtt.Client(client_id=f"sensor-{int(time.time())}")
        
        if self.username and self.password:
            self.client.username_pw_set(self.username, self.password)
        
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        
        print(f"Connecting to Solace broker at {self.broker_host}:{self.broker_port}...")
        self.client.connect(self.broker_host, self.broker_port, 60)
        self.client.loop_start()
        
        # Wait for connection
        timeout = 10
        start = time.time()
        while not self.connected and (time.time() - start) < timeout:
            time.sleep(0.1)
        
        if not self.connected:
            raise Exception("Failed to connect to Solace broker")
        
        print("✓ Connected to Solace broker")
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected"""
        if rc == 0:
            self.connected = True
            print("✓ MQTT connection established")
        else:
            print(f"✗ Connection failed with code {rc}")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected"""
        self.connected = False
        if rc != 0:
            print(f"✗ Unexpected disconnection (code {rc})")
    
    def publish(self, topic: str, payload: dict):
        """Publish a message to Solace"""
        if not self.connected:
            print("✗ Not connected to broker")
            return False
        
        json_payload = json.dumps(payload)
        result = self.client.publish(topic, json_payload, qos=1)
        
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            return True
        else:
            print(f"✗ Publish failed: {result.rc}")
            return False
    
    def disconnect(self):
        """Disconnect from broker"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            print("✓ Disconnected from Solace broker")


def run_solace_sensor(sensor_id: str, district: str, voltage_level: str,
                     asset_type: str, broker_host: str,
                     duration_seconds: int = 300,
                     username: str = None, password: str = None):
    """
    Run a sensor simulation publishing to Solace
    
    Args:
        sensor_id: Sensor identifier (e.g., 'SUB-MIT-001')
        district: Berlin district (e.g., 'mitte')
        voltage_level: 'hv', 'mv', or 'lv'
        asset_type: 'substation', 'transformer', etc.
        broker_host: Solace broker hostname
        duration_seconds: How long to run simulation
        username: MQTT username (optional)
        password: MQTT password (optional)
    """
    
    # Create sensor simulator
    sensor = PowerSensorSimulator(sensor_id, district, voltage_level, asset_type)
    
    # Create Solace publisher
    publisher = SolaceSensorPublisher(broker_host, username=username, password=password)
    
    try:
        # Connect to Solace
        publisher.connect()
        
        print(f"\n{'='*60}")
        print(f"Sensor: {sensor_id}")
        print(f"Location: {district}, Voltage: {voltage_level}, Asset: {asset_type}")
        print(f"Duration: {duration_seconds} seconds")
        print(f"{'='*60}\n")
        
        heartbeat_interval = 30  # seconds
        status_interval = 5      # seconds
        
        start_time = time.time()
        last_heartbeat = 0
        last_status = 0
        message_count = 0
        
        while (time.time() - start_time) < duration_seconds:
            current_time = time.time()
            
            # Send heartbeat every 30 seconds
            if current_time - last_heartbeat >= heartbeat_interval:
                heartbeat = sensor.generate_heartbeat()
                topic = f"bs/{district}/{voltage_level}/{asset_type}/powerline/heartbeat/v1/{sensor_id}"
                
                if publisher.publish(topic, heartbeat):
                    message_count += 1
                    print(f"✓ [{message_count}] HEARTBEAT → {topic}")
                
                last_heartbeat = current_time
            
            # Send status update every 5 seconds
            if current_time - last_status >= status_interval:
                reading = sensor.generate_reading()
                topic = f"bs/{district}/{voltage_level}/{asset_type}/powerline/statusUpdated/v1/{sensor_id}"
                
                if publisher.publish(topic, reading):
                    message_count += 1
                    status_icon = "⚠️ " if reading['status'] == 'anomaly' else "✓ "
                    print(f"{status_icon}[{message_count}] STATUS → {topic}")
                    
                    # Show key metrics
                    m = reading['measurements']
                    print(f"    Voltage: {m['voltage']['l1']:.0f}V | "
                          f"Current: {m['current']['l1']:.1f}A | "
                          f"Power: {m['power']['active']:.1f}{m['power']['active_unit']} | "
                          f"Temp: {m['temperature']:.1f}°C")
                    
                    # Highlight anomalies
                    if reading['status'] == 'anomaly':
                        print(f"    ⚠️  ANOMALY: {reading['anomalyDetails']['type']}")
                
                last_status = current_time
            
            time.sleep(1)
        
        print(f"\n{'='*60}")
        print(f"✓ Simulation complete: {message_count} messages published")
        print(f"{'='*60}\n")
        
    except KeyboardInterrupt:
        print("\n⚠️  Simulation stopped by user")
    except Exception as e:
        print(f"\n✗ Error: {e}")
    finally:
        publisher.disconnect()


if __name__ == '__main__':
    import sys
    
    # Configuration
    BROKER_HOST = os.getenv('SOLACE_HOST', 'localhost')
    BROKER_PORT = int(os.getenv('SOLACE_PORT', '1883'))
    USERNAME = os.getenv('SOLACE_USERNAME', None)
    PASSWORD = os.getenv('SOLACE_PASSWORD', None)
    
    print("""
╔══════════════════════════════════════════════════════════════╗
║  Berliner Stadtwerke Power Sensor Simulator - Solace Edition ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    # Example scenarios
    print("Select a sensor scenario:")
    print("1. Medium Voltage Transformer in Mitte (default)")
    print("2. High Voltage Substation in Spandau")
    print("3. Low Voltage Distribution in Pankow")
    print("4. Custom sensor")
    
    choice = input("\nChoice [1-4] (default: 1): ").strip() or "1"
    
    scenarios = {
        "1": {
            "sensor_id": "TRF-MIT-042",
            "district": "mitte",
            "voltage_level": "mv",
            "asset_type": "transformer"
        },
        "2": {
            "sensor_id": "SUB-SPN-001",
            "district": "spandau",
            "voltage_level": "hv",
            "asset_type": "substation"
        },
        "3": {
            "sensor_id": "DL-PAN-156",
            "district": "pankow",
            "voltage_level": "lv",
            "asset_type": "distribution-line"
        }
    }
    
    if choice in scenarios:
        config = scenarios[choice]
    else:
        config = {
            "sensor_id": input("Sensor ID: "),
            "district": input("District (e.g., mitte): "),
            "voltage_level": input("Voltage level (hv/mv/lv): "),
            "asset_type": input("Asset type (substation/transformer/etc): ")
        }
    
    duration = int(input("\nDuration in seconds (default: 120): ").strip() or "120")
    
    print(f"\n✓ Configuration:")
    print(f"  Broker: {BROKER_HOST}:{BROKER_PORT}")
    print(f"  Sensor: {config['sensor_id']}")
    print(f"  Location: {config['district']}")
    print(f"  Type: {config['voltage_level']} {config['asset_type']}")
    print(f"  Duration: {duration}s")
    
    input("\nPress Enter to start simulation...")
    
    # Run simulation
    run_solace_sensor(
        sensor_id=config['sensor_id'],
        district=config['district'],
        voltage_level=config['voltage_level'],
        asset_type=config['asset_type'],
        broker_host=BROKER_HOST,
        duration_seconds=duration,
        username=USERNAME,
        password=PASSWORD
    )
