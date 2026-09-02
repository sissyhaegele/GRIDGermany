#!/usr/bin/env python3
"""
GRIDGermany - Technician Scheduling Service
Showcase: Berliner Stadtwerke (BS)

Additiver Consumer im Event Mesh: reagiert auf dispatch_technician-Entscheidungen
des Grid Incident Agents, wählt deterministisch einen verfügbaren Techniker +
freien Slot und publiziert einen Termin als NEUES Event zurück ins Mesh.

    bs/*/…/agentActionTaken/*   (decision == dispatch_technician)
        → nächster freier Slot im zuständigen Team
        → bs/agent/…/technicianScheduled/scheduled

Kein externes Kalendersystem: Der Belegungszustand wird AUS DEM EVENT-STREAM
aufgebaut — der Service abonniert auch die technicianScheduled-Events und
rekonstruiert daraus, welche Slots vergeben sind (idempotent per appointmentId).
Mit einer durablen Queue auf diesem Topic überlebt der Zustand sogar Neustarts.

Agent und Dashboard bleiben unberührt (lose Kopplung). Start:
    python3 scheduling_service.py
"""

import bs_env  # lädt config.env in os.environ
import paho.mqtt.client as mqtt
import json
import os
import signal
import ssl
import time
from datetime import datetime, timedelta

BROKER = os.getenv('SOLACE_HOST')
PORT = int(os.getenv('SOLACE_PORT', 8883))
USERNAME = os.getenv('SOLACE_USERNAME')
PASSWORD = os.getenv('SOLACE_PASSWORD')

REQUEST_SUB = 'bs/+/mv/transformer/powerline/schedulingRequested/+'   # vom SAM-Workflow
DECISION_SUB = 'bs/+/mv/transformer/powerline/agentActionTaken/+'     # Fallback: direkt aus der Entscheidung
SCHEDULED_SUB = 'bs/+/mv/transformer/powerline/technicianScheduled/+' # Zustand aus dem Event-Stream
SCHEDULED_TOPIC = 'bs/agent/mv/transformer/powerline/technicianScheduled/scheduled'

# Techniker-Teams je Bezirk (deterministisch, kein externes System)
ROSTER = {
    'Team Ost':   ['Anna Krause', 'Ben Richter'],
    'Team Mitte': ['Clara Vogt', 'David Lang'],
    'Team West':  ['Eva Sommer', 'Finn Berg'],
    'Team Süd':   ['Greta Hahn', 'Ivan Petrov'],
    'Team Nord':  ['Jonas Weiss'],
}
DISTRICT_TEAM = {
    'kreuzberg': 'Team Ost', 'friedrichshain': 'Team Ost',
    'mitte': 'Team Mitte', 'wedding': 'Team Mitte',
    'charlottenburg': 'Team West', 'spandau': 'Team West',
    'neukoelln': 'Team Süd', 'tempelhof': 'Team Süd', 'schoeneberg': 'Team Süd',
    'prenzlauer berg': 'Team Nord',
}
# Sensor-ID-Kürzel → Bezirk. Die agentActionTaken-Entscheidung enthält KEIN
# location/district, wohl aber die sensorId (z.B. TRF-KRZ-042) — daraus leiten
# wir den Bezirk ab, damit die Last über ALLE Teams verteilt wird (sonst landet
# alles im Fallback 'Team Mitte' und einzelne Techniker werden mehrfach verplant).
CODE_DISTRICT = {
    'MIT': 'mitte', 'KRZ': 'kreuzberg', 'CHA': 'charlottenburg',
    'PRZ': 'prenzlauer berg', 'FRH': 'friedrichshain', 'NEU': 'neukoelln',
    'TMP': 'tempelhof', 'SCH': 'schoeneberg', 'WED': 'wedding', 'SPA': 'spandau',
}
_WD = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']


def _district_of(data):
    """Bezirk aus der Entscheidung ermitteln: bevorzugt explizites Feld, sonst
    aus der sensorId ableiten (TRF-KRZ-042 → kreuzberg)."""
    d = data.get('district') or (data.get('location') or {}).get('district')
    if d:
        return d
    parts = (data.get('sensorId') or '').split('-')
    if len(parts) >= 2:
        return CODE_DISTRICT.get(parts[1].upper(), parts[1].lower())
    return '—'


def _next_business_slots(after, limit=240):
    """Generator: 30-Minuten-Slots in Geschäftszeiten (Mo–Fr, 08:00–16:30),
    beginnend beim nächsten Raster-Slot nach 'after'."""
    add = 30 - (after.minute % 30)
    slot = (after + timedelta(minutes=add)).replace(second=0, microsecond=0)
    for _ in range(limit):
        if slot.weekday() < 5 and 8 <= slot.hour <= 16:
            yield slot
            slot += timedelta(minutes=30)
        else:
            # nächster Geschäftstag 08:00
            nxt = (slot + timedelta(days=1)).replace(hour=8, minute=0)
            while nxt.weekday() >= 5:
                nxt += timedelta(days=1)
            slot = nxt


def _label(dt):
    return f"{_WD[dt.weekday()]} {dt.strftime('%d.%m. %H:%M')}"


def _strip_code_fence(text):
    """Entfernt einen Markdown-Codeblock-Zaun (```json … ```), falls das LLM
    seine JSON-Antwort so verpackt."""
    s = text.strip()
    if s.startswith('```'):
        s = s[3:]
        if s[:4].lower() == 'json':
            s = s[4:]
        end = s.rfind('```')
        if end != -1:
            s = s[:end]
    return s.strip()


def _parse_payload(raw_bytes):
    """Entscheidungen/Termine robust parsen. SAM/das LLM publiziert die Nutzlast
    in mehreren Formen — alle abfangen:
      1. direktes JSON-Objekt
      2. JSON-String, der JSON enthält (doppelt kodiert)
      3. JSON-String mit ```json …```-Markdown-Fence (LLM-Ausgabe)
    """
    raw = raw_bytes.decode()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = json.loads(_strip_code_fence(raw))
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = json.loads(_strip_code_fence(data))
    return data


class SchedulingService:
    def __init__(self):
        self.assigned = {t: set() for team in ROSTER.values() for t in team}  # tech -> {slot_iso}
        self.appointments = {}     # appointmentId -> payload (idempotent)
        self.processed = set()     # alarmIds, gegen Doppelverarbeitung
        self.client = None
        self.shutdown = False
        signal.signal(signal.SIGINT, self._stop)
        signal.signal(signal.SIGTERM, self._stop)

    def _stop(self, *a):
        print(f"\n🛑 Stop. {len(self.appointments)} Termine im Zustand.")
        self.shutdown = True

    # ---- Slot-Auswahl (deterministisch) ----
    def _schedule(self, district):
        team = DISTRICT_TEAM.get(district, 'Team Mitte')
        now = datetime.now()
        best = None  # (slot, tech)
        for tech in ROSTER[team]:
            for s in _next_business_slots(now):
                if s.isoformat() not in self.assigned[tech]:
                    if best is None or s < best[0]:
                        best = (s, tech)
                    break
        if best is None:
            # Alle Techniker des Teams im betrachteten Fenster voll — statt
            # abzustürzen (TypeError) den erstbesten Slot des ersten Technikers
            # nehmen (Demo-Fallback; in echt würde man das Fenster erweitern).
            tech = ROSTER[team][0]
            slot = next(_next_business_slots(now))
            print(f"⚠️  Team {team} ausgelastet — Fallback-Slot für {tech}")
        else:
            slot, tech = best
        self.assigned[tech].add(slot.isoformat())
        return team, tech, slot

    # ---- MQTT ----
    def _on_connect(self, client, userdata, flags, rc, *a):
        code = rc if isinstance(rc, int) else getattr(rc, 'value', 0)
        if code == 0:
            client.subscribe(REQUEST_SUB, qos=1)     # bevorzugt: Workflow-Anfrage
            client.subscribe(DECISION_SUB, qos=1)     # Fallback: direkt aus dispatch_technician
            client.subscribe(SCHEDULED_SUB, qos=1)    # Zustand aus Event-Stream aufbauen
            print(f"✅ Verbunden. Höre auf schedulingRequested + Entscheidungen + Termin-Events.")
        else:
            print(f"❌ Connect fehlgeschlagen (rc={code})")

    def _on_message(self, client, userdata, message):
        try:
            data = _parse_payload(message.payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"❌ Ungültiges JSON: {e}")
            return

        if 'technicianScheduled' in message.topic:
            self._record(data)          # eigener/historischer Termin → Zustand
            return

        # Auslöser: bevorzugt schedulingRequested (vom Workflow), sonst direkt
        # die dispatch_technician-Entscheidung (Fallback ohne Workflow).
        decision = data.get('decision')
        if 'schedulingRequested' in message.topic:
            # Falls der Workflow das 'decision'-Feld mitschickt (weil er ohne
            # Switch alles publiziert), hier defensiv filtern — nur Technikereinsätze.
            if decision and decision != 'dispatch_technician':
                print(f"·  skip: schedulingRequested mit decision={decision!r} (kein dispatch)")
                return
        elif decision != 'dispatch_technician':
            # Häufigster „kein Termin"-Fall: der Agent hat gar nicht dispatch gewählt.
            print(f"·  {data.get('sensorId','?')}: decision={decision!r} → kein Technikereinsatz")
            return

        alarm_id = data.get('alarmId')
        if not alarm_id:
            # Ohne alarmId greift die Dedup nicht sinnvoll — trotzdem einplanen,
            # aber sichtbar machen (könnte doppelte Termine erzeugen).
            print(f"⚠️  dispatch OHNE alarmId für {data.get('sensorId','?')} — plane trotzdem ein")
        elif alarm_id in self.processed:
            print(f"·  dispatch {alarm_id} bereits verarbeitet (Dedup) → übersprungen")
            return          # deckt auch den Fall ab, dass BEIDE Events zum selben Alarm kommen
        if alarm_id:
            self.processed.add(alarm_id)

        district = _district_of(data)
        if district == '—':
            print(f"⚠️  Bezirk unbekannt für {data.get('sensorId','?')} "
                  f"(location={data.get('location')}) → Fallback-Team")
        team, tech, slot = self._schedule(district)
        appt = {
            'appointmentId': f"APT-{data.get('sensorId','?')}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'alarmId': alarm_id,
            'sensorId': data.get('sensorId'),
            'district': district,
            'team': team,
            'technician': tech,
            'slot': slot.isoformat(),
            'slotLabel': _label(slot),
            'status': 'scheduled',
            'timestamp': datetime.now().isoformat() + 'Z',
        }
        self._record(appt)
        try:
            client.publish(SCHEDULED_TOPIC, json.dumps(appt, ensure_ascii=False), qos=1)
            print(f"📅 Termin: {tech} ({team}) @ {appt['slotLabel']}  für {appt['sensorId']} ({district})")
        except Exception as e:
            print(f"❌ Publish-Fehler: {e}")

    def _record(self, appt):
        aid = appt.get('appointmentId')
        if not aid or aid in self.appointments:
            return
        self.appointments[aid] = appt
        tech, slot = appt.get('technician'), appt.get('slot')
        if tech in self.assigned and slot:
            self.assigned[tech].add(slot)

    def run(self):
        print(f"╔{'═'*60}╗")
        print(f"║  GRIDGermany Technician Scheduling Service{' '*17}║")
        print(f"╚{'═'*60}╝")
        print(f"📡 Broker: {BROKER}:{PORT}")
        print(f"👷 Teams: {', '.join(ROSTER)}\n")
        cid = f"scheduling-service-{int(time.time())}"
        try:
            self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                                     client_id=cid, clean_session=True)
        except (AttributeError, TypeError):
            self.client = mqtt.Client(client_id=cid, clean_session=True)
        self.client.username_pw_set(USERNAME, PASSWORD)
        self.client.tls_set(cert_reqs=ssl.CERT_NONE)
        self.client.tls_insecure_set(True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect(BROKER, PORT, keepalive=30)
        self.client.loop_start()
        try:
            while not self.shutdown:
                time.sleep(0.5)
        finally:
            self.client.loop_stop()
            self.client.disconnect()


if __name__ == '__main__':
    SchedulingService().run()
