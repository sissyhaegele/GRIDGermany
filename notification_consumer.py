#!/usr/bin/env python3
"""
GRIDGermany - Notification Consumer
Showcase: Berliner Stadtwerke (BS)

Ein additiver Consumer im Event Mesh: abonniert die Entscheidungen des
Grid Incident Agents und erzeugt bei bestimmten decision-Typen eine
Benachrichtigung (E-Mail). Agent und Dashboard bleiben davon unberührt —
reine Event-Driven-Erweiterung (lose Kopplung).

    bs/*/mv/transformer/powerline/agentActionTaken/*   (SMF-Wildcards)
        │
        ├─ decision == dispatch_technician  → Mail an Netzservice
        └─ decision == escalate             → Mail an Leitwarte

Versand: MOCK-Modus (Default) — die fertige E-Mail wird in der Konsole
angezeigt UND als .eml-Datei gespeichert (mit jedem Mail-Client öffenbar).
Es geht nichts nach außen. Ein echter SMTP-/Teams-Adapter lässt sich später
in _deliver() einhängen, ohne die übrige Logik zu ändern.

Verbindung = wie remote_controlled_sensor.py (MQTT/TLS, Port 8883). Der
Consumer nutzt dieselbe MQTT-Schnittstelle wie die Sensoren; der Broker
übersetzt zwischen MQTT und SMF, sodass er die vom Agent (REST/SMF)
publizierten Entscheidungen empfängt.

Start:
    python3 notification_consumer.py
Optional (Env): SOLACE_HOST, SOLACE_PORT, SOLACE_USERNAME, SOLACE_PASSWORD,
    NOTIFY_OUTBOX (Zielordner für .eml, Default: ./outbox)
"""

import paho.mqtt.client as mqtt
import json
import os
import signal
import ssl
import sys
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

# ============================================
# CONFIGURATION
# ============================================

import bs_env  # lädt config.env in os.environ
BROKER = os.getenv('SOLACE_HOST')
PORT = int(os.getenv('SOLACE_PORT', 8883))
USERNAME = os.getenv('SOLACE_USERNAME')
PASSWORD = os.getenv('SOLACE_PASSWORD')

# SMF-Wildcard '*' (eine Ebene) — konsistent mit Dashboard und SAM-Entrypoint,
# kein MQTT '+'/'#'. Auf der MQTT-Schnittstelle akzeptiert Solace '*' NICHT als
# Wildcard, daher wird beim Abonnieren auf die MQTT-Form gemappt (siehe SUB_MQTT).
ACTION_TOPIC_SMF = 'bs/*/mv/transformer/powerline/agentActionTaken/*'
SUB_MQTT = 'bs/+/mv/transformer/powerline/agentActionTaken/+'  # MQTT-Interface-Form

OUTBOX = os.getenv('NOTIFY_OUTBOX', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'outbox'))
FROM_ADDR = 'bs-grid-agent@berlinerstadtwerke.example'

# Welche Entscheidung → welche Benachrichtigung. Erweiterbar: weitere
# decision-Typen hier ergänzen, der Rest des Codes bleibt gleich.
ROUTES = {
    'dispatch_technician': {
        'to': 'netzservice@berlinerstadtwerke.example',
        'team': 'Netzservice',
        'subject': '🔧 Technikereinsatz erforderlich',
        'lead': 'Der Grid Incident Agent hat einen Technikereinsatz veranlasst.',
    },
    'escalate': {
        'to': 'leitwarte@berlinerstadtwerke.example',
        'team': 'Leitwarte',
        'subject': '⚠️ Eskalation an die Leitwarte',
        'lead': 'Der Grid Incident Agent hat einen Vorfall zur Eskalation markiert.',
    },
}


# ============================================
# MAIL BUILDING + (MOCK) DELIVERY
# ============================================

def build_email(decision_data, route):
    """Erzeugt eine EmailMessage aus einer agentActionTaken-Entscheidung."""
    d = decision_data
    sensor = d.get('sensorId', '?')
    district = _district_of(d)
    params = d.get('parameters') or {}
    priority = params.get('priority', '—')

    subject = f"{route['subject']} — {sensor} ({district})"
    body = f"""{route['lead']}

Transformator : {sensor}
Bezirk        : {district}
Entscheidung  : {d.get('decision')}
Priorität     : {priority}
Zielteam      : {params.get('targetTeam', route['team'])}
Konfidenz     : {_pct(d.get('confidence'))}
Alarm-ID      : {d.get('alarmId', '—')}
Zeitpunkt     : {d.get('timestamp', '—')}

Begründung des Agents:
{d.get('reasoning', '(keine Begründung übermittelt)')}

—
Automatisch erzeugt vom BS GRID Notification Consumer (Event Mesh).
Auslösendes Event: agentActionTaken • Agent: {d.get('agent', '—')}
"""

    msg = EmailMessage()
    msg['From'] = FROM_ADDR
    msg['To'] = route['to']
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = make_msgid(domain='berlinerstadtwerke.example')
    msg['X-BSGRID-Decision'] = d.get('decision', '')
    msg['X-BSGRID-AlarmId'] = d.get('alarmId', '')
    msg.set_content(body)
    return msg


def deliver(msg, decision_data):
    """MOCK-Versand: Konsole + .eml-Datei. Kein echter Versand nach außen.

    Für echten Versand später hier einen Adapter einhängen, z.B.:
      - SMTP:  smtplib.SMTP(host, port) → starttls → login → send_message(msg)
      - Teams: requests.post(webhook_url, json={...})
    Die übrige Pipeline (Filtern, Mail bauen) bleibt unverändert.
    """
    os.makedirs(OUTBOX, exist_ok=True)
    safe = (decision_data.get('alarmId') or 'unknown').replace('/', '_')
    path = os.path.join(OUTBOX, f"{safe}.eml")
    with open(path, 'wb') as f:
        f.write(bytes(msg))

    print("\n" + "=" * 68)
    print(f"📧 [MOCK] E-Mail würde versendet an: {msg['To']}")
    print("=" * 68)
    print(f"From:    {msg['From']}")
    print(f"To:      {msg['To']}")
    print(f"Subject: {msg['Subject']}")
    print("-" * 68)
    print(msg.get_content().rstrip())
    print("=" * 68)
    print(f"💾 gespeichert: {path}\n")


# ============================================
# HELPERS
# ============================================

def _district_of(d):
    loc = d.get('location') or {}
    if loc.get('district'):
        return loc['district']
    # Fallback: aus der sensorId ableiten (TRF-KRZ-042 → KRZ)
    parts = (d.get('sensorId') or '').split('-')
    return parts[1].lower() if len(parts) >= 2 else '—'


def _pct(conf):
    try:
        return f"{round(float(conf) * 100)} %"
    except (TypeError, ValueError):
        return '—'


def _parse_payload(raw_bytes):
    """agentActionTaken robust parsen: SAM publiziert das JSON teils als
    escaped String, teils direkt als Objekt — beides abfangen."""
    data = json.loads(raw_bytes.decode())
    if isinstance(data, str):
        data = json.loads(data)
    return data


# ============================================
# CONSUMER
# ============================================

class NotificationConsumer:
    def __init__(self):
        self.client = None
        self.matched = 0
        self.seen = 0
        self.shutdown = False
        signal.signal(signal.SIGINT, self._stop)
        signal.signal(signal.SIGTERM, self._stop)

    def _stop(self, signum, frame):
        print(f"\n🛑 Shutting down (seen {self.seen}, notified {self.matched})...")
        self.shutdown = True

    def _on_connect(self, client, userdata, flags, rc, *args):
        code = rc if isinstance(rc, int) else getattr(rc, 'value', 0)
        if code == 0:
            client.subscribe(SUB_MQTT, qos=1)
            print(f"✅ Connected — subscribed to {ACTION_TOPIC_SMF}")
            print(f"   Trigger: {', '.join(ROUTES)}  |  Mock-Outbox: {OUTBOX}")
        else:
            print(f"❌ Connection failed (rc={code})")

    def _on_message(self, client, userdata, message):
        self.seen += 1
        try:
            d = _parse_payload(message.payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"❌ Ungültiges agentActionTaken-JSON: {e}")
            return

        decision = d.get('decision')
        route = ROUTES.get(decision)
        if not route:
            print(f"·  {d.get('sensorId','?')}: {decision} — keine Benachrichtigung konfiguriert")
            return

        msg = build_email(d, route)
        deliver(msg, d)
        self.matched += 1

    def run(self):
        print(f"╔{'═'*60}╗")
        print(f"║  GRIDGermany Notification Consumer (MOCK){' '*18}║")
        print(f"╚{'═'*60}╝")
        print(f"📡 Broker: {BROKER}:{PORT}")
        print()

        client_id = f"notify-consumer-{int(time.time())}"
        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id, clean_session=True)
        except (AttributeError, TypeError):
            self.client = mqtt.Client(client_id=client_id, clean_session=True)

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
            print(f"👋 Stopped. seen {self.seen}, notified {self.matched}")


if __name__ == '__main__':
    NotificationConsumer().run()
