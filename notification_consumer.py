#!/usr/bin/env python3
"""
GRIDGermany - Notification Consumer
Showcase: Berliner Stadtwerke (BS)

Ein additiver Consumer im Event Mesh: hört auf zwei Events und erzeugt
daraus Benachrichtigungen (E-Mail). Agent, Scheduler und Dashboard bleiben
davon unberührt — reine Event-Driven-Erweiterung (lose Kopplung).

    bs/*/mv/transformer/powerline/agentActionTaken/*      (Entscheidung des Agents)
        └─ decision == escalate        → Mail an die Leitwarte

    bs/*/mv/transformer/powerline/technicianScheduled/*   (Termin vom Scheduler)
        └─ Technikereinsatz            → Mail an den Netzservice mit
                                         Team + Techniker + Slot; Status
                                         "EINGEPLANT, noch nicht entsandt".

Damit spiegelt die Techniker-Mail den echten Ablauf: Der Agent VERANLASST
den Einsatz (dispatch_technician), die Einsatzplanung vergibt einen Termin
(technicianScheduled) — erst dann steht fest, WER WANN kommt.

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
# Wildcard, daher wird beim Abonnieren auf die MQTT-Form gemappt (siehe *_MQTT).
#
# Zwei Trigger, zwei Mail-Typen:
#   • escalate            → agentActionTaken  (kein Folge-Event, direkt aus der Entscheidung)
#   • Technikereinsatz    → technicianScheduled (der Scheduler hat Team + Slot vergeben →
#                            die Mail zeigt den konkreten Termin: "eingeplant, noch nicht entsandt")
ACTION_TOPIC_SMF = 'bs/*/mv/transformer/powerline/agentActionTaken/*'
ACTION_SUB_MQTT = 'bs/+/mv/transformer/powerline/agentActionTaken/+'
SCHEDULED_TOPIC_SMF = 'bs/*/mv/transformer/powerline/technicianScheduled/*'
SCHEDULED_SUB_MQTT = 'bs/+/mv/transformer/powerline/technicianScheduled/+'

OUTBOX = os.getenv('NOTIFY_OUTBOX', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'outbox'))
FROM_ADDR = 'bs-grid-agent@berlinerstadtwerke.example'

# decision → Benachrichtigung, ausgelöst DIREKT durch agentActionTaken.
# dispatch_technician steht hier NICHT: dafür wartet der Consumer auf das
# Folge-Event technicianScheduled (dann liegt ein konkreter Termin vor).
ROUTES = {
    'escalate': {
        # Demo-Gadget: kritische Vorfälle gehen "in Echtzeit" an den Regierenden
        # Bürgermeister. Reine Mock-Adresse (.example = RFC 2606, nicht zustellbar).
        'to': 'Regierender Bürgermeister von Berlin <kai.wegner@berlin.example>',
        'cc': 'leitwarte@berlinerstadtwerke.example',
        'salutation': 'Sehr geehrter Herr Regierender Bürgermeister,',
        'team': 'Senatskanzlei / Leitwarte',
        'subject': '⚠️ Eskalation — Regierender Bürgermeister in Kenntnis gesetzt',
        'lead': 'Der Grid Incident Agent hat einen kritischen Netzvorfall eskaliert und '
                'den Regierenden Bürgermeister von Berlin in Echtzeit informiert.',
        'action': 'Bitte den Vorfall aus der Leitwarte übernehmen; das Büro des Regierenden '
                  'Bürgermeisters ist zur Kenntnis nachrichtlich einbezogen.',
    },
}

# Zieladresse für die Technikereinsatz-Mail (kommt aus technicianScheduled).
DISPATCH_TO = 'netzservice@berlinerstadtwerke.example'


# ============================================
# MAIL BUILDING + (MOCK) DELIVERY
# ============================================

def _slug(text):
    """'Team Mitte' → 'team-mitte' (für Mock-Postfachadressen)."""
    repl = {'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss'}
    s = ''.join(repl.get(c, c) for c in text.lower())
    return ''.join(c if c.isalnum() else '-' for c in s).strip('-')


def _lines(pairs):
    """Baut ausgerichtete 'Label : Wert'-Zeilen und lässt leere Werte weg,
    damit keine sinnlosen '—'-Zeilen in der Mail stehen."""
    kept = [(k, v) for k, v in pairs if v not in (None, '', '—')]
    if not kept:
        return ''
    width = max(len(k) for k, _ in kept)
    return '\n'.join(f"{k.ljust(width)} : {v}" for k, v in kept)


def _mail(to, subject, body, decision, alarm_id, extra_headers=None, cc=None):
    msg = EmailMessage()
    msg['From'] = FROM_ADDR
    msg['To'] = to
    if cc:
        msg['Cc'] = cc
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = make_msgid(domain='berlinerstadtwerke.example')
    msg['X-BSGRID-Decision'] = decision or ''
    msg['X-BSGRID-AlarmId'] = alarm_id or ''
    for k, v in (extra_headers or {}).items():
        msg[k] = v
    msg.set_content(body)
    return msg


def build_email(decision_data, route):
    """Eskalations-Mail aus einer agentActionTaken-Entscheidung."""
    d = decision_data
    sensor = d.get('sensorId', '?')
    district = _district_of(d)
    params = d.get('parameters') or {}

    subject = f"{route['subject']} — {sensor} ({district})"
    facts = _lines([
        ('Transformator', sensor),
        ('Bezirk', district),
        ('Entscheidung', d.get('decision')),
        ('Priorität', params.get('priority')),
        ('Zielteam', params.get('targetTeam') or route['team']),
        ('Konfidenz', _pct(d.get('confidence'))),
        ('Alarm-ID', d.get('alarmId')),
        ('Zeitpunkt', d.get('timestamp')),
    ])
    reasoning = d.get('reasoning')
    reason_block = f"\n\nBegründung des Agents:\n{reasoning}" if reasoning else ''
    agent = d.get('agent')
    trailer = f"agentActionTaken" + (f" • Agent: {agent}" if agent else '')

    salutation = route.get('salutation', 'Sehr geehrte Damen und Herren,')
    body = (f"{salutation}\n\n"
            f"{route['lead']}\n\n"
            f"➡️  {route['action']}\n\n"
            f"{facts}{reason_block}\n\n"
            f"Mit freundlichen Grüßen\nIhr BS GRID Incident Agent\n\n"
            f"—\nAutomatisch erzeugt vom BS GRID Notification Consumer (Event Mesh).\n"
            f"Auslösendes Event: {trailer}\n")

    return _mail(route['to'], subject, body, d.get('decision'), d.get('alarmId'),
                 cc=route.get('cc'))


def build_scheduled_email(appt):
    """Technikereinsatz-Mail aus einem technicianScheduled-Event: der Scheduler
    hat Team + Techniker + Slot vergeben. Wortlaut: EINGEPLANT, noch nicht entsandt."""
    sensor = appt.get('sensorId', '?')
    district = appt.get('district', '—')
    tech = appt.get('technician', '—')
    team = appt.get('team', '—')
    slot = appt.get('slotLabel') or appt.get('slot') or '—'

    # Konkreter Empfänger statt "undefiniert": das zuständige Team als Anzeige-
    # name, adressiert an das Team-Postfach (aus dem Team abgeleitet).
    team_slug = _slug(team) if team not in (None, '', '—') else 'netzservice'
    to = f"{team} <{team_slug}@berlinerstadtwerke.example>" if team not in (None, '', '—') else DISPATCH_TO
    anrede = f"Sehr geehrte/r {tech}," if tech not in (None, '', '—') else f"Sehr geehrtes {team},"

    subject = f"🔧 Technikereinsatz eingeplant — {sensor} ({district})"
    facts = _lines([
        ('Transformator', sensor),
        ('Bezirk', district),
        ('Zielteam', team),
        ('Techniker', tech),
        ('Termin', slot),
        ('Alarm-ID', appt.get('alarmId')),
        ('Termin-ID', appt.get('appointmentId')),
    ])

    body = (
        f"{anrede}\n\n"
        "der Grid Incident Agent hat einen Technikereinsatz veranlasst; "
        "die Einsatzplanung hat Ihnen daraufhin den folgenden Termin zugewiesen.\n\n"
        "ℹ️  Status: EINGEPLANT — der Techniker ist noch NICHT entsandt. "
        "Der Einsatz gilt als bestätigt, sobald Sie den Termin annehmen.\n\n"
        "➡️  Bitte den Termin bestätigen und die Anfahrt vorbereiten.\n\n"
        f"{facts}\n\n"
        "Mit freundlichen Grüßen\nIhr BS GRID Incident Agent\n\n"
        "—\nAutomatisch erzeugt vom BS GRID Notification Consumer (Event Mesh).\n"
        "Auslösendes Event: technicianScheduled\n"
    )

    return _mail(to, subject, body, 'dispatch_technician', appt.get('alarmId'),
                 {'X-BSGRID-AppointmentId': appt.get('appointmentId', '')})


def deliver(msg, decision_data):
    """MOCK-Versand: Konsole + .eml-Datei. Kein echter Versand nach außen.

    Für echten Versand später hier einen Adapter einhängen, z.B.:
      - SMTP:  smtplib.SMTP(host, port) → starttls → login → send_message(msg)
      - Teams: requests.post(webhook_url, json={...})
    Die übrige Pipeline (Filtern, Mail bauen) bleibt unverändert.
    """
    os.makedirs(OUTBOX, exist_ok=True)
    # Terminmails über appointmentId benennen (sonst würde die spätere
    # Techniker-Mail die frühere Alarm-Mail mit gleicher alarmId überschreiben).
    key = decision_data.get('appointmentId') or decision_data.get('alarmId') or 'unknown'
    safe = str(key).replace('/', '_')
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


def _strip_code_fence(text):
    """Entfernt einen Markdown-Codeblock-Zaun (```json … ```), falls das LLM
    seine JSON-Antwort so verpackt. Gibt den inneren Text zurück."""
    s = text.strip()
    if s.startswith('```'):
        s = s[3:]                      # führende ```
        if s[:4].lower() == 'json':    # optionale Sprachangabe
            s = s[4:]
        end = s.rfind('```')
        if end != -1:
            s = s[:end]
    return s.strip()


def _parse_payload(raw_bytes):
    """agentActionTaken robust parsen. SAM/das LLM publiziert die Entscheidung
    in mehreren Formen — alle abfangen:
      1. direktes JSON-Objekt
      2. JSON-String, der JSON enthält (doppelt kodiert)
      3. JSON-String mit ```json …```-Markdown-Fence (LLM-Ausgabe)
    """
    raw = raw_bytes.decode()
    # Erst direkt parsen (SAM: escaped String → 1. Parse ergibt String),
    # nur bei Fehler die ```json-Fence entfernen.
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


# ============================================
# CONSUMER
# ============================================

class NotificationConsumer:
    def __init__(self):
        self.client = None
        self.matched = 0
        self.seen = 0
        self.notified_appts = set()   # appointmentId, gegen doppelte Terminmails
        self.shutdown = False
        signal.signal(signal.SIGINT, self._stop)
        signal.signal(signal.SIGTERM, self._stop)

    def _stop(self, signum, frame):
        print(f"\n🛑 Shutting down (seen {self.seen}, notified {self.matched})...")
        self.shutdown = True

    def _on_connect(self, client, userdata, flags, rc, *args):
        code = rc if isinstance(rc, int) else getattr(rc, 'value', 0)
        if code == 0:
            client.subscribe(ACTION_SUB_MQTT, qos=1)
            client.subscribe(SCHEDULED_SUB_MQTT, qos=1)
            print(f"✅ Connected — subscribed to:")
            print(f"     {ACTION_TOPIC_SMF}   → {', '.join(ROUTES)}")
            print(f"     {SCHEDULED_TOPIC_SMF} → Technikereinsatz (eingeplant)")
            print(f"   Mock-Outbox: {OUTBOX}")
        else:
            print(f"❌ Connection failed (rc={code})")

    def _on_message(self, client, userdata, message):
        self.seen += 1
        try:
            d = _parse_payload(message.payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"❌ Ungültiges JSON: {e}")
            return

        # Technikereinsatz-Mail: durch das technicianScheduled-Folge-Event
        # ausgelöst (konkreter Termin liegt vor).
        if 'technicianScheduled' in message.topic:
            appt_id = d.get('appointmentId')
            if appt_id and appt_id in self.notified_appts:
                return                       # denselben Termin nicht doppelt mailen
            if appt_id:
                self.notified_appts.add(appt_id)
            deliver(build_scheduled_email(d), d)
            self.matched += 1
            return

        # Sonst: Entscheidung direkt aus agentActionTaken (nur escalate konfiguriert).
        decision = d.get('decision')
        route = ROUTES.get(decision)
        if not route:
            print(f"·  {d.get('sensorId','?')}: {decision} — keine Benachrichtigung konfiguriert")
            return

        deliver(build_email(d, route), d)
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
