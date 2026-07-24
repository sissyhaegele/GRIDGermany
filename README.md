# ⚡ BS GRID - Berliner Stadtwerke Grid Monitoring

Real-time power grid monitoring system using SAP Advanced Event Mesh (Solace).

## 🚀 Quick Start

```bash
# Start sensors
./bsgrid
# → Wähle Anzahl (7/10/25/50/100)
# → Enter für 50 (Standard)

# Open dashboard (neuer Tab)
open dashboards/dashboard-fiori.html   # SAP Fiori Style
# oder
open dashboards/dashboard-multi.html   # Original Style

# Stop sensors
Ctrl+C
```

## 📁 Project Structure

```
GRIDGermany/
├── bsgrid                      # Sensor Starter Script
├── remote_controlled_sensor.py # Sensor Simulation
├── solclient-full.js           # Solace JavaScript Library
│
├── dashboards/
│   ├── dashboard-fiori.html    # SAP Fiori Style Dashboard
│   ├── dashboard-multi.html    # Original Dashboard
│   └── fleet-control.html      # Sensor Management UI
│
├── scripts/
│   ├── start.sh                # Alternative Start Script
│   └── stop-sensors.sh         # Stop All Sensors
│
├── docs/
│   ├── BS_GRID_POC_DOKUMENTATION.md
│   └── SETUP_COMMANDS.sh
│
├── btp-deployment/             # SAP BTP Deployment
│   ├── mta.yaml
│   ├── xs-security.json
│   ├── deploy.sh
│   ├── app/
│   └── approuter/
│
└── archive/                    # Old files
```

## 🎯 Features

- **Scalable Sensors**: 7 / 10 / 25 / 50 / 100 sensors
- **Real-time KPIs**: Voltage, Frequency, Load, Temperature, Power
- **Berlin Map**: 10 districts with sensor locations
- **Anomaly Detection**: 3% chance, visual alerts
- **Two Dashboards**: Original + SAP Fiori Style

## 📡 Architecture

```
[Sensors] → MQTT:8883 → [SAP AEM / Solace] → SMF:443 → [Dashboard]
```

| Component | Protocol | Port |
|-----------|----------|------|
| Sensors   | MQTT/TLS | 8883 |
| Dashboard | SMF/WSS  | 443  |

## 🤖 AI / LLM Integration

Der **Grid Incident Agent** bewertet Alarme und entscheidet über die Reaktion
(Techniker, Eskalation, Sensor-Neustart, Beobachten). Er läuft im **Solace
Agent Mesh (SAM)** und nutzt ein LLM über einen OpenAI-kompatiblen Endpoint.

Für den LLM-Zugang gibt es **zwei Wege** — beide sprechen dasselbe
OpenAI-/LiteLLM-Protokoll, SAM sieht keinen Unterschied:

| Weg | Ordner | Status | Wann |
|-----|--------|--------|------|
| **HAI (Hyperspace AI), lokaler Proxy** | [`hai/`](hai/) | ✅ **aktiv genutzt** | Endpoint `localhost:6655`, kein Deployment nötig |
| **SAP AI Core via LiteLLM auf Kyma** | [`litellm-proxy/`](litellm-proxy/) | 🅿️ bereitgestellt, nicht aktiv | wenn der Proxy geteilt/serverseitig laufen soll (Team, Produktion) |

Aktueller Datenfluss (alles lokal + Solace Cloud, **kein Kyma im Pfad**):

```
Alarm → SAP AEM/Solace → SAM-Agent → HAI-Proxy (localhost:6655) → Claude/GPT
                              ↓
                   agentActionTaken → notification_consumer.py → E-Mail (outbox/)
```

- SAM Custom-Provider: Endpoint `http://localhost:6655/litellm`, Model z.B.
  `anthropic--claude-4.6-sonnet`. Details: [`hai/README.md`](hai/README.md).
- Der Kyma-Cluster (`c3d1a36`) läuft, ist aber aktuell leer — der
  `litellm-proxy/`-Weg ist dort noch **nicht** deployed.
- Agent-Instructions & Event-Contract: [`docs/`](docs/).

## 🔧 Configuration

Broker credentials in `remote_controlled_sensor.py` and dashboards:

```python
BROKER = 'mr-connection-gu0w0pjgchg.messaging.solace.cloud'
VPN = 'germangrid_berlin'
```

## 📊 KPIs

| KPI | Normal | Warning | Critical |
|-----|--------|---------|----------|
| Frequency | 49.98-50.02 Hz | <49.95 / >50.05 | <49.80 / >50.20 |
| Voltage | 228-232 V | <225 / >235 | <220 / >240 |
| Load | 50-70% | >85% | >95% |
| Temperature | 35-50°C | >60°C | >75°C |

---

**Built for Berliner Stadtwerke • SAP Advanced Event Mesh • Real-Time Grid Monitoring**
