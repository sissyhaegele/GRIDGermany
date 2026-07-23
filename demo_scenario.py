#!/usr/bin/env python3
"""
GRIDGermany - Demo Scenario Player
Showcase: Berliner Stadtwerke (BS)

Spielt eine feste, gut getimte Folge von Alarmen ab — statt sie zufällig
entstehen zu lassen. Damit ist die Demo:
  - gut getaktet:  der erste Alarm kommt zügig, die nächsten verteilt später
  - sparsam:       jeder Alarm = genau ein Agent-Aufruf (= Credits). Du weißt
                   vorab exakt, wie viele. Default: 4 Alarme über ~4 Minuten.
  - abwechslungsreich: die vier Szenarien decken alle vier Agent-Entscheidungen ab.

Voraussetzung: der SAM-Agent (GridIncidentAgent + GridAlarmEntrypoint) läuft.
Sensoren können parallel laufen (fürs Live-Telemetrie-Bild); für null zufällige
Zusatz-Alarme dabei: SENSOR_ANOMALY_CHANCE=0 ./bsgrid

Start:
    python3 demo_scenario.py
Optional (Env):
    DEMO_FIRST_DELAY  Sekunden bis zum 1. Alarm         (Default 8)
    DEMO_GAP          Sekunden zwischen den weiteren     (Default 70)
    DEMO_MAX_ALARMS   nur die ersten N Szenarien spielen (Default alle 4)
    SOLACE_HOST/PORT/USERNAME/PASSWORD  wie üblich
"""

import paho.mqtt.client as mqtt
import json
import os
import ssl
import sys
import time
from datetime import datetime, timedelta

BROKER = os.getenv('SOLACE_HOST', 'mr-connection-gu0w0pjgchg.messaging.solace.cloud')
PORT = int(os.getenv('SOLACE_PORT', 8883))
USERNAME = os.getenv('SOLACE_USERNAME', 'solace-cloud-client')
PASSWORD = os.getenv('SOLACE_PASSWORD', 'iejmgp94muv7m5ahsfe9b50dvb')

FIRST_DELAY = float(os.getenv('DEMO_FIRST_DELAY', '8'))
GAP = float(os.getenv('DEMO_GAP', '70'))
MAX_ALARMS = int(os.getenv('DEMO_MAX_ALARMS', '0'))  # 0 = alle


def _recent(metric, start, end, n, base, anomaly_tail=1):
    """Baut ein recentMetrics-Fenster: 'metric' läuft von start→end über n Ticks,
    die übrigen Werte bleiben plausibel stabil. Bei temperature/load steigt die
    Last mit (plausible Überlast). Die letzten 'anomaly_tail' Ticks sind 'anomaly'."""
    now = datetime.utcnow()
    rows = []
    for i in range(n):
        frac = i / (n - 1) if n > 1 else 1
        row = dict(base)
        row[metric] = round(start + (end - start) * frac, 2)
        if metric in ('temperature', 'load'):
            row['load'] = round(base.get('load', 60) + frac * 18, 1)
            row['power'] = round(50 + row['load'] * 1.5, 1)
        row['status'] = 'anomaly' if i >= n - anomaly_tail else 'normal'
        row['timestamp'] = (now - timedelta(seconds=(n - 1 - i))).isoformat() + 'Z'
        rows.append(row)
    return rows


# Vier Szenarien → decken alle vier Agent-Entscheidungen ab.
# Jedes: (sensorId, district, alarmType, value, unit, threshold, severity, recentMetrics)
BASE = {'temperature': 45, 'voltage': 230, 'frequency': 50.0, 'load': 60, 'power': 140, 'uptime': 100.0}

def scenarios():
    return [
        # 1) Temperatur-Rampe + steigende Last → dispatch_technician  (der schnelle erste Alarm)
        dict(sensorId='TRF-KRZ-042', district='kreuzberg', alarmType='temperature',
             value=74.5, unit='°C', threshold={'max': 60.0}, severity='critical',
             location={'district': 'kreuzberg', 'lat': 52.4970, 'lon': 13.4070, 'address': 'Kottbusser Tor'},
             recentMetrics=_recent('temperature', 52, 74.5, 8, BASE)),
        # 2) Spannungs-Rampe → escalate (Netzstabilität)
        dict(sensorId='TRF-NEU-002', district='neukoelln', alarmType='voltage',
             value=212.0, unit='V', threshold={'nominal': 230.0, 'maxDeviation': 10.0}, severity='critical',
             location={'district': 'neukoelln', 'lat': 52.4810, 'lon': 13.4350, 'address': 'Hermannplatz'},
             recentMetrics=_recent('voltage', 231, 212, 8, BASE)),
        # 3) Milder Einzelausreißer → monitor
        dict(sensorId='TRF-MIT-007', district='mitte', alarmType='temperature',
             value=63.0, unit='°C', threshold={'max': 60.0}, severity='warning',
             location={'district': 'mitte', 'lat': 52.5200, 'lon': 13.4050, 'address': 'Alexanderplatz'},
             recentMetrics=_recent('temperature', 52, 52.5, 7, BASE) +
                           _recent('temperature', 63, 63, 1, BASE)),
        # 4) Abrupter Spike ohne Vorlauf → restart_sensor (Sensorfehler)
        dict(sensorId='TRF-FRH-003', district='friedrichshain', alarmType='temperature',
             value=79.0, unit='°C', threshold={'max': 60.0}, severity='critical',
             location={'district': 'friedrichshain', 'lat': 52.5150, 'lon': 13.4540, 'address': 'Warschauer Straße'},
             recentMetrics=_recent('temperature', 55, 55.5, 7, BASE) +
                           _recent('temperature', 79, 79, 1, BASE)),
    ]


def build_alarm(sc):
    now = datetime.utcnow()
    return {
        'alarmId': f"ALM-{sc['sensorId']}-{now.strftime('%Y%m%d%H%M%S')}",
        'sensorId': sc['sensorId'],
        'timestamp': now.isoformat() + 'Z',
        'severity': sc['severity'],
        'alarmType': sc['alarmType'],
        'value': sc['value'],
        'unit': sc['unit'],
        'threshold': sc['threshold'],
        'location': sc['location'],
        'recentMetrics': sc['recentMetrics'],
    }


def topic_for(sc):
    return f"bs/{sc['district']}/mv/transformer/powerline/alarmRaised/{sc['sensorId']}"


def main():
    scs = scenarios()
    if MAX_ALARMS > 0:
        scs = scs[:MAX_ALARMS]

    print(f"╔{'═'*60}╗")
    print(f"║  GRIDGermany Demo Scenario Player{' '*26}║")
    print(f"╚{'═'*60}╝")
    print(f"📡 Broker: {BROKER}:{PORT}")
    print(f"🎬 {len(scs)} Alarme  |  1. nach {FIRST_DELAY:.0f}s, dann alle {GAP:.0f}s")
    print(f"💡 = {len(scs)} Agent-Aufrufe (Credits). Ctrl+C bricht ab.\n")

    client_id = f"demo-scenario-{int(time.time())}"
    try:
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                             client_id=client_id, clean_session=True)
    except (AttributeError, TypeError):
        client = mqtt.Client(client_id=client_id, clean_session=True)
    client.username_pw_set(USERNAME, PASSWORD)
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.connect(BROKER, PORT, keepalive=30)
    client.loop_start()
    time.sleep(1.5)

    try:
        for i, sc in enumerate(scs):
            wait = FIRST_DELAY if i == 0 else GAP
            print(f"⏳ warte {wait:.0f}s bis Alarm {i+1}/{len(scs)} …")
            time.sleep(wait)
            payload = build_alarm(sc)
            client.publish(topic_for(sc), json.dumps(payload), qos=1)
            print(f"🚨 [{i+1}/{len(scs)}] {sc['severity'].upper()} {sc['alarmType']}="
                  f"{sc['value']}{sc['unit']} @ {sc['sensorId']} → {topic_for(sc)}")
        print("\n✅ Szenario komplett gespielt. Die Agent-Entscheidungen erscheinen "
              "im Dashboard / als E-Mails.")
    except KeyboardInterrupt:
        print("\n🛑 Abgebrochen.")
    finally:
        time.sleep(0.5)
        client.loop_stop()
        client.disconnect()


if __name__ == '__main__':
    main()
