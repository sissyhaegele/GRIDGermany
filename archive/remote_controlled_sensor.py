#!/usr/bin/env python3
"""
Remote-Controlled Powerline Sensor
Berliner Stadtwerke - Mobile App gesteuert

Kann via MQTT Commands von deinem Smartphone gestartet/gestoppt werden:
- Start/Stop/Pause
- Live-Konfiguration ändern
- Status-Updates an App senden
"""

import json
import time
import threading
import os
from datetime import datetime
from power_sensor_simulator import PowerSensorSimulator
import paho.mqtt.client as mqtt


class RemoteControlledSensor:
    """Remote-controlled sensor that responds to MQTT commands"""
    
    def __init__(self, sensor_id, broker_host, broker_port=1883, 
                 username=None, password=None):
        self.sensor_id = sensor_id
        self.state = "stopped"  # stopped, running, paused, error
        
        # Default configuration
        self.config = {
            "district": "mitte",
            "voltageLevel": "mv",
            "assetType": "transformer",
            "samplingRateSeconds": 1,  # High frequency: 1 event per second
            "anomalyRatePercent": 2
        }
        
        # Initialize sensor simulator
        self.simulator = PowerSensorSimulator(
            sensor_id,
            self.config["district"],
            self.config["voltageLevel"],
            self.config["assetType"]
        )
        
        # Statistics
        self.stats = {
            "eventsPublished": 0,
            "startTime": None,
            "lastEventTime": None,
            "errors": 0
        }
        
        # MQTT Client setup (using callback API version 2)
        self.client = mqtt.Client(
            client_id=f"sensor-{sensor_id}-{int(time.time())}",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )
        if username and password:
            self.client.username_pw_set(username, password)
        
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        
        # Connection details
        self.broker_host = broker_host
        self.broker_port = broker_port
        
        # Enable TLS for secure connections (port 8883)
        if broker_port == 8883:
            import ssl
            self.client.tls_set(cert_reqs=ssl.CERT_NONE)
            self.client.tls_insecure_set(True)
            print("✓ TLS enabled for secure connection")
        self.connected = False
        
        # Threading
        self.publish_thread = None
        self.heartbeat_thread = None
        self.stop_event = threading.Event()
        
    def connect(self):
        """Connect to MQTT broker"""
        try:
            print(f"Connecting to {self.broker_host}:{self.broker_port}...")
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_start()
            
            # Wait for connection
            timeout = 10
            start = time.time()
            while not self.connected and (time.time() - start) < timeout:
                time.sleep(0.1)
            
            if not self.connected:
                raise Exception("Connection timeout")
            
            print("✓ Connected to Solace broker\n")
            return True
            
        except Exception as e:
            print(f"✗ Connection failed: {e}")
            self.state = "error"
            return False
    
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """Callback when connected to broker"""
        if rc == 0:
            self.connected = True
            
            # Subscribe to control commands for this sensor
            command_topic = f"control/sensor/{self.sensor_id}/command"
            self.client.subscribe(command_topic, qos=1)
            print(f"✓ Subscribed to commands: {command_topic}")
            
            # Publish online status
            self._publish_status("online", {
                "config": self.config,
                "capabilities": ["start", "stop", "pause", "configure"]
            })
            
            # Start heartbeat thread
            if not self.heartbeat_thread or not self.heartbeat_thread.is_alive():
                self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
                self.heartbeat_thread.start()
        else:
            print(f"✗ Connection failed with code {rc}")
            self.state = "error"
    
    def _on_disconnect(self, client, userdata, rc, properties=None):
        """Callback when disconnected"""
        self.connected = False
        if rc != 0:
            print(f"✗ Unexpected disconnection (code {rc})")
            self.state = "error"
    
    def _on_message(self, client, userdata, msg):
        """Handle incoming commands from mobile app"""
        try:
            payload = msg.payload.decode()
            command = json.loads(payload)
            
            print(f"\n📨 Command received: {json.dumps(command, indent=2)}")
            
            cmd_type = command.get("command")
            request_id = command.get("requestId", "unknown")
            
            # Execute command
            if cmd_type == "start":
                self.start(request_id)
            elif cmd_type == "stop":
                self.stop(request_id)
            elif cmd_type == "pause":
                duration = command.get("duration", 300)
                self.pause(duration, request_id)
            elif cmd_type == "configure":
                new_config = command.get("config", {})
                self.configure(new_config, request_id)
            elif cmd_type == "status":
                self._publish_status("heartbeat", request_id=request_id)
            else:
                print(f"✗ Unknown command: {cmd_type}")
                self._publish_status("error", {
                    "error": f"Unknown command: {cmd_type}",
                    "requestId": request_id
                })
                
        except json.JSONDecodeError as e:
            print(f"✗ Invalid JSON in command: {e}")
        except Exception as e:
            print(f"✗ Error handling command: {e}")
            self.stats["errors"] += 1
    
    def start(self, request_id=None):
        """Start generating and publishing sensor data"""
        if self.state == "running":
            print("⚠️  Sensor already running")
            self._publish_status("error", {
                "error": "Sensor already running",
                "requestId": request_id
            })
            return
        
        self.state = "running"
        self.stats["startTime"] = time.time()
        
        print(f"\n✓ Sensor STARTED")
        print(f"  Publishing to: bs/{self.config['district']}/{self.config['voltageLevel']}/...")
        print(f"  Interval: {self.config['samplingRateSeconds']} seconds\n")
        
        self._publish_status("started", {"requestId": request_id})
        
        # Start publishing thread
        self.stop_event.clear()
        self.publish_thread = threading.Thread(target=self._publish_loop, daemon=True)
        self.publish_thread.start()
    
    def stop(self, request_id=None):
        """Stop sensor"""
        if self.state == "stopped":
            print("⚠️  Sensor already stopped")
            return
        
        previous_state = self.state
        self.state = "stopped"
        self.stop_event.set()
        
        print(f"\n✓ Sensor STOPPED")
        
        self._publish_status("stopped", {
            "requestId": request_id,
            "totalEvents": self.stats["eventsPublished"],
            "previousState": previous_state
        })
    
    def pause(self, duration, request_id=None):
        """Pause sensor for specified duration"""
        if self.state != "running":
            print("⚠️  Can only pause running sensor")
            self._publish_status("error", {
                "error": "Sensor not running",
                "requestId": request_id
            })
            return
        
        self.state = "paused"
        print(f"\n⏸️  Sensor PAUSED for {duration} seconds")
        
        self._publish_status("paused", {
            "requestId": request_id,
            "duration": duration,
            "resumeAt": time.time() + duration
        })
        
        # Schedule resume
        def resume_after_pause():
            time.sleep(duration)
            if self.state == "paused":
                self.state = "running"
                print(f"\n▶️  Sensor RESUMED")
                self._publish_status("resumed", {"requestId": request_id})
        
        threading.Thread(target=resume_after_pause, daemon=True).start()
    
    def configure(self, new_config, request_id=None):
        """Apply new configuration"""
        print(f"\n🔧 Applying new configuration:")
        
        was_running = self.state == "running"
        
        # Temporarily stop if running
        if was_running:
            self.stop_event.set()
            time.sleep(0.5)
        
        # Update configuration
        old_config = self.config.copy()
        self.config.update(new_config)
        
        # Recreate simulator with new settings
        try:
            self.simulator = PowerSensorSimulator(
                self.sensor_id,
                self.config["district"],
                self.config["voltageLevel"],
                self.config["assetType"]
            )
            
            # Show what changed
            for key, value in new_config.items():
                old_value = old_config.get(key)
                if old_value != value:
                    print(f"  {key}: {old_value} → {value}")
            
            self._publish_status("configured", {
                "requestId": request_id,
                "config": self.config,
                "changes": new_config
            })
            
            # Restart if was running
            if was_running:
                self.stop_event.clear()
                self.publish_thread = threading.Thread(target=self._publish_loop, daemon=True)
                self.publish_thread.start()
                print(f"  Restarted with new configuration")
            
            print(f"✓ Configuration applied successfully\n")
            
        except Exception as e:
            print(f"✗ Configuration failed: {e}")
            self.config = old_config  # Rollback
            self._publish_status("error", {
                "error": f"Configuration failed: {str(e)}",
                "requestId": request_id
            })
    
    def _publish_loop(self):
        """Main loop for publishing sensor data"""
        heartbeat_interval = 30
        last_heartbeat = 0
        
        while not self.stop_event.is_set():
            if self.state == "running":
                try:
                    current_time = time.time()
                    
                    # Generate and publish status update
                    reading = self.simulator.generate_reading()
                    data_topic = (
                        f"bs/{self.config['district']}/"
                        f"{self.config['voltageLevel']}/"
                        f"{self.config['assetType']}/"
                        f"powerline/statusUpdated/v1/{self.sensor_id}"
                    )
                    
                    self.client.publish(data_topic, json.dumps(reading), qos=1)
                    self.stats["eventsPublished"] += 1
                    self.stats["lastEventTime"] = current_time
                    
                    # Print status
                    status_icon = "⚠️ " if reading['status'] == 'anomaly' else "✓ "
                    power = reading['measurements']['power']['active']
                    temp = reading['measurements']['temperature']
                    print(f"{status_icon}Event #{self.stats['eventsPublished']}: "
                          f"Power={power:.1f}kW, Temp={temp:.1f}°C")
                    
                    # Publish heartbeat periodically
                    if current_time - last_heartbeat >= heartbeat_interval:
                        heartbeat = self.simulator.generate_heartbeat()
                        # Add sensor statistics to heartbeat
                        heartbeat['eventsPublished'] = self.stats['eventsPublished']
                        heartbeat['uptime'] = int(current_time - self.stats['startTime']) if self.stats['startTime'] else 0
                        
                        hb_topic = (
                            f"bs/{self.config['district']}/"
                            f"{self.config['voltageLevel']}/"
                            f"{self.config['assetType']}/"
                            f"powerline/heartbeat/v1/{self.sensor_id}"
                        )
                        
                        self.client.publish(hb_topic, json.dumps(heartbeat), qos=1)
                        print(f"💓 Heartbeat sent")
                        last_heartbeat = current_time
                    
                    # Wait for configured interval
                    time.sleep(self.config["samplingRateSeconds"])
                    
                except Exception as e:
                    print(f"✗ Error in publish loop: {e}")
                    self.stats["errors"] += 1
                    time.sleep(1)
            else:
                # Paused or other state - just wait
                time.sleep(1)
    
    def _heartbeat_loop(self):
        """Send status heartbeat every 30 seconds"""
        while True:
            time.sleep(30)
            if self.connected and self.state != "stopped":
                self._publish_status("heartbeat")
    
    def _publish_status(self, status, extra_data=None, request_id=None):
        """Publish sensor status to control plane"""
        topic = f"control/sensor/{self.sensor_id}/status"
        
        payload = {
            "status": status,
            "sensorId": self.sensor_id,
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "state": self.state
        }
        
        if request_id:
            payload["requestId"] = request_id
        
        # Add statistics for heartbeat
        if status == "heartbeat":
            uptime = int(time.time() - self.stats["startTime"]) if self.stats["startTime"] else 0
            payload.update({
                "eventsPublished": self.stats["eventsPublished"],
                "uptime": uptime,
                "config": self.config,
                "errors": self.stats["errors"]
            })
        
        # Add any extra data
        if extra_data:
            payload.update(extra_data)
        
        self.client.publish(topic, json.dumps(payload), qos=1)
        
        if status not in ["heartbeat"]:
            print(f"📤 Status: {status}")
    
    def disconnect(self):
        """Disconnect from broker"""
        self.stop()
        self._publish_status("offline")
        time.sleep(0.5)
        self.client.loop_stop()
        self.client.disconnect()
        print("\n✓ Disconnected from broker")


def main():
    """Main entry point"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║  Remote-Controlled Powerline Sensor                          ║
║  Berliner Stadtwerke - Mobile App Control                    ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    # Configuration from environment or prompts
    SENSOR_ID = os.getenv('SENSOR_ID') or input("Sensor ID (z.B. TRF-MIT-042): ").strip()
    BROKER_HOST = os.getenv('SOLACE_HOST', 'localhost')
    BROKER_PORT = int(os.getenv('SOLACE_PORT', '1883'))
    USERNAME = os.getenv('SOLACE_USERNAME')
    PASSWORD = os.getenv('SOLACE_PASSWORD')
    
    print(f"\n✓ Configuration:")
    print(f"  Sensor ID: {SENSOR_ID}")
    print(f"  Broker: {BROKER_HOST}:{BROKER_PORT}")
    print(f"  Username: {USERNAME or '(none)'}")
    print()
    
    # Create and connect sensor
    sensor = RemoteControlledSensor(
        SENSOR_ID,
        BROKER_HOST,
        BROKER_PORT,
        USERNAME,
        PASSWORD
    )
    
    if not sensor.connect():
        print("\n✗ Failed to connect to broker")
        return
    
    print(f"✓ Sensor '{SENSOR_ID}' initialized and ready")
    print(f"\n📱 Control from your mobile app:")
    print(f"  Publish commands to: control/sensor/{SENSOR_ID}/command")
    print(f"\n  Commands:")
    print(f"    {{'command': 'start'}}")
    print(f"    {{'command': 'stop'}}")
    print(f"    {{'command': 'pause', 'duration': 300}}")
    print(f"    {{'command': 'configure', 'config': {{'samplingRateSeconds': 5}}}}")
    print(f"\n📊 Status updates published to: control/sensor/{SENSOR_ID}/status")
    print(f"\n  Press Ctrl+C to exit\n")
    print("="*60)
    
    # Keep running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n✓ Shutting down gracefully...")
        sensor.disconnect()
        print("✓ Goodbye!\n")


if __name__ == '__main__':
    main()
