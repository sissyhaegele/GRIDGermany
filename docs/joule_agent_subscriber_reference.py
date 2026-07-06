#!/usr/bin/env python3
"""
Referenz-Subscriber für den Grid Incident Agent (Joule Studio, Pro-Code).

Dieser Code gehört NICHT in dieses Repo, sondern in die main.py des
Joule-Agent-Projekts. Er läuft beim App-Start als Daemon-Thread PARALLEL
zum HTTP-/A2A-Server: er verbindet sich mit dem SAP Advanced Event Mesh,
lauscht auf alarmRaised-Events und ruft pro Alarm den Agent lokal auf.

Warum lokal (localhost) statt über das Gateway?
- Der Subscriber läuft IM selben Container wie der Agent. Der Aufruf geht an
  http://localhost:<A2A_PORT>/ — kein JWT, kein OAuth, kein Gateway nötig.
- Der Agent publiziert seine Entscheidung wie gehabt selbst über seine
  Aktion "Publish Agent Action" (agentActionTaken via REST 9443).

Verbindung = identisch zu remote_controlled_sensor.py (MQTT/TLS, Port 8883),
damit Host/Port/Auth garantiert kompatibel sind.

asset.yaml (Environment):
  SOLACE_HOST=mr-connection-gu0w0pjgchg.messaging.solace.cloud
  SOLACE_PORT=8883
  SOLACE_USERNAME=solace-cloud-client
  SOLACE_PASSWORD=<demo-passwort>
  SOLACE_VPN_NAME=germangrid_berlin            # bei MQTT nicht zwingend nötig
  SOLACE_SUBSCRIBE_TOPIC=bs/+/mv/transformer/powerline/alarmRaised/v1/#
  A2A_LOCAL_URL=http://localhost:8080/          # lokaler A2A-Endpoint des Agents
"""

import paho.mqtt.client as mqtt
import json
import os
import ssl
import threading
import time
import urllib.request
import uuid

# ---- Konfiguration aus dem Environment (asset.yaml) ----
BROKER = os.getenv('SOLACE_HOST', 'mr-connection-gu0w0pjgchg.messaging.solace.cloud')
PORT = int(os.getenv('SOLACE_PORT', 8883))
USERNAME = os.getenv('SOLACE_USERNAME', 'solace-cloud-client')
PASSWORD = os.getenv('SOLACE_PASSWORD', '')
# MQTT-Wildcards: + = eine Ebene, # = beliebig viele. NICHT mit SMF (* und >) mischen!
SUBSCRIBE_TOPIC = os.getenv('SOLACE_SUBSCRIBE_TOPIC',
                            'bs/+/mv/transformer/powerline/alarmRaised/v1/#')
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


def _on_connect(client, userdata, flags, rc, *args):
    code = rc if isinstance(rc, int) else getattr(rc, 'value', 0)
    if code == 0:
        client.subscribe(SUBSCRIBE_TOPIC, qos=1)
        print(f"[grid-subscriber] connected, subscribed to {SUBSCRIBE_TOPIC}")
    else:
        print(f"[grid-subscriber] connect failed rc={code}")


def _on_message(client, userdata, message):
    try:
        alarm = json.loads(message.payload.decode())
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
    client_id = f"grid-incident-agent-{uuid.uuid4().hex[:8]}"
    try:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id, clean_session=True)
    except (AttributeError, TypeError):
        client = mqtt.Client(client_id=client_id, clean_session=True)

    client.username_pw_set(USERNAME, PASSWORD)
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.on_connect = _on_connect
    client.on_message = _on_message

    # loop_forever kümmert sich um automatische Reconnects
    while True:
        try:
            client.connect(BROKER, PORT, keepalive=30)
            client.loop_forever()
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
