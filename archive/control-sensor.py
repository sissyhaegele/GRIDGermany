#!/usr/bin/env python3
"""
Simple Sensor Control - Works on Windows/Mac/Linux
Sendet Commands an Remote-Controlled Sensor
"""

import paho.mqtt.client as mqtt
import json
import time
import sys

# Configuration
BROKER = "mr-connection-gu0w0pjgchg.messaging.solace.cloud"
PORT = 8883  # TLS/SSL port
USERNAME = "solace-cloud-client"
PASSWORD = "iejmgp94muv7m5ahsfe9b50dvb"
SENSOR_ID = "TRF-MIT-042"

def send_command(command, duration=None):
    """Send command to sensor"""
    
    # Create payload
    payload = {
        "command": command,
        "requestId": f"req-{int(time.time())}"
    }
    
    if duration:
        payload["duration"] = duration
    
    topic = f"control/sensor/{SENSOR_ID}/command"
    
    print(f"→ Sending command: {command}")
    print(f"  Topic: {topic}")
    print(f"  Payload: {json.dumps(payload)}")
    
    # Create MQTT client (using callback API version 2)
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(USERNAME, PASSWORD)
    
    # Enable TLS for port 8883
    if PORT == 8883:
        import ssl
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)
    
    connected = False
    
    def on_connect(client, userdata, flags, rc, properties=None):
        nonlocal connected
        connected = (rc == 0)
        if rc == 0:
            print("  ✓ Connected to broker")
        else:
            print(f"  ✗ Connection failed: {rc}")
    
    client.on_connect = on_connect
    
    try:
        # Connect
        print("  Connecting to broker...")
        client.connect(BROKER, PORT, 60)
        client.loop_start()
        
        # Wait for connection
        timeout = 5
        start = time.time()
        while not connected and (time.time() - start) < timeout:
            time.sleep(0.1)
        
        if not connected:
            print("  ✗ Connection timeout")
            return False
        
        # Publish
        result = client.publish(topic, json.dumps(payload), qos=1)
        
        # Wait for publish to complete
        result.wait_for_publish()
        
        if result.rc == 0:
            print("✓ Command sent successfully!")
            time.sleep(0.5)  # Give time for message to be sent
            return True
        else:
            print(f"✗ Failed to send command: {result.rc}")
            return False
            
    except Exception as e:
        print(f"✗ Error: {e}")
        return False
    finally:
        client.loop_stop()
        client.disconnect()

def main():
    """Main menu"""
    
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  Sensor Control - Command Line                               ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print(f"Sensor: {SENSOR_ID}")
    print(f"Broker: {BROKER}")
    print()
    
    while True:
        print("Commands:")
        print("  1) START sensor")
        print("  2) STOP sensor")
        print("  3) PAUSE sensor (5 minutes)")
        print("  4) Exit")
        print()
        
        choice = input("Choose [1-4]: ").strip()
        
        if choice == "1":
            send_command("start")
        elif choice == "2":
            send_command("stop")
        elif choice == "3":
            send_command("pause", duration=300)
        elif choice == "4":
            print("\nGoodbye!")
            sys.exit(0)
        else:
            print("Invalid choice!")
        
        print()

if __name__ == '__main__':
    main()