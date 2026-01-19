#!/usr/bin/env python3
"""
Berliner Stadtwerke Power Sensor Simulator
Simulates realistic power grid sensor data and publishes to Solace
"""

import json
import time
import random
import math
from datetime import datetime
from typing import Dict, Tuple

class PowerSensorSimulator:
    """Simulates a power grid monitoring sensor"""
    
    def __init__(self, sensor_id: str, district: str, voltage_level: str, asset_type: str):
        self.sensor_id = sensor_id
        self.district = district
        self.voltage_level = voltage_level  # hv, mv, or lv
        self.asset_type = asset_type  # substation, transformer, etc.
        
        # Set parameters based on voltage level
        self.config = self._get_voltage_config()
        
        # Current state
        self.temperature = self.config['temp_normal']
        self.anomaly_mode = None
        self.anomaly_duration = 0
        
    def _get_voltage_config(self) -> Dict:
        """Get configuration parameters based on voltage level"""
        configs = {
            'hv': {  # High Voltage 110kV
                'voltage_nominal': 110000,
                'voltage_variance': 5500,  # ±5%
                'current_nominal': 400,
                'current_max': 1000,
                'active_power_nominal': 80000,  # 80 MW
                'power_factor_target': 0.95,
                'temp_normal': 50,
                'temp_alarm': 80,
                'thd_normal': 2.0,
                'thd_alarm': 5.0
            },
            'mv': {  # Medium Voltage 20kV
                'voltage_nominal': 20000,
                'voltage_variance': 1000,  # ±5%
                'current_nominal': 200,
                'current_max': 500,
                'active_power_nominal': 7000,  # 7 MW
                'power_factor_target': 0.92,
                'temp_normal': 55,
                'temp_alarm': 90,
                'thd_normal': 3.0,
                'thd_alarm': 6.0
            },
            'lv': {  # Low Voltage 400V
                'voltage_nominal': 400,
                'voltage_variance': 40,  # ±10%
                'current_nominal': 60,
                'current_max': 200,
                'active_power_nominal': 40,  # 40 kW
                'power_factor_target': 0.85,
                'temp_normal': 45,
                'temp_alarm': 75,
                'thd_normal': 4.0,
                'thd_alarm': 8.0
            }
        }
        return configs.get(self.voltage_level, configs['mv'])
    
    def _get_load_factor(self) -> float:
        """Calculate load factor based on time of day and day of week"""
        now = datetime.now()
        hour = now.hour
        day_of_week = now.weekday()  # 0=Monday, 6=Sunday
        
        # Weekend reduction
        weekend_factor = 0.6 if day_of_week >= 5 else 1.0
        
        # Hourly pattern (24-hour cycle)
        if 0 <= hour < 6:     # Night
            time_factor = 0.35
        elif 6 <= hour < 9:   # Morning ramp
            time_factor = 0.35 + (hour - 6) * 0.15
        elif 9 <= hour < 12:  # Morning peak
            time_factor = 0.90
        elif 12 <= hour < 14: # Lunch dip
            time_factor = 0.75
        elif 14 <= hour < 18: # Afternoon peak
            time_factor = 1.0
        elif 18 <= hour < 22: # Evening
            time_factor = 0.80
        else:                 # Late evening
            time_factor = 0.55
        
        return time_factor * weekend_factor
    
    def _calculate_3phase_power(self, voltage: float, current: float, 
                                power_factor: float) -> Tuple[float, float, float]:
        """Calculate 3-phase power values"""
        # Active power (kW)
        active_power = (math.sqrt(3) * voltage * current * power_factor) / 1000
        
        # Reactive power (kVAR)
        reactive_power = (math.sqrt(3) * voltage * current * 
                         math.sqrt(1 - power_factor**2)) / 1000
        
        # Apparent power (kVA)
        apparent_power = math.sqrt(active_power**2 + reactive_power**2)
        
        return active_power, reactive_power, apparent_power
    
    def _inject_anomaly(self) -> bool:
        """Randomly inject anomalies (2% probability)"""
        if self.anomaly_mode is not None:
            return True
        
        if random.random() < 0.02:  # 2% chance
            anomalies = [
                'voltage_sag', 'voltage_swell', 'overload', 
                'frequency_deviation', 'high_temperature', 'poor_power_factor'
            ]
            self.anomaly_mode = random.choice(anomalies)
            self.anomaly_duration = random.randint(5, 30)  # 5-30 heartbeats
            return True
        return False
    
    def generate_reading(self) -> Dict:
        """Generate a realistic sensor reading"""
        
        # Check for anomalies
        has_anomaly = self._inject_anomaly()
        
        # Base load from time pattern
        load_factor = self._get_load_factor()
        
        # Initialize values
        voltage = self.config['voltage_nominal']
        current = self.config['current_nominal'] * load_factor
        power_factor = self.config['power_factor_target']
        frequency = 50.0
        thd = self.config['thd_normal']
        
        # Apply anomaly if active
        if self.anomaly_mode == 'voltage_sag':
            voltage *= 0.92  # -8% voltage
        elif self.anomaly_mode == 'voltage_swell':
            voltage *= 1.08  # +8% voltage
        elif self.anomaly_mode == 'overload':
            current *= 1.85  # 85% overload
        elif self.anomaly_mode == 'frequency_deviation':
            frequency = random.choice([49.75, 50.25])
        elif self.anomaly_mode == 'high_temperature':
            self.temperature = min(self.temperature + 2, self.config['temp_alarm'] + 5)
        elif self.anomaly_mode == 'poor_power_factor':
            power_factor = 0.75
        
        # Add realistic noise to all parameters
        voltage += random.gauss(0, self.config['voltage_variance'] * 0.01)
        current += random.gauss(0, current * 0.02)
        frequency += random.gauss(0, 0.01)
        thd += random.gauss(0, 0.5)
        
        # Ensure bounds
        voltage = max(voltage, self.config['voltage_nominal'] * 0.85)
        voltage = min(voltage, self.config['voltage_nominal'] * 1.15)
        current = max(current, 0)
        current = min(current, self.config['current_max'])
        
        # Calculate derived values
        active_power, reactive_power, apparent_power = self._calculate_3phase_power(
            voltage, current, power_factor
        )
        
        # Temperature follows current load with thermal inertia
        load_ratio = current / self.config['current_nominal']
        target_temp = self.config['temp_normal'] + (load_ratio ** 2) * 30
        self.temperature += (target_temp - self.temperature) * 0.1  # Slow thermal response
        
        # Generate 3-phase values with slight imbalance
        imbalance = random.gauss(0, 0.03)  # ±3% imbalance
        voltage_l1 = voltage * (1 + imbalance)
        voltage_l2 = voltage * (1 - imbalance/2)
        voltage_l3 = voltage * (1 - imbalance/2)
        
        current_l1 = current * (1 + imbalance * 1.5)
        current_l2 = current * (1 - imbalance)
        current_l3 = current * (1 - imbalance/2)
        
        # Decrement anomaly duration
        if self.anomaly_mode and self.anomaly_duration > 0:
            self.anomaly_duration -= 1
            if self.anomaly_duration == 0:
                self.anomaly_mode = None
        
        # Determine status
        status = 'normal'
        anomaly_details = None
        
        if has_anomaly or self.anomaly_mode:
            status = 'anomaly'
            anomaly_details = {
                'type': self.anomaly_mode,
                'voltage_deviation_pct': ((voltage / self.config['voltage_nominal']) - 1) * 100,
                'current_ratio': current / self.config['current_nominal'],
                'temperature_above_normal': self.temperature - self.config['temp_normal']
            }
        
        # Create reading
        reading = {
            'eventType': 'PowerlineStatusUpdated',
            'eventId': f"{self.sensor_id}-{int(time.time())}",
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'region': self.district,
            'powerlineId': self.sensor_id,
            'status': status,
            'measurements': {
                'voltage': {
                    'l1': round(voltage_l1, 2),
                    'l2': round(voltage_l2, 2),
                    'l3': round(voltage_l3, 2),
                    'unit': 'V'
                },
                'current': {
                    'l1': round(current_l1, 2),
                    'l2': round(current_l2, 2),
                    'l3': round(current_l3, 2),
                    'unit': 'A'
                },
                'power': {
                    'active': round(active_power, 2),
                    'reactive': round(reactive_power, 2),
                    'apparent': round(apparent_power, 2),
                    'power_factor': round(power_factor, 3),
                    'active_unit': 'kW' if self.voltage_level != 'hv' else 'MW',
                    'reactive_unit': 'kVAR' if self.voltage_level != 'hv' else 'MVAR'
                },
                'frequency': round(frequency, 3),
                'temperature': round(self.temperature, 1),
                'thd': round(thd, 2)
            }
        }
        
        if anomaly_details:
            reading['anomalyDetails'] = anomaly_details
        
        return reading
    
    def generate_heartbeat(self) -> Dict:
        """Generate a simple heartbeat message"""
        return {
            'eventType': 'PowerlineHeartbeat',
            'eventId': f"{self.sensor_id}-hb-{int(time.time())}",
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'region': self.district,
            'powerlineId': self.sensor_id,
            'status': 'online'
        }


def simulate_sensor(sensor_id: str, district: str, voltage_level: str, 
                   asset_type: str, duration_seconds: int = 300):
    """
    Run a sensor simulation
    
    Args:
        sensor_id: Sensor identifier (e.g., 'SUB-MIT-001')
        district: Berlin district (e.g., 'mitte')
        voltage_level: 'hv', 'mv', or 'lv'
        asset_type: 'substation', 'transformer', etc.
        duration_seconds: How long to run simulation
    """
    
    sensor = PowerSensorSimulator(sensor_id, district, voltage_level, asset_type)
    
    print(f"Starting sensor simulation: {sensor_id}")
    print(f"Location: {district}, Voltage: {voltage_level}, Asset: {asset_type}")
    print(f"Will run for {duration_seconds} seconds")
    print("-" * 60)
    
    heartbeat_interval = 30  # seconds
    status_interval = 5      # seconds
    
    start_time = time.time()
    last_heartbeat = 0
    last_status = 0
    
    while (time.time() - start_time) < duration_seconds:
        current_time = time.time()
        
        # Send heartbeat every 30 seconds
        if current_time - last_heartbeat >= heartbeat_interval:
            heartbeat = sensor.generate_heartbeat()
            topic = f"bs/{district}/{voltage_level}/{asset_type}/powerline/heartbeat/v1/{sensor_id}"
            print(f"\n[HEARTBEAT] {topic}")
            print(json.dumps(heartbeat, indent=2))
            last_heartbeat = current_time
        
        # Send status update every 5 seconds
        if current_time - last_status >= status_interval:
            reading = sensor.generate_reading()
            topic = f"bs/{district}/{voltage_level}/{asset_type}/powerline/statusUpdated/v1/{sensor_id}"
            print(f"\n[STATUS] {topic}")
            print(json.dumps(reading, indent=2))
            
            # Highlight anomalies
            if reading['status'] == 'anomaly':
                print("*** ANOMALY DETECTED ***")
                print(json.dumps(reading['anomalyDetails'], indent=2))
            
            last_status = current_time
        
        time.sleep(1)


if __name__ == '__main__':
    # Example: Simulate a medium voltage transformer in Mitte
    simulate_sensor(
        sensor_id='TRF-MIT-042',
        district='mitte',
        voltage_level='mv',
        asset_type='transformer',
        duration_seconds=120  # Run for 2 minutes
    )
