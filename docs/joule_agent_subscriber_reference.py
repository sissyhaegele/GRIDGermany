#!/usr/bin/env python3
"""
Referenz-Subscriber für den Grid Incident Agent (Joule Studio, Pro-Code).

Solace-NATIV (SMF) über die offizielle Solace PubSub+ Python API.
Wildcards sind daher '*' (eine Ebene) und '>' (Rest) — kein MQTT '+'/'#'.

Dieser Code gehört NICHT in dieses Repo, sondern in die main.py des
Joule-Agent-Projekts. Er läuft beim App-Start als Daemon-Thread PARALLEL
zum HTTP-/A2A-Server: verbindet sich mit dem SAP Advanced Event Mesh,
lauscht auf alarmRaised-Events und ruft pro Alarm den Agent lokal auf.

Warum lokal (localhost) statt über das Gateway?
- Der Subscriber läuft IM selben Container wie der Agent. Der Aufruf geht an
  http://localhost:<A2A_PORT>/ — kein JWT, kein OAuth, kein Gateway nötig.
- Der Agent publiziert seine Entscheidung wie gehabt selbst über seine
  Aktion "Publish Agent Action" (agentActionTaken via REST 9443).

Dependency: pip install solace-pubsubplus
(liegt als manylinux-Wheel für x86_64/aarch64 vor, kein Alpine/musl nötig —
 auf PyPI geprüft: solace_pubsubplus-1.11.0-py36-none-manylinux_2_17_aarch64.whl
 etc. existieren. Ein stiller Import-Fehler ist auf normalen glibc-Containern
 (Debian/Ubuntu-Basis) also unwahrscheinlich; siehe STATUS/get_status() unten,
 um es für die tatsächliche Laufzeitumgebung zu verifizieren statt zu raten.)

asset.yaml (Environment):
  SOLACE_HOST=tcps://mr-connection-gu0w0pjgchg.messaging.solace.cloud:55443
  SOLACE_VPN_NAME=germangrid_berlin
  SOLACE_USERNAME=solace-cloud-client
  SOLACE_PASSWORD=<demo-passwort>
  SOLACE_SUBSCRIBE_TOPIC=bs/*/mv/transformer/powerline/alarmRaised/*
  A2A_LOCAL_URL=http://localhost:8080/          # lokaler A2A-Endpoint des Agents

main.py: Health-Endpoint für Verifikation ohne Zugriff auf Runtime-Logs, z.B.:

  from grid_subscriber import start_subscriber, get_status
  start_subscriber()
  @app.route("/health/subscriber")
  def subscriber_health():
      return jsonify(get_status())

  # get_status() liefert sofort (auch vor dem ersten Connect-Versuch), ob der
  # solace-pubsubplus-Import geklappt hat, ob der SMF-Client aktuell verbunden
  # ist, den letzten Fehler und Plattform-Diagnostik (Python/OS/libc).
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
    from solace.messaging.receiver.message_receiver import MessageHandler
    _IMPORT_ERROR = None
except Exception as e:  # ImportError bei fehlendem Paket, OSError bei fehlender nativer Lib
    MessagingService = None
    TopicSubscription = None
    MessageHandler = object  # Platzhalter, damit _AlarmHandler(MessageHandler) unten nicht crasht
    _IMPORT_ERROR = e

# ---- Konfiguration aus dem Environment (asset.yaml) ----
# SMF/TLS-Endpoint der Solace Cloud (tcps, Port 55443). Der Broker nutzt ein
# öffentlich vertrauenswürdiges Zertifikat -> keine Insecure-Flags nötig.
HOST = os.getenv('SOLACE_HOST', 'tcps://mr-connection-gu0w0pjgchg.messaging.solace.cloud:55443')
VPN = os.getenv('SOLACE_VPN_NAME', 'germangrid_berlin')
USERNAME = os.getenv('SOLACE_USERNAME', 'solace-cloud-client')
PASSWORD = os.getenv('SOLACE_PASSWORD', '')
# SMF-Wildcards: '*' = eine Ebene, '>' = Rest. sensorId ist genau eine Ebene
# -> '*' am Ende (so spezifisch wie möglich, kein gieriges '>').
SUBSCRIBE_TOPIC = os.getenv('SOLACE_SUBSCRIBE_TOPIC',
                            'bs/*/mv/transformer/powerline/alarmRaised/*')
# Lokaler A2A-Endpoint des Agents im selben Container (kein Auth nötig)
A2A_LOCAL_URL = os.getenv('A2A_LOCAL_URL', 'http://localhost:8080/')
A2A_METHOD = os.getenv('JOULE_A2A_METHOD', 'message/send')

# Sofort beim Modul-Import gefüllt (nicht erst nach dem ersten Connect-Versuch),
# damit main.py den Stand auch dann per Health-Endpoint zeigen kann, wenn
# start_subscriber() noch nicht oder nie erfolgreich verbunden hat.
STATUS = {
    'import_ok': _IMPORT_ERROR is None,
    'connected': False,
    'subscribed_topic': SUBSCRIBE_TOPIC,
    'last_error': None if _IMPORT_ERROR is None else f'{type(_IMPORT_ERROR).__name__}: {_IMPORT_ERROR}',
    'last_error_at': None,
    'diagnostics': {
        'python': sys.version.split()[0],
        'platform': platform.platform(),
        'libc': platform.libc_ver(),  # ('glibc', 'x.xx') oder ('', '') falls nicht erkennbar (z.B. musl/Alpine)
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_status() -> dict:
    """Für einen Health-Endpoint in main.py: aktueller Subscriber-Status,
    ohne dass Runtime-Logs zugänglich sein müssen."""
    return dict(STATUS)


def invoke_agent(alarm: dict):
    """Ruft den Agent lokal per A2A (JSON-RPC) mit dem Alarm als Task auf."""
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
                             'Analysiere und entscheide gemäß deinen Instructions:\n'
                             + json.dumps(alarm, ensure_ascii=False))
                }]
            }
        }
    }
    req = urllib.request.Request(
        A2A_LOCAL_URL,
        data=json.dumps(rpc).encode(),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


class _AlarmHandler(MessageHandler):
    def on_message(self, message):
        try:
            alarm = json.loads(message.get_payload_as_string() or '{}')
        except json.JSONDecodeError as e:
            print(f"[grid-subscriber] invalid alarm JSON: {e}")
            return
        print(f"[grid-subscriber] alarm {alarm.get('alarmId')} "
              f"{alarm.get('alarmType')}={alarm.get('value')} @ {alarm.get('sensorId')}")
        try:
            invoke_agent(alarm)
        except Exception as e:
            print(f"[grid-subscriber] agent invocation failed: {e}")


def _run():
    if _IMPORT_ERROR is not None:
        # Kein Retry hier: ein fehlendes/kaputtes Paket behebt sich nicht durch
        # Warten. Laut und wiederholt loggen statt still zu bleiben, damit der
        # Ausfall in den Logs auffällt statt als unauffällig hängender Agent.
        logger.error(
            "[grid-subscriber] solace-pubsubplus Import fehlgeschlagen: %s. "
            "SMF-Subscriber ist DEAKTIVIERT, Agent reagiert nicht auf Broker-Events. "
            "Diagnostik: python=%s platform=%s libc=%s",
            STATUS['last_error'], STATUS['diagnostics']['python'],
            STATUS['diagnostics']['platform'], STATUS['diagnostics']['libc'],
        )
        return

    while True:
        try:
            service = MessagingService.builder().from_properties({
                'solace.messaging.transport.host': HOST,
                'solace.messaging.service.vpn-name': VPN,
                'solace.messaging.authentication.scheme.basic.username': USERNAME,
                'solace.messaging.authentication.scheme.basic.password': PASSWORD,
            }).build()
            service.connect()

            receiver = service.create_direct_message_receiver_builder() \
                .with_subscriptions([TopicSubscription.of(SUBSCRIBE_TOPIC)]) \
                .build()
            receiver.start()
            receiver.receive_async(_AlarmHandler())
            STATUS['connected'] = True
            STATUS['last_error'] = None
            print(f"[grid-subscriber] connected, subscribed to {SUBSCRIBE_TOPIC}")

            # Thread am Leben halten, während der Receiver asynchron zustellt.
            # Blockieren statt 'while service.is_connected' pollen -> keine
            # Abhängigkeit von einer versionsabhängigen Property; die Solace-API
            # reconnected intern selbst (Default Retry Strategy).
            threading.Event().wait()
        except Exception as e:
            STATUS['connected'] = False
            STATUS['last_error'] = f'{type(e).__name__}: {e}'
            STATUS['last_error_at'] = _now_iso()
            print(f"[grid-subscriber] connection error: {e}, retry in 5s")
            logger.debug("connection error detail:\n%s", traceback.format_exc())
            time.sleep(5)


def start_subscriber():
    """Beim App-Start aufrufen — läuft als Daemon-Thread neben dem HTTP-Server."""
    threading.Thread(target=_run, name="grid-subscriber", daemon=True).start()


# In der main.py des Agents:
#
#   from grid_subscriber import start_subscriber, get_status
#   start_subscriber()          # VOR / parallel zum HTTP-Server starten
#   @app.route("/health/subscriber")
#   def subscriber_health():
#       return jsonify(get_status())
#   app.run(host="0.0.0.0", port=8080)
#
if __name__ == '__main__':
    start_subscriber()
    while True:
        time.sleep(1)
