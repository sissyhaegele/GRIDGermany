#!/usr/bin/env python3
"""
GRIDGermany - Demo Scenario Player
Showcase: Berliner Stadtwerke (BS)

Spielt getimte Alarme ab, damit die Demo verlässlich läuft:
  - gescripteter Einstieg: die ersten beiden Karten sind fest — 1) Beobachtung
    (monitor), 2) Technikereinsatz (dispatch) — danach bleibt es ZUFÄLLIG.
    So bleibt die EDA-Botschaft "deterministisch UND nicht-deterministisch".
  - gut getaktet:  1. Kachel nach ~10s, die nächsten verteilt (DEMO_GAP).
  - sparsam:       jeder Alarm = genau ein Agent-Aufruf (= Credits).
  - abwechslungsreich: deckt alle vier Agent-Entscheidungen ab.

Lead-in abschalten (rein zufällig): DEMO_LEADIN=0
Komplett feste Reihenfolge (alle 4 gescriptet): DEMO_RANDOM=0

Voraussetzung: der SAM-Agent (GridIncidentAgent + GridAlarmEntrypoint) läuft.
Sensoren können parallel laufen (fürs Live-Telemetrie-Bild); für null zufällige
Zusatz-Alarme dabei: SENSOR_ANOMALY_CHANCE=0 ./bsgrid

Start:
    python3 demo_scenario.py
Optional (Env):
    DEMO_FIRST_DELAY  Sekunden bis zum 1. Alarm         (Default 2 → Kachel ~10s)
    DEMO_GAP          Sekunden zwischen den weiteren     (Default 15)
    DEMO_MAX_ALARMS   nur die ersten N Szenarien spielen (Default alle 4)
    DEMO_RANDOM       1 = zufällig (mit festem Lead-in), 0 = ganz fest (Default 1)
    DEMO_LEADIN       1 = feste erste 2 Karten, 0 = sofort zufällig (Default 1)
    DEMO_MAX_MINUTES  Auto-Stopp nach N Minuten gegen Token-Verbrauch (Default 2; 0 = aus)
    SOLACE_HOST/PORT/USERNAME/PASSWORD  wie üblich
"""

import paho.mqtt.client as mqtt
import json
import os
import random
import signal
import ssl
import sys
import time
from datetime import datetime, timedelta

import bs_env  # lädt config.env in os.environ
BROKER = os.getenv('SOLACE_HOST')
PORT = int(os.getenv('SOLACE_PORT', 8883))
USERNAME = os.getenv('SOLACE_USERNAME')
PASSWORD = os.getenv('SOLACE_PASSWORD')

# Ziel: 1. Kachel im Dashboard nach ~10s. Die Karte = Alarm + Agent-Latenz (~8s),
# daher wird der 1. Alarm nach ~2s gefeuert. Wenn dein Agent langsamer/schneller
# ist, DEMO_FIRST_DELAY nachstellen. Alles per Env überschreibbar.
FIRST_DELAY = float(os.getenv('DEMO_FIRST_DELAY', '15'))
GAP = float(os.getenv('DEMO_GAP', '10'))
MAX_ALARMS = int(os.getenv('DEMO_MAX_ALARMS', '0'))  # 0 = alle (bzw. 4 bei Zufall)
RANDOM = os.getenv('DEMO_RANDOM', '1') != '0'         # 1 = zufällig variierte Alarme (Default)
# Not-Aus gegen Token-Verbrauch: nach so vielen MINUTEN stoppt der Taktgeber
# automatisch — auch im Dauerbetrieb, auch wenn das Terminal vergessen wird.
# Neustart der Demo bringt frische 2 Minuten. 0 = kein Zeitlimit.
MAX_MINUTES = float(os.getenv('DEMO_MAX_MINUTES', '2'))


def _recent(metric, start, end, n, base, anomaly_tail=1, correlate=True):
    """Baut ein recentMetrics-Fenster: 'metric' läuft von start→end über n Ticks,
    die übrigen Werte bleiben plausibel stabil. Bei temperature/load und
    correlate=True steigt die Last mit (plausible Überlast → dispatch). Für einen
    abrupten Sensorfehler correlate=False (Last bleibt flach → implausibel → restart).
    Die letzten 'anomaly_tail' Ticks sind 'anomaly'."""
    now = datetime.utcnow()
    rows = []
    for i in range(n):
        frac = i / (n - 1) if n > 1 else 1
        row = dict(base)
        row[metric] = round(start + (end - start) * frac, 2)
        if correlate and metric in ('temperature', 'load'):
            row['load'] = round(base.get('load', 60) + frac * 18, 1)
            row['power'] = round(50 + row['load'] * 1.5, 1)
        row['status'] = 'anomaly' if i >= n - anomaly_tail else 'normal'
        row['timestamp'] = (now - timedelta(seconds=(n - 1 - i))).isoformat() + 'Z'
        rows.append(row)
    return rows


# Bezirks-Katalog für zufällige Szenarien (Code → Name, lat, lon, Adresse)
DISTRICTS = {
    'MIT': ('mitte', 52.5200, 13.4050, 'Alexanderplatz'),
    'KRZ': ('kreuzberg', 52.4970, 13.4070, 'Kottbusser Tor'),
    'CHA': ('charlottenburg', 52.5160, 13.3040, 'Savignyplatz'),
    'PRZ': ('prenzlauer berg', 52.5380, 13.4240, 'Schönhauser Allee'),
    'FRH': ('friedrichshain', 52.5150, 13.4540, 'Warschauer Straße'),
    'NEU': ('neukoelln', 52.4810, 13.4350, 'Hermannplatz'),
    'TMP': ('tempelhof', 52.4700, 13.4030, 'Tempelhofer Feld'),
    'SCH': ('schoeneberg', 52.4830, 13.3530, 'Nollendorfplatz'),
    'WED': ('wedding', 52.5510, 13.3590, 'Leopoldplatz'),
    'SPA': ('spandau', 52.5350, 13.2000, 'Altstadt Spandau'),
}


def random_scenario():
    """Ein zufällig variierter Alarm — zufälliger Bezirk/Sensor/Metrik/Verlauf.
    Das Muster bestimmt die zu erwartende Agent-Entscheidung (ramp→dispatch/escalate,
    outlier→monitor, spike→restart), der Agent entscheidet aber selbst."""
    code = random.choice(list(DISTRICTS))
    district, lat, lon, addr = DISTRICTS[code]
    loc = {'district': district, 'lat': round(lat + random.uniform(-0.01, 0.01), 4),
           'lon': round(lon + random.uniform(-0.01, 0.01), 4), 'address': addr}
    sensor = f"TRF-{code}-{random.randint(1, 99):03d}"
    kind = random.choice(['dispatch', 'escalate', 'monitor', 'restart'])
    n = random.randint(6, 9)

    if kind == 'dispatch':                 # Rampe Temp/Last mit steigender Last
        if random.random() < 0.5:
            end = round(random.uniform(72, 82), 1)
            rm = _recent('temperature', round(random.uniform(48, 55), 1), end, n, BASE)
            metric, unit, thr = 'temperature', '°C', {'max': 60.0}
        else:
            end = round(random.uniform(93, 99), 1)
            rm = _recent('load', round(random.uniform(58, 66), 1), end, n, BASE)
            metric, unit, thr = 'load', '%', {'max': 85.0}
        sev, val = 'critical', end
    elif kind == 'escalate':               # Rampe Spannung/Frequenz (Netzabweichung)
        if random.random() < 0.5:
            end = round(random.choice([random.uniform(210, 214), random.uniform(246, 250)]), 1)
            rm = _recent('voltage', 230.5, end, n, BASE)
            metric, unit, thr = 'voltage', 'V', {'nominal': 230.0, 'maxDeviation': 10.0}
        else:
            end = round(random.choice([random.uniform(49.80, 49.88), random.uniform(50.12, 50.20)]), 2)
            rm = _recent('frequency', 50.0, end, n, BASE)
            metric, unit, thr = 'frequency', 'Hz', {'nominal': 50.0, 'maxDeviation': 0.05}
        sev, val = 'critical', end
    elif kind == 'monitor':                # milder Einzelausreißer, stabil davor
        base_t = round(random.uniform(50, 54), 1)
        spike = round(random.uniform(61, 66), 1)
        rm = (_recent('temperature', base_t, base_t + 0.4, n - 1, BASE, correlate=False) +
              _recent('temperature', spike, spike, 1, BASE, correlate=False))
        metric, unit, thr, sev, val = 'temperature', '°C', {'max': 60.0}, 'warning', spike
    else:                                  # abrupter Spike ohne Vorlauf → Sensorfehler
        if random.random() < 0.5:
            flat = round(random.uniform(52, 57), 1); spike = round(random.uniform(72, 82), 1)
            rm = (_recent('temperature', flat, flat + 0.4, n - 1, BASE, correlate=False) +
                  _recent('temperature', spike, spike, 1, BASE, correlate=False))
            metric, unit, thr = 'temperature', '°C', {'max': 60.0}
        else:
            flat = round(random.uniform(60, 68), 1); spike = round(random.uniform(93, 98), 1)
            rm = (_recent('load', flat, flat + 0.4, n - 1, BASE, correlate=False) +
                  _recent('load', spike, spike, 1, BASE, correlate=False))
            metric, unit, thr = 'load', '%', {'max': 85.0}
        sev, val = 'critical', spike

    return dict(sensorId=sensor, district=district, alarmType=metric, value=val,
                unit=unit, threshold=thr, severity=sev, location=loc, recentMetrics=rm)


# Vier Szenarien → decken alle vier Agent-Entscheidungen ab.
# Jedes: (sensorId, district, alarmType, value, unit, threshold, severity, recentMetrics)
BASE = {'temperature': 45, 'voltage': 230, 'frequency': 50.0, 'load': 60, 'power': 140, 'uptime': 100.0}

def scenarios():
    # Reihenfolge = bewusst gewählte Eröffnung der Demo:
    # 1) Beobachtung, 2) Technikereinsatz, 3) Eskalation, 4) Restart.
    return [
        # 1) Milder Einzelausreißer → monitor  (der ruhige Einstieg: "Agent beobachtet")
        dict(sensorId='TRF-MIT-007', district='mitte', alarmType='temperature',
             value=63.0, unit='°C', threshold={'max': 60.0}, severity='warning',
             location={'district': 'mitte', 'lat': 52.5200, 'lon': 13.4050, 'address': 'Alexanderplatz'},
             recentMetrics=_recent('temperature', 52, 52.5, 7, BASE) +
                           _recent('temperature', 63, 63, 1, BASE)),
        # 2) Temperatur-Rampe + steigende Last → dispatch_technician  (Techniker wird eingeplant)
        dict(sensorId='TRF-KRZ-042', district='kreuzberg', alarmType='temperature',
             value=74.5, unit='°C', threshold={'max': 60.0}, severity='critical',
             location={'district': 'kreuzberg', 'lat': 52.4970, 'lon': 13.4070, 'address': 'Kottbusser Tor'},
             recentMetrics=_recent('temperature', 52, 74.5, 8, BASE)),
        # 3) Spannungs-Rampe → escalate (Netzstabilität)
        dict(sensorId='TRF-NEU-002', district='neukoelln', alarmType='voltage',
             value=212.0, unit='V', threshold={'nominal': 230.0, 'maxDeviation': 10.0}, severity='critical',
             location={'district': 'neukoelln', 'lat': 52.4810, 'lon': 13.4350, 'address': 'Hermannplatz'},
             recentMetrics=_recent('voltage', 231, 212, 8, BASE)),
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


_shutdown = {'v': False}
def _stop(*a):
    _shutdown['v'] = True


def _plan():
    """Ergibt entweder eine feste Alarm-Liste (endlich) oder None für Dauerbetrieb.
    Dauerbetrieb = RANDOM und kein MAX_ALARMS: jeder Alarm wird frisch zufällig
    erzeugt, endlos im Takt FIRST_DELAY / GAP."""
    if RANDOM and MAX_ALARMS <= 0:
        return None                                   # ∞ zufällig
    if RANDOM:
        lead_in = os.getenv('DEMO_LEADIN', '0') != '0'   # Default AUS: alles Zufall
        base = scenarios()[:2] if lead_in else []
        return (base + [random_scenario()
                        for _ in range(max(0, MAX_ALARMS - len(base)))])[:MAX_ALARMS]
    scs = scenarios()
    return scs[:MAX_ALARMS] if MAX_ALARMS > 0 else scs


def main():
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    planned = _plan()
    continuous = planned is None
    total = '∞' if continuous else str(len(planned))

    print(f"╔{'═'*60}╗")
    print(f"║  GRIDGermany Demo Scenario Player{' '*26}║")
    print(f"╚{'═'*60}╝")
    print(f"📡 Broker: {BROKER}:{PORT}")
    print(f"🎬 {total} Alarme ({'zufällig' if RANDOM else 'fest'})  |  "
          f"1. nach {FIRST_DELAY:.0f}s, dann alle {GAP:.0f}s")
    if MAX_MINUTES > 0:
        print(f"⏱️  Auto-Stopp nach {MAX_MINUTES:.0f} Min — danach keine Agent-Aufrufe mehr "
              f"(Token-Schutz). Neu starten für weitere.")
    if continuous:
        print("💡 Dauerbetrieb: jeder Alarm = 1 Agent-Aufruf (Credits!). Ctrl+C stoppt.\n")
    else:
        print(f"💡 = {len(planned)} Agent-Aufrufe (Credits). Ctrl+C bricht ab.\n")

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

    def _sleep(seconds):
        """Wartet unterbrechbar, damit Ctrl+C/SIGTERM sofort greift."""
        end = seconds
        step = 0.25
        while end > 0 and not _shutdown['v']:
            time.sleep(min(step, end))
            end -= step

    deadline = (time.monotonic() + MAX_MINUTES * 60) if MAX_MINUTES > 0 else None
    stopped_by_time = False
    try:
        i = 0
        while not _shutdown['v']:
            if deadline is not None and time.monotonic() >= deadline:
                stopped_by_time = True
                break
            _sleep(FIRST_DELAY if i == 0 else GAP)
            if _shutdown['v']:
                break
            if deadline is not None and time.monotonic() >= deadline:
                stopped_by_time = True
                break
            sc = random_scenario() if continuous else planned[i]
            payload = build_alarm(sc)
            client.publish(topic_for(sc), json.dumps(payload), qos=1)
            n = f"{i+1}" + ('' if continuous else f"/{len(planned)}")
            print(f"🚨 [{n}] {sc['severity'].upper()} {sc['alarmType']}="
                  f"{sc['value']}{sc['unit']} @ {sc['sensorId']} → {topic_for(sc)}")
            i += 1
            if not continuous and i >= len(planned):
                break
        if stopped_by_time:
            print(f"\n⏱️  Zeitlimit erreicht ({MAX_MINUTES:.0f} Min) — Taktgeber gestoppt, "
                  f"keine weiteren Agent-Aufrufe. Demo neu starten für weitere.")
        elif not continuous:
            print("\n✅ Szenario komplett gespielt.")
        else:
            print("\n🛑 Gestoppt.")
    finally:
        time.sleep(0.5)
        client.loop_stop()
        client.disconnect()


if __name__ == '__main__':
    main()
