#!/usr/bin/env python3
"""
GRIDGermany - Joule Agent Bridge
Showcase: Berliner Stadtwerke (BS)

Verbindet das Event Mesh mit dem Grid Incident Agent (Joule Studio):
- Abonniert Alarme:  bs/{district}/mv/transformer/powerline/alarmRaised/{sensorId}
- Holt OAuth-Token (Client Credentials) vom IAS Token-Endpoint
- Ruft den Agent per A2A (JSON-RPC, POST /) mit dem Alarm als Task auf

Der Agent publiziert seine Entscheidung selbst über seine Aktion
"Publish Agent Action" zurück ins Mesh (agentActionTaken) - die Bridge
ist nur der Hinweg. Details: docs/JOULE_AGENT_EVENT_CONTRACT.md

Benötigte Umgebungsvariablen (Client-ID/Secret aus dem BTP Cockpit,
Instances & Subscriptions -> Service Binding des Agent-/AI-Core-Dienstes):
  JOULE_CLIENT_ID, JOULE_CLIENT_SECRET
Optional (Defaults passen zum Showcase):
  JOULE_AGENT_URL, JOULE_TOKEN_URL, JOULE_A2A_METHOD,
  SOLACE_HOST, SOLACE_PORT, SOLACE_USERNAME, SOLACE_PASSWORD
"""

import paho.mqtt.client as mqtt
import json
import os
import signal
import ssl
import sys
import time
import urllib.request
import urllib.parse
import uuid

# ============================================
# CONFIGURATION
# ============================================

# Broker (wie remote_controlled_sensor.py)
BROKER = os.getenv('SOLACE_HOST', 'mr-connection-gu0w0pjgchg.messaging.solace.cloud')
PORT = int(os.getenv('SOLACE_PORT', 8883))
USERNAME = os.getenv('SOLACE_USERNAME', 'solace-cloud-client')
PASSWORD = os.getenv('SOLACE_PASSWORD', 'iejmgp94muv7m5ahsfe9b50dvb')

ALARM_TOPIC_FILTER = 'bs/+/mv/transformer/powerline/alarmRaised/+'

# Joule Agent (Werte aus den Deployment-Logs des Kollegen)
AGENT_URL = os.getenv('JOULE_AGENT_URL', 'https://3ccef423-ce1a19a1.joule-stg-eu12.c.run.ai.cloud.sap/')
TOKEN_URL = os.getenv('JOULE_TOKEN_URL', 'https://a4w58gs3j.accounts400.ondemand.com/oauth2/token')
A2A_METHOD = os.getenv('JOULE_A2A_METHOD', 'message/send')
CLIENT_ID = os.getenv('JOULE_CLIENT_ID', '')
CLIENT_SECRET = os.getenv('JOULE_CLIENT_SECRET', '')


# ============================================
# OAUTH TOKEN (Client Credentials, mit Cache)
# ============================================

class TokenProvider:
    def __init__(self):
        self._token = None
        self._expires_at = 0

    def get(self):
        if self._token and time.time() < self._expires_at - 60:
            return self._token

        body = urllib.parse.urlencode({
            'grant_type': 'client_credentials',
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET
        }).encode()
        req = urllib.request.Request(
            TOKEN_URL, data=body,
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        self._token = data['access_token']
        self._expires_at = time.time() + int(data.get('expires_in', 3600))
        print("🔑 OAuth token acquired")
        return self._token


# ============================================
# A2A CALL
# ============================================

def call_agent(token_provider, alarm):
    """Send the alarm to the Grid Incident Agent as an A2A task"""
    rpc = {
        'jsonrpc': '2.0',
        'id': alarm.get('alarmId', str(uuid.uuid4())),
        'method': A2A_METHOD,
        'params': {
            'message': {
                'role': 'user',
                'messageId': str(uuid.uuid4()),
                'parts': [{
                    'kind': 'text',   # A2A-Spec (neuere Versionen)
                    'type': 'text',   # Feldname im Joule-Studio-Beispiel
                    'text': ('Neuer Transformator-Alarm aus dem BS-GRID-Event-Mesh. '
                             'Analysiere und entscheide gemäß deinen Instructions:\n'
                             + json.dumps(alarm, ensure_ascii=False))
                }]
            }
        }
    }

    req = urllib.request.Request(
        AGENT_URL,
        data=json.dumps(rpc).encode(),
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token_provider.get()}'
        }
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


# ============================================
# MQTT BRIDGE
# ============================================

class JouleBridge:
    def __init__(self):
        self.tokens = TokenProvider()
        self.client = None
        self.processed = 0
        self.failed = 0
        self.shutdown = False
        signal.signal(signal.SIGINT, self._stop)
        signal.signal(signal.SIGTERM, self._stop)

    def _stop(self, signum, frame):
        print("\n🛑 Shutting down bridge...")
        self.shutdown = True

    def _on_connect(self, client, userdata, flags, rc, *args):
        code = rc if isinstance(rc, int) else getattr(rc, 'value', 0)
        if code == 0:
            print("✅ Connected to Solace broker")
            # QoS 1 + persistente Session: Alarme werden gepuffert, wenn die Bridge offline ist
            client.subscribe(ALARM_TOPIC_FILTER, qos=1)
            print(f"📥 Subscribed to: {ALARM_TOPIC_FILTER}")
        else:
            print(f"❌ Connection failed (rc={code})")

    def _on_message(self, client, userdata, message):
        try:
            alarm = json.loads(message.payload.decode())
        except json.JSONDecodeError as e:
            print(f"❌ Invalid alarm JSON: {e}")
            return

        alarm_id = alarm.get('alarmId', '?')
        print(f"\n🚨 Alarm {alarm_id}: {alarm.get('alarmType')}={alarm.get('value')}{alarm.get('unit', '')} "
              f"[{alarm.get('severity')}] @ {alarm.get('sensorId')}")

        try:
            result = call_agent(self.tokens, alarm)
            self.processed += 1
            summary = json.dumps(result, ensure_ascii=False)
            print(f"🤖 Agent accepted task ({len(summary)} bytes response) "
                  f"| processed: {self.processed}, failed: {self.failed}")
        except Exception as e:
            self.failed += 1
            print(f"❌ Agent call failed: {e} | processed: {self.processed}, failed: {self.failed}")

    def run(self):
        if not CLIENT_ID or not CLIENT_SECRET:
            print("❌ JOULE_CLIENT_ID / JOULE_CLIENT_SECRET fehlen.")
            print("   Quelle: BTP Cockpit -> Instances & Subscriptions -> Service Binding")
            print("   Start:  JOULE_CLIENT_ID=... JOULE_CLIENT_SECRET=... python3 joule_bridge.py")
            sys.exit(1)

        print(f"╔{'═'*60}╗")
        print(f"║  GRIDGermany Joule Bridge{' '*34}║")
        print(f"╚{'═'*60}╝")
        print(f"📡 Broker: {BROKER}:{PORT}")
        print(f"🤖 Agent:  {AGENT_URL}")
        print(f"🔑 Token:  {TOKEN_URL}")
        print()

        # Fester Client-Name -> persistente Session (clean_session=False)
        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id='joule-bridge',
                clean_session=False
            )
        except (AttributeError, TypeError):
            self.client = mqtt.Client(client_id='joule-bridge', clean_session=False)

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
            print(f"👋 Bridge stopped. processed: {self.processed}, failed: {self.failed}")


if __name__ == '__main__':
    JouleBridge().run()
