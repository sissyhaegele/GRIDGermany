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

asset.yaml (Environment):
  SOLACE_HOST=tcps://mr-connection-gu0w0pjgchg.messaging.solace.cloud:55443
  SOLACE_VPN_NAME=germangrid_berlin
  SOLACE_USERNAME=solace-cloud-client
  SOLACE_PASSWORD=<demo-passwort>
  SOLACE_SUBSCRIBE_TOPIC=bs/*/mv/transformer/powerline/alarmRaised/*
  A2A_LOCAL_URL=http://localhost:8080/          # lokaler A2A-Endpoint des Agents
"""

import json
import os
import threading
import time
import urllib.request
import uuid

from solace.messaging.messaging_service import MessagingService
from solace.messaging.resources.topic_subscription import TopicSubscription
from solace.messaging.receiver.message_receiver import MessageHandler

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
            print(f"[grid-subscriber] connected, subscribed to {SUBSCRIBE_TOPIC}")

            while service.is_connected:
                time.sleep(1)
        except Exception as e:
            print(f"[grid-subscriber] connection error: {e}, retry in 5s")
            time.sleep(5)


def start_subscriber():
    """Beim App-Start aufrufen — läuft als Daemon-Thread neben dem HTTP-Server."""
    threading.Thread(target=_run, name="grid-subscriber", daemon=True).start()


# In der main.py des Agents:
#
#   from grid_subscriber import start_subscriber
#   start_subscriber()          # VOR / parallel zum HTTP-Server starten
#   app.run(host="0.0.0.0", port=8080)
#
if __name__ == '__main__':
    start_subscriber()
    while True:
        time.sleep(1)
