#!/usr/bin/env python3
"""
GRIDGermany - Remote Controlled Sensor
Showcase: Berliner Stadtwerke (BS)

Simuliert einen Transformator-Sensor mit Grid-KPIs
- Empfängt Befehle über MQTT (control/sensor/{id}/command)
- Sendet Daten über MQTT an Topic: bs/{district}/mv/transformer/powerline/statusUpdated/{sensorId}
- Sendet Alarme (für Joule Agent) an: bs/{district}/mv/transformer/powerline/alarmRaised/{sensorId}

Verbesserungen v2:
- Clean Session für saubere Reconnects
- Last Will & Testament für automatische Offline-Erkennung
- Graceful Shutdown mit Signal Handling
- Verbesserte Reconnection-Logik
"""

import paho.mqtt.client as mqtt
import json
import time
import random
import threading
import os
import sys
import signal
from collections import deque
from datetime import datetime

# ============================================
# CONFIGURATION (neue Credentials!)
# ============================================

# Broker settings - NEUE SERVICE ID
BROKER = os.getenv('SOLACE_HOST', 'mr-connection-gu0w0pjgchg.messaging.solace.cloud')
PORT = int(os.getenv('SOLACE_PORT', 8883))
USERNAME = os.getenv('SOLACE_USERNAME', 'solace-cloud-client')
PASSWORD = os.getenv('SOLACE_PASSWORD', 'iejmgp94muv7m5ahsfe9b50dvb')

# Sensor settings
SENSOR_ID = os.getenv('SENSOR_ID', 'TRF-MIT-042')
DISTRICT = os.getenv('DISTRICT', 'mitte')

# Location data per district
DISTRICT_LOCATIONS = {
    'mitte': {'lat': 52.5200, 'lon': 13.4050, 'address': 'Alexanderplatz'},
    'kreuzberg': {'lat': 52.4970, 'lon': 13.4070, 'address': 'Kottbusser Tor'},
    'charlottenburg': {'lat': 52.5160, 'lon': 13.3040, 'address': 'Savignyplatz'},
    'prenzlauer berg': {'lat': 52.5380, 'lon': 13.4240, 'address': 'Schönhauser Allee'},
    'friedrichshain': {'lat': 52.5150, 'lon': 13.4540, 'address': 'Warschauer Straße'},
    'neukoelln': {'lat': 52.4810, 'lon': 13.4350, 'address': 'Hermannplatz'},
    'tempelhof': {'lat': 52.4700, 'lon': 13.4030, 'address': 'Tempelhofer Feld'},
    'schoeneberg': {'lat': 52.4830, 'lon': 13.3530, 'address': 'Nollendorfplatz'},
    'wedding': {'lat': 52.5510, 'lon': 13.3590, 'address': 'Leopoldplatz'},
    'spandau': {'lat': 52.5350, 'lon': 13.2000, 'address': 'Altstadt Spandau'}
}

# ============================================
# SENSOR CLASS
# ============================================

class RemoteControlledSensor:
    def __init__(self, sensor_id, district):
        self.sensor_id = sensor_id
        self.district = district.lower()
        self.running = False
        self.paused = False
        self.pause_until = 0
        self.client = None
        self.connected = False
        self.start_time = None
        self.total_messages = 0
        self.failed_messages = 0
        self.shutdown_requested = False
        
        # Simulated sensor values
        self.temperature = random.uniform(35, 50)
        
        # Grid KPIs
        self.voltage = random.uniform(228, 232)
        self.frequency = random.uniform(49.98, 50.02)
        self.load = random.uniform(50, 70)
        self.power = random.uniform(80, 120)
        
        # Topics
        self.data_topic = f"bs/{self.district}/mv/transformer/powerline/statusUpdated/{self.sensor_id}"
        self.alarm_topic = f"bs/{self.district}/mv/transformer/powerline/alarmRaised/{self.sensor_id}"
        self.command_topic = f"control/sensor/{self.sensor_id}/command"
        self.status_topic = f"control/sensor/{self.sensor_id}/status"

        # Rolling window of recent readings - sent as context with alarms
        self.metrics_history = deque(maxlen=10)

        # Active anomaly event (spike cooldown or gradual ramp), or None
        self.event = None
        
        # Location
        loc = DISTRICT_LOCATIONS.get(self.district, DISTRICT_LOCATIONS['mitte'])
        self.location = {
            'district': self.district,
            'lat': loc['lat'] + random.uniform(-0.01, 0.01),
            'lon': loc['lon'] + random.uniform(-0.01, 0.01),
            'address': loc['address']
        }
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        print(f"\n\n🛑 Received signal {signum}, shutting down gracefully...")
        self.shutdown_requested = True
        self.running = False
    
    def connect(self):
        """Connect to Solace broker via MQTT"""
        print(f"╔{'═'*60}╗")
        print(f"║  GRIDGermany Sensor - {self.sensor_id:<36} ║")
        print(f"╚{'═'*60}╝")
        print()
        print(f"📍 District: {self.district.title()}")
        print(f"📡 Broker: {BROKER}:{PORT}")
        print(f"📤 Data Topic: {self.data_topic}")
        print(f"📥 Command Topic: {self.command_topic}")
        print()
        
        # Create MQTT client with CLEAN SESSION
        client_id = f"sensor-{self.sensor_id}-{int(time.time())}"
        
        try:
            # Try new paho-mqtt API (v2.x)
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id,
                clean_session=True  # WICHTIG: Clean Session!
            )
        except (AttributeError, TypeError):
            # Fallback for older paho-mqtt (v1.x)
            self.client = mqtt.Client(
                client_id=client_id,
                clean_session=True
            )
        
        self.client.username_pw_set(USERNAME, PASSWORD)
        
        # Enable TLS
        import ssl
        self.client.tls_set(cert_reqs=ssl.CERT_NONE)
        self.client.tls_insecure_set(True)
        
        # Last Will & Testament - wird automatisch gesendet wenn Verbindung abbricht
        lwt_payload = json.dumps({
            'sensorId': self.sensor_id,
            'status': 'offline',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'reason': 'unexpected_disconnect'
        })
        self.client.will_set(self.status_topic, lwt_payload, qos=1, retain=False)
        
        # Callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        
        try:
            print("🔌 Connecting to broker...")
            self.client.connect(BROKER, PORT, keepalive=30)
            self.client.loop_start()
            
            # Wait for connection
            timeout = 10
            start = time.time()
            while not self.connected and (time.time() - start) < timeout:
                time.sleep(0.1)
            
            if not self.connected:
                print("❌ Connection timeout!")
                return False
                
            return True
            
        except Exception as e:
            print(f"❌ Connection error: {e}")
            return False
    
    def _on_connect(self, client, userdata, flags, rc, *args):
        """Called when connected to broker - compatible with paho v1 and v2"""
        # Handle different paho-mqtt versions
        if isinstance(rc, int):
            reason_code = rc
        else:
            # paho v2 returns ReasonCode object
            reason_code = rc.value if hasattr(rc, 'value') else int(rc)
        
        if reason_code == 0:
            self.connected = True
            print("✅ Connected to Solace broker!")
            
            # Subscribe to command topic
            client.subscribe(self.command_topic, qos=1)
            print(f"📥 Subscribed to: {self.command_topic}")
            
            # Publish initial status
            self._publish_status('connected')
        else:
            error_messages = {
                1: "Incorrect protocol version",
                2: "Invalid client identifier",
                3: "Server unavailable",
                4: "Bad username or password",
                5: "Not authorized"
            }
            error_msg = error_messages.get(reason_code, f"Unknown error ({reason_code})")
            print(f"❌ Connection failed: {error_msg}")
    
    def _on_disconnect(self, client, userdata, *args):
        """Called when disconnected - compatible with paho v1 and v2"""
        self.connected = False
        
        # Extract reason code from args (different between paho versions)
        rc = 0
        if args:
            rc = args[0] if isinstance(args[0], int) else getattr(args[0], 'value', 0)
        
        if self.shutdown_requested:
            print("🔌 Disconnected (clean shutdown)")
        elif rc == 0:
            print("🔌 Disconnected (normal)")
        else:
            print(f"🔌 Disconnected unexpectedly (rc={rc})")
            # Reconnection wird automatisch von loop_start() versucht
    
    def _on_message(self, client, userdata, message):
        """Handle incoming command messages"""
        try:
            payload = json.loads(message.payload.decode())
            command = payload.get('command', '').lower()
            request_id = payload.get('requestId', 'unknown')
            
            print(f"\n📩 Command received: {command} (req: {request_id})")
            
            if command == 'start':
                self._handle_start()
            elif command == 'stop':
                self._handle_stop()
            elif command == 'pause':
                duration = payload.get('duration', 300)
                self._handle_pause(duration)
            else:
                print(f"⚠️ Unknown command: {command}")
                
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON: {e}")
        except Exception as e:
            print(f"❌ Command error: {e}")
    
    def _handle_start(self):
        """Start sending sensor data"""
        if self.running:
            print("ℹ️ Sensor already running")
            return
            
        self.running = True
        self.paused = False
        self.start_time = time.time()
        self.total_messages = 0
        self.failed_messages = 0
        
        print("▶️ Sensor STARTED")
        self._publish_status('running')
        
        # Start data thread
        thread = threading.Thread(target=self._send_data_loop, daemon=True)
        thread.start()
    
    def _handle_stop(self):
        """Stop sending sensor data"""
        self.running = False
        self.paused = False
        print("⏹️ Sensor STOPPED")
        self._publish_status('stopped')
    
    def _handle_pause(self, duration):
        """Pause sensor for specified duration"""
        self.paused = True
        self.pause_until = time.time() + duration
        print(f"⏸️ Sensor PAUSED for {duration}s")
        self._publish_status('paused')
    
    def _publish_status(self, status):
        """Publish sensor status"""
        if not self.connected:
            return
            
        payload = {
            'sensorId': self.sensor_id,
            'status': status,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        
        try:
            self.client.publish(self.status_topic, json.dumps(payload), qos=1)
        except Exception as e:
            print(f"❌ Status publish error: {e}")
    
    def _send_data_loop(self):
        """Main loop for sending sensor data"""
        print("\n📊 Starting data transmission...")
        print("-" * 50)
        
        while self.running and not self.shutdown_requested:
            # Check if paused
            if self.paused:
                if time.time() < self.pause_until:
                    time.sleep(1)
                    continue
                else:
                    self.paused = False
                    print("▶️ Resuming after pause")
                    self._publish_status('running')
            
            # Check connection
            if not self.connected:
                print("⚠️ Not connected, waiting...")
                time.sleep(2)
                continue
            
            # Generate and send data
            self._send_sensor_data()
            
            # Wait 1 second between messages
            time.sleep(1)
        
        print("\n⏹️ Data transmission stopped")
    
    def _send_sensor_data(self):
        """Generate and publish sensor data"""
        new_anomaly_type = None  # metric whose alarm fires THIS tick

        if self.event:
            # A spike cooldown or a gradual ramp is in progress
            is_anomaly, new_anomaly_type = self._advance_event()
        else:
            # Normal value drift with recovery
            if self.voltage < 220 or self.voltage > 240:
                self.voltage = random.uniform(228, 232)
            else:
                self.voltage += random.uniform(-0.5, 0.5)
            self.voltage = max(210, min(250, self.voltage))

            if self.frequency < 49.95 or self.frequency > 50.05:
                self.frequency = random.uniform(49.98, 50.02)
            else:
                self.frequency += random.uniform(-0.01, 0.01)
            self.frequency = max(49.80, min(50.20, self.frequency))

            if self.load > 85:
                self.load = random.uniform(50, 70)
            else:
                self.load += random.uniform(-2, 2)
            self.load = max(30, min(100, self.load))

            self.power = 50 + (self.load * 1.5) + random.uniform(-5, 5)

            if self.temperature > 60:
                self.temperature = random.uniform(40, 55)
            else:
                self.temperature += random.uniform(-0.5, 0.5)
            self.temperature = max(30, min(85, self.temperature))

            # Start an anomaly event: spike (abrupt) or ramp (gradual trend)
            is_anomaly = False
            if random.random() < self.ANOMALY_CHANCE:
                is_anomaly, new_anomaly_type = self._start_event()
        
        status = 'anomaly' if is_anomaly else 'normal'
        
        # Calculate uptime
        uptime = 100.0
        if self.start_time and self.total_messages > 0:
            success_rate = (self.total_messages - self.failed_messages) / self.total_messages
            uptime = success_rate * 100
        
        # Build payload
        payload = {
            'sensorId': self.sensor_id,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'status': status,
            'location': self.location,
            'metrics': {
                'temperature': round(self.temperature, 1),
                'voltage': round(self.voltage, 1),
                'frequency': round(self.frequency, 2),
                'load': round(self.load, 1),
                'power': round(self.power, 1),
                'uptime': round(uptime, 2)
            }
        }
        
        # Keep rolling context window (includes the anomalous reading itself)
        self.metrics_history.append({
            'timestamp': payload['timestamp'],
            'status': status,
            **payload['metrics']
        })

        try:
            result = self.client.publish(
                self.data_topic,
                json.dumps(payload),
                qos=0  # Direct messaging for real-time
            )

            self.total_messages += 1
            
            # Print status
            m = payload['metrics']
            anomaly_marker = "⚠️ ANOMALY" if is_anomaly else ""
            print(f"📤 [{self.total_messages:04d}] "
                  f"{m['voltage']:.0f}V | {m['frequency']:.2f}Hz | "
                  f"Load {m['load']:.0f}% | {m['power']:.0f}kW | "
                  f"{m['temperature']:.0f}°C {anomaly_marker}")
            
        except Exception as e:
            self.failed_messages += 1
            print(f"❌ Publish error: {e}")

        if new_anomaly_type:
            self._publish_alarm(new_anomaly_type)

    # Probability per idle tick (≈ per second) that a NEW anomaly event begins,
    # per sensor. Grid incidents are rare in reality, so keep this low — the
    # fleet-wide rate scales with the number of sensors:
    #   rate ≈ ANOMALY_CHANCE × (number of sensors) alarms per second.
    # Default 0.001 → e.g. ~1 alarm / 20 s with 50 sensors, ~1 / 40 s with 25.
    # Tune per demo via env: SENSOR_ANOMALY_CHANCE=0.003 for a busier run.
    ANOMALY_CHANCE = float(os.getenv('SENSOR_ANOMALY_CHANCE', '0.001'))

    # Alarm thresholds: (warning, critical) limits per metric.
    # Values beyond 'critical' → severity critical, beyond 'warning' → warning.
    ALARM_THRESHOLDS = {
        'voltage':     {'unit': 'V',  'nominal': 230.0, 'warning': 10.0, 'critical': 15.0},   # deviation from nominal
        'frequency':   {'unit': 'Hz', 'nominal': 50.0,  'warning': 0.05, 'critical': 0.10},   # deviation from nominal
        'load':        {'unit': '%',  'warning': 85.0,  'critical': 92.0},                    # absolute upper limit
        'temperature': {'unit': '°C', 'warning': 60.0,  'critical': 70.0}                     # absolute upper limit
    }

    def _publish_alarm(self, alarm_type):
        """Publish an alarmRaised event for the Joule agent (QoS 1 - must not get lost)"""
        cfg = self.ALARM_THRESHOLDS[alarm_type]
        value = {
            'voltage': self.voltage,
            'frequency': self.frequency,
            'load': self.load,
            'temperature': self.temperature
        }[alarm_type]

        if 'nominal' in cfg:
            deviation = abs(value - cfg['nominal'])
            severity = 'critical' if deviation >= cfg['critical'] else 'warning'
            threshold = {'nominal': cfg['nominal'], 'maxDeviation': cfg['warning']}
        else:
            severity = 'critical' if value >= cfg['critical'] else 'warning'
            threshold = {'max': cfg['warning']}

        now = datetime.utcnow()
        payload = {
            'alarmId': f"ALM-{self.sensor_id}-{now.strftime('%Y%m%d%H%M%S')}",
            'sensorId': self.sensor_id,
            'timestamp': now.isoformat() + 'Z',
            'severity': severity,
            'alarmType': alarm_type,
            'value': round(value, 2),
            'unit': cfg['unit'],
            'threshold': threshold,
            'location': self.location,
            'recentMetrics': list(self.metrics_history)
        }

        try:
            self.client.publish(self.alarm_topic, json.dumps(payload), qos=1)
            print(f"🚨 ALARM [{severity.upper()}] {alarm_type}={payload['value']}{cfg['unit']} "
                  f"→ {self.alarm_topic}")
        except Exception as e:
            print(f"❌ Alarm publish error: {e}")

    # ============================================
    # ANOMALY EVENTS (spike + ramp)
    # ============================================

    def _beyond(self, metric, value, level):
        """True if value violates the given threshold level ('warning'|'critical')."""
        cfg = self.ALARM_THRESHOLDS[metric]
        if 'nominal' in cfg:
            return abs(value - cfg['nominal']) >= cfg[level]
        return value >= cfg[level]

    def _start_event(self):
        """Begin an anomaly. Returns (is_anomaly_now, alarm_metric_or_None).
        50% ramp (gradual → dispatch/escalate), 50% spike (abrupt → restart/monitor)."""
        return self._start_ramp() if random.random() < 0.5 else self._start_spike()

    def _start_ramp(self):
        """Gradual climb over several ticks so recentMetrics shows a real trend.
        temperature/load ramp → dispatch_technician; voltage/frequency ramp → escalate.
        The alarm fires later, when the value crosses its critical threshold."""
        metric = random.choice(['temperature', 'load', 'voltage', 'frequency'])
        dur = random.randint(6, 9)
        if metric == 'temperature':
            target, start = random.uniform(74, 82), self.temperature
        elif metric == 'load':
            target, start = random.uniform(93, 99), self.load
        elif metric == 'voltage':
            target = random.choice([random.uniform(210, 214), random.uniform(246, 250)])
            start = self.voltage
        else:  # frequency
            target = random.choice([random.uniform(49.80, 49.88), random.uniform(50.12, 50.20)])
            start = self.frequency
        self.event = {'mode': 'ramp', 'metric': metric, 'target': target,
                      'step': (target - start) / dur, 'ticks_left': dur, 'fired': False}
        print(f"📈 RAMP {metric} → {target:.2f} ({dur} Ticks)")
        return False, None  # looks normal until it crosses the threshold

    def _start_spike(self):
        """Abrupt outlier with no lead-up.
        hard temp/load spike → restart_sensor; mild warning-level outlier → monitor."""
        if random.random() < 0.5:
            metric = random.choice(['temperature', 'load'])
            if metric == 'temperature':
                self.temperature = random.uniform(72, 82); v = self.temperature
            else:
                self.load = random.uniform(93, 98); self.power = 50 + self.load * 1.5; v = self.load
            self.event = {'mode': 'spike', 'ticks_left': 2}
            print(f"🔥 HARD {metric.upper()} SPIKE! {v:.1f}")
        else:
            metric = random.choice(['voltage', 'frequency', 'load', 'temperature'])
            if metric == 'voltage':
                self.voltage = random.choice([random.uniform(216, 219), random.uniform(241, 244)]); v = self.voltage
            elif metric == 'frequency':
                self.frequency = random.choice([random.uniform(49.90, 49.94), random.uniform(50.06, 50.10)]); v = self.frequency
            elif metric == 'load':
                self.load = random.uniform(86, 91); self.power = 50 + self.load * 1.5; v = self.load
            else:
                self.temperature = random.uniform(61, 68); v = self.temperature
            self.event = {'mode': 'spike', 'ticks_left': 1}
            print(f"• MILD {metric.upper()} outlier {v:.2f}")
        return True, metric

    def _advance_event(self):
        """Progress the active event by one tick. Returns (is_anomaly, alarm_metric_or_None)."""
        ev = self.event
        if ev['mode'] == 'spike':
            ev['ticks_left'] -= 1
            if ev['ticks_left'] <= 0:
                self.event = None
            return True, None

        # ramp: step the metric toward its target, keep correlated metrics plausible
        metric = ev['metric']
        setattr(self, metric, getattr(self, metric) + ev['step'])
        if metric == 'temperature':
            self.load = min(100, self.load + random.uniform(1.0, 2.5))   # heat ↔ load
        elif metric == 'load':
            self.temperature = min(88, self.temperature + random.uniform(0.8, 1.8))
        self.power = 50 + self.load * 1.5
        # keep everything in sane bounds
        self.voltage = max(205, min(255, self.voltage))
        self.frequency = max(49.5, min(50.5, self.frequency))
        self.load = max(30, min(100, self.load))
        self.temperature = max(30, min(90, self.temperature))

        fire, is_anom = None, ev['fired']
        if not ev['fired'] and self._beyond(metric, getattr(self, metric), 'critical'):
            ev['fired'] = True
            fire, is_anom = metric, True

        ev['ticks_left'] -= 1
        if ev['ticks_left'] <= 0:
            self.event = None
        return is_anom, fire

    def disconnect(self):
        """Clean disconnect from broker"""
        print("\n🔌 Disconnecting...")
        
        # Publish offline status
        if self.connected:
            self._publish_status('offline')
            time.sleep(0.3)  # Give time for message to send
        
        # Stop and disconnect
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
        
        print("✅ Disconnected cleanly")
    
    def run(self):
        """Main run loop - wait for commands"""
        print("\n⏳ Waiting for commands...")
        print(f"   Send 'start' to control/sensor/{self.sensor_id}/command")
        print()
        
        try:
            while not self.shutdown_requested:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            self.disconnect()
            print("👋 Goodbye!")


# ============================================
# MAIN
# ============================================

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='BS GRID Remote Controlled Sensor')
    parser.add_argument('sensor_id', nargs='?', default=SENSOR_ID, help='Sensor ID (e.g., TRF-MIT-001)')
    parser.add_argument('district', nargs='?', default=DISTRICT, help='District name')
    parser.add_argument('--autostart', action='store_true', help='Start sending data immediately without waiting for commands')
    
    args = parser.parse_args()
    
    sensor_id = args.sensor_id
    district = args.district
    
    # Extract district from sensor ID if not provided
    if district == DISTRICT and '-' in sensor_id:
        prefix = sensor_id.split('-')[1].upper()
        district_map = {
            'MIT': 'mitte',
            'KRZ': 'kreuzberg',
            'CHA': 'charlottenburg',
            'PRZ': 'prenzlauer berg',
            'FRH': 'friedrichshain',
            'NEU': 'neukoelln',
            'TMP': 'tempelhof',
            'SCH': 'schoeneberg',
            'WED': 'wedding',
            'SPA': 'spandau'
        }
        district = district_map.get(prefix, 'mitte')
    
    sensor = RemoteControlledSensor(sensor_id, district)
    
    if sensor.connect():
        if args.autostart:
            # Start immediately without waiting for commands
            print("\n🚀 AUTOSTART MODE - Starting immediately...")
            sensor.running = True
            sensor.start_time = time.time()
            sensor._publish_status('running')
            sensor._send_data_loop()
            sensor.disconnect()
        else:
            sensor.run()
    else:
        print("❌ Failed to start sensor")
        sys.exit(1)


if __name__ == '__main__':
    main()
