# BS GRID × SAP Joule Agent — Event Contract

**Zweck:** Schnittstellen-Vertrag zwischen dem BS-GRID-Broker (SAP Advanced Event Mesh / Solace Cloud)
und dem Joule Agent (gebaut in Joule Studio).
**Stand:** Juli 2026

---

## 1. Architektur-Überblick

Der Agent ist ein **Pro-Code-Agent** und lauscht **selbst** am Event Mesh
(MQTT-Subscriber in seiner `main.py`, parallel zum HTTP-/A2A-Server). Er zieht
die Alarme also aktiv — kein Push, kein Gateway, kein JWT auf dem Hinweg.

```
┌──────────────┐  MQTT/TLS   ┌──────────────────┐   MQTT/TLS (8883)   ┌─────────────────┐
│   Sensoren   │ ──────────▶ │  Solace Cloud    │ ──────────────────▶ │  Joule Agent    │
│  (Python)    │  alarmRaised│  Event Mesh      │  Agent subscribed   │  (Joule Studio) │
└──────────────┘             │                  │  auf alarmRaised    │  ┌───────────┐  │
                             │                  │                     │  │Subscriber │  │
┌──────────────┐   SMF/WSS   │                  │                     │  │→ localhost│  │
│  Dashboard   │ ◀────────── │                  │  ◀───────────────── │  │  A2A      │  │
│  (Browser)   │agentAction- │                  │  REST 9443          │  └───────────┘  │
└──────────────┘   Taken     └──────────────────┘  agentActionTaken   └─────────────────┘
```

Der Agent **subscribed** die Alarme direkt (Messaging-Credentials, kein OAuth)
und **antwortet** mit einem `agentActionTaken`-Event per REST auf Port 9443.
Der Subscriber ruft den Agent in-process über seinen lokalen A2A-Endpoint auf.
Referenz-Implementierung: [`joule_agent_subscriber_reference.py`](joule_agent_subscriber_reference.py).

---

## 2. Broker-Verbindung

| Parameter | Wert |
|-----------|------|
| Host | `mr-connection-gu0w0pjgchg.messaging.solace.cloud` |
| Message VPN | `germangrid_berlin` |
| MQTT/TLS (Agent-Subscriber, Hinweg) | Port `8883` |
| REST Messaging (agentActionTaken, Rückkanal) | Port `9443` (HTTPS) |
| AMQP 1.0 (optional, Queue-Konsum) | Port `5671` (TLS) |
| Credentials | siehe `BS_GRID_POC_DOKUMENTATION.md`, Abschnitt 3 |

---

## 3. Event: `alarmRaised` (Broker → Agent)

**Topic:**
```
bs/{bezirk}/mv/transformer/powerline/alarmRaised/v1/{sensorId}
```
- MQTT-Wildcard zum Abonnieren: `bs/+/mv/transformer/powerline/alarmRaised/v1/#`
- SMF-Wildcard: `bs/*/mv/transformer/powerline/alarmRaised/v1/>`
- QoS 1 / persistent — Alarme dürfen nicht verloren gehen.
- Ausgelöst **einmal pro Anomalie-Beginn** (nicht pro Messwert). Bei 50 Sensoren
  entstehen im Demo-Betrieb grob 1–2 Alarme pro Sekunde (3 % Anomalie-Rate);
  für ruhigere Demos die Rate im Sensor senken.

**Payload (Beispiel):**
```json
{
  "alarmId": "ALM-TRF-KRZ-042-20260703071326",
  "sensorId": "TRF-KRZ-042",
  "timestamp": "2026-07-03T07:13:26.085Z",
  "severity": "critical",
  "alarmType": "temperature",
  "value": 78.3,
  "unit": "°C",
  "threshold": { "max": 60.0 },
  "location": {
    "district": "kreuzberg",
    "lat": 52.4883,
    "lon": 13.4016,
    "address": "Kottbusser Tor"
  },
  "recentMetrics": [
    {
      "timestamp": "2026-07-03T07:13:17.000Z",
      "status": "normal",
      "temperature": 52.1, "voltage": 229.4, "frequency": 50.01,
      "load": 61.2, "power": 141.8, "uptime": 100.0
    }
  ]
}
```

**Felder:**

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `alarmId` | string | Eindeutige Alarm-ID, Korrelations-Schlüssel für die Agent-Antwort |
| `sensorId` | string | z.B. `TRF-KRZ-042` |
| `timestamp` | string (ISO 8601, UTC) | Zeitpunkt des Alarms |
| `severity` | `warning` \| `critical` | Abgeleitet aus Schwellwert-Überschreitung |
| `alarmType` | `voltage` \| `frequency` \| `load` \| `temperature` | Betroffene Messgröße |
| `value` | number | Auslösender Messwert |
| `unit` | string | Einheit des Messwerts |
| `threshold` | object | Entweder `{max}` (Obergrenze) oder `{nominal, maxDeviation}` (Abweichung vom Sollwert) |
| `location` | object | Bezirk + Koordinaten + Adresse |
| `recentMetrics` | array (≤ 10) | Die letzten Messwerte **inklusive** des anomalen — Analysekontext für den Agent, kein Rück-Query nötig |

---

## 4. Event: `agentActionTaken` (Agent → Broker)

Wenn der Agent entschieden hat, publiziert er seine Entscheidung zurück ins Mesh —
das Dashboard zeigt sie live an.

**Topic:**
```
bs/{bezirk}/mv/transformer/powerline/agentActionTaken/v1/{sensorId}
```
`{bezirk}` und `{sensorId}` aus dem Alarm übernehmen (`location.district`, `sensorId`).

**Versand per REST Messaging** (einfachster Weg aus Joule Studio — normaler HTTP-Call):
```
POST https://mr-connection-gu0w0pjgchg.messaging.solace.cloud:9443/bs/kreuzberg/mv/transformer/powerline/agentActionTaken/v1/TRF-KRZ-042
Authorization: Basic <username:password>
Content-Type: application/json
```
Der Topic ist der URL-Pfad; der Body ist das Event-Payload.

**Payload (Beispiel):**
```json
{
  "actionId": "ACT-20260703071330-001",
  "alarmId": "ALM-TRF-KRZ-042-20260703071326",
  "sensorId": "TRF-KRZ-042",
  "timestamp": "2026-07-03T07:13:30.412Z",
  "agent": "joule-grid-incident-agent",
  "decision": "dispatch_technician",
  "reasoning": "Temperatur 78,3°C liegt 18°C über dem Grenzwert; die letzten 10 Messwerte zeigen einen steilen Anstieg statt eines Ausreißers. Physische Inspektion erforderlich.",
  "confidence": 0.87,
  "parameters": {
    "priority": "high",
    "targetTeam": "Netzservice Kreuzberg"
  }
}
```

**Felder:**

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `actionId` | string | Eindeutige Aktions-ID |
| `alarmId` | string | Korrelation zum auslösenden Alarm |
| `sensorId` | string | Betroffener Sensor |
| `timestamp` | string (ISO 8601, UTC) | Entscheidungszeitpunkt |
| `agent` | string | Name/ID des entscheidenden Agents |
| `decision` | `dispatch_technician` \| `restart_sensor` \| `monitor` \| `escalate` | Getroffene Entscheidung (erweiterbar) |
| `reasoning` | string | Begründung des Agents — wird im Dashboard angezeigt, bitte kurz und deutsch |
| `confidence` | number (0–1) | Konfidenz der Entscheidung (optional) |
| `parameters` | object | Entscheidungsspezifische Details (optional) |

**Option für später:** Bei `decision: "restart_sensor"` kann der Agent zusätzlich direkt den
bestehenden Fleet-Control-Kanal nutzen: `control/sensor/{sensorId}/command` mit
`{"command": "stop"|"start"|"pause", "requestId": "<actionId>"}` — dann schließt sich der Loop
bis zur tatsächlichen Aktion.

---

## 5. Zustellung der Alarme an den Agent

**Aktueller Weg: Der Agent subscribed selbst (Pro-Code, MQTT-Subscriber in `main.py`).**
Kein Broker-seitiges Setup nötig, keine Bridge, kein OAuth/JWT auf dem Hinweg —
der Agent meldet sich mit den Solace-Messaging-Credentials am Broker an und lauscht.

**a) `asset.yaml` (Environment des Agents):**

| Variable | Wert |
|----------|------|
| `SOLACE_HOST` | `tcps://mr-connection-gu0w0pjgchg.messaging.solace.cloud:55443` (SMF/TLS) |
| `SOLACE_VPN_NAME` | `germangrid_berlin` |
| `SOLACE_USERNAME` | `solace-cloud-client` |
| `SOLACE_PASSWORD` | siehe `BS_GRID_POC_DOKUMENTATION.md`, Abschnitt 3 |
| `SOLACE_SUBSCRIBE_TOPIC` | `bs/*/mv/transformer/powerline/alarmRaised/*` |
| `A2A_LOCAL_URL` | `http://localhost:8080/` (lokaler A2A-Endpoint) |

**Solace-nativ (SMF), nicht MQTT.** Wildcards sind `*` (eine Ebene) und `>`
(Rest) — `+`/`#` gibt es nur auf der MQTT-Schnittstelle. Die `sensorId` ist
genau eine Ebene, also `…/alarmRaised/*` (nicht das gierige `…/alarmRaised/>`).
Die von Joule Studio vorgeschlagene Form `bs/+/…/>` mischte MQTT und SMF und
war ungültig. Das Dashboard subscribed bereits SMF-nativ mit `*`.

**b) `main.py`:** MQTT-Subscriber als Daemon-Thread parallel zum HTTP-Server
starten. Fertige Referenz-Implementierung (spiegelt die bewährte Sensor-Verbindung):
[`joule_agent_subscriber_reference.py`](joule_agent_subscriber_reference.py) —
`start_subscriber()` vor `app.run(...)` aufrufen.

**c) Optional — Durable Queue statt direkter Topic-Subscription.** Bei direkter
Topic-Subscription verliert der Agent Alarme, während er offline ist. Robuster:
eine Queue (`Q.JOULE.ALARMS`) mit Topic-Abo `bs/*/mv/transformer/powerline/alarmRaised/v1/>`
im Broker Manager anlegen und den Agent aus der Queue konsumieren lassen (AMQP,
Port 5671). Für Live-Demos reicht die direkte Subscription.

---

### Fallback-Wege (nicht aktiv, nur zur Referenz)

<details>
<summary>A2A-Bridge (<code>joule_bridge.py</code>) — falls der Agent NICHT selbst subscriben soll</summary>

Externer Python-Service, der Alarme abonniert, ein OAuth-Token holt und den Agent
per A2A von außen aufruft. Braucht Client-ID/Secret aus dem BTP-Binding des
Agent-Gateways. Start: `JOULE_CLIENT_ID=... JOULE_CLIENT_SECRET=... python3 joule_bridge.py`.
Agent-URL `https://3ccef423-ce1a19a1.joule-stg-eu12.c.run.ai.cloud.sap/`,
Token-URL `https://a4w58gs3j.accounts400.ondemand.com/oauth2/token`.

</details>

<details>
<summary>REST Delivery Point (RDP) — falls der Agent einen einfachen Webhook-Trigger bekommt</summary>

Der Broker pusht jeden Alarm als HTTP POST an einen Endpoint des Agents.
Setup im Solace Cloud **Broker Manager**:

1. **Queue anlegen:** `Q.JOULE.ALARMS` (exclusive, respect TTL optional)
2. **Topic-Subscription auf die Queue:** `bs/*/mv/transformer/powerline/alarmRaised/>` *(SMF-Syntax)*
3. **RDP anlegen:** `RDP.JOULE.AGENT`
   - REST Client (UI-Tab „REST Clients"; in der SEMP-API „REST Consumer"):
     Host/Port/TLS des Agent-Endpoints *(URL kommt vom Joule-Kollegen)*
   - Queue Binding: `Q.JOULE.ALARMS`, Post-Request-Target = Pfad des Endpoints
   - Authentifizierung nach Bedarf des Endpoints (Basic/OAuth/Header)
4. RDP, REST Client und Queue Binding **enablen** (drei separate Schalter) —
   ab dann wird jeder Alarm zugestellt, bei Nichterreichbarkeit puffert
   die Queue (kein Alarmverlust).

**Alternative: AMQP 1.0** (Port 5671) — falls die Agent-Seite lieber selbst konsumiert,
z.B. über eine Middleware. Queue `Q.JOULE.ALARMS` kann identisch genutzt werden.

</details>

---

**Stand der Integration:**
- [x] Architektur: Agent subscribed selbst am Mesh (Pro-Code MQTT-Subscriber)
- [x] Referenz-Subscriber `joule_agent_subscriber_reference.py` (offline getestet)
- [x] asset.yaml-Werte + Wildcard-Syntax dokumentiert
- [ ] Subscriber in die Agent-`main.py` übernehmen und `start_subscriber()` aufrufen
- [ ] `A2A_LOCAL_URL` auf den tatsächlichen lokalen Port des Agents setzen
- [ ] End-to-End-Test: Sensor-Alarm → Agent-Subscriber → agentActionTaken im Dashboard
- [ ] Finale Liste der `decision`-Werte, sobald der Use Case geschärft ist

---

## 6. Maschinenlesbare Spezifikation

Die AsyncAPI-Definition beider Events liegt in
[`joule-agent-asyncapi.yaml`](joule-agent-asyncapi.yaml) — geeignet als Import/Referenz
für Joule Studio, Code-Generierung oder das Event Portal.
