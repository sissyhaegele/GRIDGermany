#!/usr/bin/env python3
"""
Grid Incident Agent — SMF-Subscriber + Entscheidungs-Publisher (Joule Studio, Pro-Code).

Solace-NATIV (SMF) über die offizielle Solace PubSub+ Python API.
Wildcards sind '*' (eine Ebene) und '>' (Rest) — kein MQTT '+'/'#'.

Läuft beim App-Start als Daemon-Thread PARALLEL zum A2A/HTTP-Server:
  1. verbindet sich AUSGEHEND mit dem SAP Advanced Event Mesh (kein RDP, kein
     Webhook, kein OAuth — nur Messaging-Credentials),
  2. abonniert alarmRaised und ruft pro Alarm den Agent lokal (localhost A2A) auf,
  3. publiziert die Entscheidung des Agents als agentActionTaken über DIESELBE
     SMF-Verbindung zurück ins Mesh.

Dependency:  pip install solace-pubsubplus
(manylinux-Wheel für x86_64/aarch64, glibc — Debian/Ubuntu-Basis. Auf musl/Alpine
 schlägt der native Import fehl; das wird unten abgefangen und über get_status()
 sichtbar gemacht, statt still zu hängen.)

Konfiguration siehe asset.yaml (Environment-Variablen).
Einbindung in main.py: siehe unten / main.py in diesem Ordner.
"""

import json
import logging
import os
import platform
import sys
import threading
import time
import traceback
import urllib.request
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("grid-subscriber")

try:
    from solace.messaging.messaging_service import MessagingService
    from solace.messaging.resources.topic_subscription import TopicSubscription
    from solace.messaging.resources.topic import Topic
    from solace.messaging.receiver.message_receiver import MessageHandler
    from solace.messaging.publisher.direct_message_publisher import PublishFailureListener
    _IMPORT_ERROR = None
except Exception as e:  # ImportError (Paket fehlt) oder OSError (native Lib fehlt)
    MessagingService = None
    TopicSubscription = None
    Topic = None
    MessageHandler = object   # Platzhalter, damit _AlarmHandler(MessageHandler) nicht crasht
    _IMPORT_ERROR = e

# ---- Konfiguration aus dem Environment (asset.yaml) ----
# SMF/TLS-Endpoint der Solace Cloud (tcps, Port 55443). Öffentlich vertrauens-
# würdiges Zertifikat -> keine Insecure-Flags nötig.
HOST = os.getenv('SOLACE_HOST', 'tcps://mr-connection-89lyiztvo72.messaging.solace.cloud:55443')
VPN = os.getenv('SOLACE_VPN_NAME', 'ger_dmi')
USERNAME = os.getenv('SOLACE_USERNAME', 'solace-cloud-client')
PASSWORD = os.getenv('SOLACE_PASSWORD', '')
# SMF-Wildcards: '*' = eine Ebene, '>' = Rest. sensorId ist genau eine Ebene
# -> '*' am Ende (so spezifisch wie möglich, kein gieriges '>').
SUBSCRIBE_TOPIC = os.getenv('SOLACE_SUBSCRIBE_TOPIC',
                            'bs/*/mv/transformer/powerline/alarmRaised/*')
# Ziel-Topic-Muster für die Entscheidung. {district}/{sensorId} werden ersetzt.
PUBLISH_TOPIC_TMPL = os.getenv('SOLACE_PUBLISH_TOPIC',
                               'bs/{district}/mv/transformer/powerline/agentActionTaken/{sensorId}')
# Lokaler A2A-Endpoint des Agents im selben Container (kein Auth nötig)
A2A_LOCAL_URL = os.getenv('A2A_LOCAL_URL', 'http://localhost:8080/')
A2A_METHOD = os.getenv('JOULE_A2A_METHOD', 'message/send')
AGENT_NAME = os.getenv('AGENT_NAME', 'joule-grid-incident-agent')

# Sofort beim Import gefüllt, damit ein Health-Endpoint den Stand auch VOR dem
# ersten Connect-Versuch zeigen kann.
STATUS = {
    'import_ok': _IMPORT_ERROR is None,
    'connected': False,
    'subscribed_topic': SUBSCRIBE_TOPIC,
    'alarms_received': 0,
    'decisions_published': 0,
    'last_error': None if _IMPORT_ERROR is None else f'{type(_IMPORT_ERROR).__name__}: {_IMPORT_ERROR}',
    'last_error_at': None,
    'diagnostics': {
        'python': sys.version.split()[0],
        'platform': platform.platform(),
        'libc': platform.libc_ver(),   # ('glibc','x.xx') oder ('','') bei musl/Alpine
    },
}

# Vom Publisher-Setup gefüllt (damit _AlarmHandler die Entscheidung senden kann).
_publisher = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_status() -> dict:
    """Für den Health-Endpoint in main.py: aktueller Stand ohne Runtime-Logs."""
    return dict(STATUS)


# ---------------------------------------------------------------------------
# Agent lokal aufrufen (A2A JSON-RPC) und Entscheidung extrahieren
# ---------------------------------------------------------------------------
def invoke_agent(alarm: dict) -> dict:
    """Ruft den Agent lokal per A2A auf und gibt dessen Antwort (dict) zurück."""
    rpc = {
        'jsonrpc': '2.0',
        'id': alarm.get('alarmId', str(uuid.uuid4())),
        'method': A2A_METHOD,
        'params': {
            'message': {
                'role': 'user',
                'messageId': str(uuid.uuid4()),
                'parts': [{
                    'kind': 'text',   # A2A-Spec
                    'type': 'text',   # Joule-Studio-Beispiel
                    'text': ('Neuer Transformator-Alarm aus dem BS-GRID-Event-Mesh. '
                             'Analysiere und entscheide gemäß deinen Instructions. '
                             'Antworte NUR mit dem agentActionTaken-JSON:\n'
                             + json.dumps(alarm, ensure_ascii=False))
                }]
            }
        }
    }
    req = urllib.request.Request(
        A2A_LOCAL_URL,
        data=json.dumps(rpc).encode(),
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _extract_decision(agent_response: dict, alarm: dict) -> dict:
    """Holt das agentActionTaken-JSON aus der A2A-Antwort. Der Agent kann es als
    reinen Text, doppelt kodiert oder in einem ```json-Fence liefern — alles
    abfangen (gleiche Robustheit wie im Dashboard/Scheduler)."""
    # A2A-Antwort → Text der Agent-Nachricht herausschälen (mehrere mögliche Formen).
    text = None
    r = agent_response
    try:
        result = r.get('result', r)
        # message/send liefert i.d.R. result.message.parts[].text oder result.parts[]
        parts = (result.get('message', {}) or {}).get('parts') or result.get('parts') or []
        for p in parts:
            if isinstance(p, dict) and p.get('text'):
                text = p['text']
                break
    except AttributeError:
        pass
    if text is None:
        text = json.dumps(r)  # Fallback: ganze Antwort als Text behandeln

    data = _parse_json_loose(text)
    if not isinstance(data, dict) or 'decision' not in data:
        # Der Agent hat kein verwertbares JSON geliefert -> konservativ eskalieren,
        # damit ein Alarm nie unbeantwortet bleibt.
        data = {
            'decision': 'escalate',
            'reasoning': 'Agent lieferte keine auswertbare Entscheidung; '
                         'konservativ an die Leitwarte eskaliert.',
            'confidence': 0.3,
            'parameters': {},
        }
    # Pflichtfelder anreichern/normalisieren.
    data.setdefault('actionId', f"ACT-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:4]}")
    data['alarmId'] = alarm.get('alarmId')
    data['sensorId'] = alarm.get('sensorId')
    data.setdefault('timestamp', _now_iso())
    data['agent'] = AGENT_NAME
    data.setdefault('parameters', {})
    return data


def _parse_json_loose(text):
    """JSON aus Agent-Text robust parsen (direkt / doppelt kodiert / ```json-Fence)."""
    if isinstance(text, (dict, list)):
        return text
    s = str(text).strip()
    try:
        d = json.loads(s)
    except json.JSONDecodeError:
        d = json.loads(_strip_fence(s))
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except json.JSONDecodeError:
            d = json.loads(_strip_fence(d))
    return d


def _strip_fence(text: str) -> str:
    s = text.strip()
    if s.startswith('```'):
        s = s[3:]
        if s[:4].lower() == 'json':
            s = s[4:]
        end = s.rfind('```')
        if end != -1:
            s = s[:end]
    # auf das äußere JSON-Objekt eingrenzen
    a, b = s.find('{'), s.rfind('}')
    return s[a:b + 1] if a != -1 and b > a else s.strip()


# ---------------------------------------------------------------------------
# Entscheidung über DIESELBE SMF-Verbindung zurück ins Mesh publizieren
# ---------------------------------------------------------------------------
def publish_decision(decision: dict):
    """Publiziert agentActionTaken auf bs/{district}/…/agentActionTaken/{sensorId}."""
    if _publisher is None or Topic is None:
        raise RuntimeError('SMF-Publisher nicht initialisiert')
    sensor = decision.get('sensorId') or '?'
    district = _district_of(decision, sensor)
    topic = PUBLISH_TOPIC_TMPL.format(district=district, sensorId=sensor)
    payload = json.dumps(decision, ensure_ascii=False)
    _publisher.publish(destination=Topic.of(topic), message=payload)
    STATUS['decisions_published'] += 1
    print(f"[grid-subscriber] published {decision.get('decision')} -> {topic}")


def _district_of(decision: dict, sensor: str) -> str:
    """Bezirk für das Publish-Topic: aus der Entscheidung, sonst aus der sensorId."""
    d = decision.get('district') or (decision.get('location') or {}).get('district')
    if d:
        return d
    code_district = {
        'MIT': 'mitte', 'KRZ': 'kreuzberg', 'CHA': 'charlottenburg',
        'PRZ': 'prenzlauer berg', 'FRH': 'friedrichshain', 'NEU': 'neukoelln',
        'TMP': 'tempelhof', 'SCH': 'schoeneberg', 'WED': 'wedding', 'SPA': 'spandau',
    }
    parts = (sensor or '').split('-')
    if len(parts) >= 2:
        return code_district.get(parts[1].upper(), parts[1].lower())
    return 'agent'


# ---------------------------------------------------------------------------
# SMF-Empfang: pro Alarm den Agent aufrufen und die Entscheidung publizieren
# ---------------------------------------------------------------------------
class _AlarmHandler(MessageHandler):
    def on_message(self, message):
        try:
            alarm = json.loads(message.get_payload_as_string() or '{}')
        except json.JSONDecodeError as e:
            print(f"[grid-subscriber] invalid alarm JSON: {e}")
            return
        STATUS['alarms_received'] += 1
        print(f"[grid-subscriber] alarm {alarm.get('alarmId')} "
              f"{alarm.get('alarmType')}={alarm.get('value')} @ {alarm.get('sensorId')}")
        try:
            response = invoke_agent(alarm)
            decision = _extract_decision(response, alarm)
            publish_decision(decision)
        except Exception as e:
            STATUS['last_error'] = f'{type(e).__name__}: {e}'
            STATUS['last_error_at'] = _now_iso()
            print(f"[grid-subscriber] handling failed: {e}")


def _run():
    if _IMPORT_ERROR is not None:
        # Kein Retry: ein fehlendes/kaputtes Paket behebt sich nicht durch Warten.
        # Laut loggen, damit der Ausfall auffällt statt still zu hängen.
        logger.error(
            "[grid-subscriber] solace-pubsubplus Import fehlgeschlagen: %s. "
            "SMF-Subscriber DEAKTIVIERT, Agent reagiert nicht auf Broker-Events. "
            "python=%s platform=%s libc=%s",
            STATUS['last_error'], STATUS['diagnostics']['python'],
            STATUS['diagnostics']['platform'], STATUS['diagnostics']['libc'],
        )
        return

    global _publisher
    while True:
        try:
            service = MessagingService.builder().from_properties({
                'solace.messaging.transport.host': HOST,
                'solace.messaging.service.vpn-name': VPN,
                'solace.messaging.authentication.scheme.basic.username': USERNAME,
                'solace.messaging.authentication.scheme.basic.password': PASSWORD,
            }).build()
            service.connect()

            # Publisher (für agentActionTaken) auf derselben Verbindung.
            _publisher = service.create_direct_message_publisher_builder().build()
            _publisher.start()

            # Subscriber (für alarmRaised).
            receiver = service.create_direct_message_receiver_builder() \
                .with_subscriptions([TopicSubscription.of(SUBSCRIBE_TOPIC)]) \
                .build()
            receiver.start()
            receiver.receive_async(_AlarmHandler())

            STATUS['connected'] = True
            STATUS['last_error'] = None
            print(f"[grid-subscriber] connected {HOST} vpn={VPN}, "
                  f"subscribed {SUBSCRIBE_TOPIC}")

            # Thread am Leben halten; die Solace-API reconnected intern selbst.
            threading.Event().wait()
        except Exception as e:
            STATUS['connected'] = False
            STATUS['last_error'] = f'{type(e).__name__}: {e}'
            STATUS['last_error_at'] = _now_iso()
            _publisher = None
            print(f"[grid-subscriber] connection error: {e}, retry in 5s")
            logger.debug("connection error detail:\n%s", traceback.format_exc())
            time.sleep(5)


def start_subscriber():
    """Beim App-Start aufrufen — läuft als Daemon-Thread neben dem HTTP-Server."""
    threading.Thread(target=_run, name="grid-subscriber", daemon=True).start()


if __name__ == '__main__':
    start_subscriber()
    while True:
        time.sleep(1)
