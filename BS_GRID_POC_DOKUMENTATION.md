# BS GRID POC - Technische Dokumentation

**Projekt:** Berliner Stadtwerke - Echtzeit Netzüberwachung  
**Stand:** 14. Januar 2026  
**Ziel:** Demonstration von Event-Driven Architecture mit Solace Event Mesh

---

## 1. Projekt-Übersicht

### Use Case
Echtzeit-Monitoring von Stromnetztransformatoren in Berliner Bezirken mit dem Ziel:
- Sensoren und Kameras an kritischen Infrastrukturpunkten
- Frühzeitige Erkennung von Sabotage-Versuchen
- Sofortige Alarmierung bei Anomalien

### Referenz: Swissgrid
Swissgrid nutzt Solace zur kontinuierlichen Überprüfung des Stromnetzes. Grid-Komponenten melden ihren Status jede Sekunde. Reagiert eine Stromleitung 5x hintereinander nicht, wird automatisch der Notfallplan ausgelöst.

### Skalierung
- **POC:** 1-100 Sensoren
- **Event Rate:** 1 Event/Sekunde pro Sensor
- **Max. Durchsatz:** 100 Events/Sekunde = 360.000 Events/Stunde

---

## 2. Architektur

```
┌─────────────────┐     MQTT (8883)      ┌─────────────────┐
│  Python Sensors │ ──────────────────▶  │                 │
│  (1-100 Stück)  │                      │  Solace Cloud   │
└─────────────────┘                      │  Event Mesh     │
                                         │                 │
┌─────────────────┐     MQTT (8443)      │  germangrid_    │
│  Fleet Control  │ ◀────────────────▶   │  berlin         │
│  (Browser)      │                      │                 │
└─────────────────┘                      │                 │
                                         │                 │
┌─────────────────┐     SMF (443)        │                 │
│  Dashboard      │ ◀────────────────    │                 │
│  (Browser)      │                      └─────────────────┘
└─────────────────┘
```

### Protokoll-Aufteilung

| Komponente | Protokoll | Port | Wildcard Syntax |
|------------|-----------|------|-----------------|
| **Sensoren** | MQTT über TLS | 8883 | `+` (single) `#` (multi) |
| **Fleet Control** | MQTT über WebSocket | 8443 | `+` (single) `#` (multi) |
| **Dashboard** | SMF über WebSocket | 443 | `*` (single) `>` (multi) |

### Warum Multi-Protokoll?
Solace übersetzt automatisch zwischen MQTT und SMF. Das demonstriert:
- Protokoll-Unabhängigkeit des Event Mesh
- IoT-Geräte (MQTT) und Enterprise-Anwendungen (SMF) auf einer Plattform
- Flexible Integration ohne Code-Änderungen

---

## 3. Broker-Konfiguration

### Solace Cloud Credentials

```
Host:     mr-connection-gu0w0pjgchg.messaging.solace.cloud
VPN:      germangrid_berlin
Username: solace-cloud-client
Password: iejmgp94muv7m5ahsfe9b50dvb
```

### Ports

| Protokoll | Port | Verwendung |
|-----------|------|------------|
| MQTT/TLS | 8883 | Python Sensoren |
| MQTT/WSS | 8443 | Fleet Control (Browser) |
| SMF/WSS | 443 | Dashboard (Browser) |

---

## 4. Topic Design

### Struktur (Solace Best Practices)

```
bs/{district}/mv/transformer/powerline/statusUpdated/v1/{sensorId}
```

**Beispiele:**
```
bs/mitte/mv/transformer/powerline/statusUpdated/v1/TRF-MIT-001
bs/kreuzberg/mv/transformer/powerline/statusUpdated/v1/TRF-KRZ-005
bs/charlottenburg/mv/transformer/powerline/statusUpdated/v1/TRF-CHA-017
```

### Wildcard Subscriptions

| Protokoll | Syntax | Beispiel |
|-----------|--------|----------|
| MQTT | `+` / `#` | `bs/+/mv/transformer/powerline/statusUpdated/v1/+` |
| SMF | `*` / `>` | `bs/*/mv/transformer/powerline/statusUpdated/v1/*` |

### Control Plane Topic (MQTT)

```
control/sensor/{sensorId}/command    → Commands an Sensor
control/sensor/{sensorId}/status     → Status vom Sensor
```

**Fleet Control subscribt:**
```
control/sensor/+/status
```

---

## 5. Queues (Solace Console)

| Queue Name | Topic Subscription |
|------------|-------------------|
| `PowerlineTracker-PowerlineHeartbeat` | `bs/*/mv/transformer/powerline/statusUpdated/v1/*` |
| `PowerlineTracker-PowerlineStatusUpdated` | `bs/*/mv/transformer/powerline/statusUpdated/v1/*` |

---

## 6. Sensor Payload Format

### Daten-Payload (von Sensor an Dashboard)

```json
{
  "sensorId": "TRF-MIT-042",
  "timestamp": "2026-01-14T15:30:00.000Z",
  "status": "normal",
  "location": {
    "district": "mitte",
    "lat": 52.5200,
    "lon": 13.4050,
    "address": "Alexanderplatz"
  },
  "metrics": {
    "voltage": 230.5,
    "frequency": 50.01,
    "load": 65.2,
    "power": 147.8,
    "temperature": 45.3,
    "uptime": 99.97
  }
}
```

### Energie-KPIs (Grid Metriken)

| KPI | Feld | Einheit | Normalbereich | Anomalie-Schwelle |
|-----|------|---------|---------------|-------------------|
| Spannung | `voltage` | V | 228-232 | <220 oder >240 |
| Frequenz | `frequency` | Hz | 49.98-50.02 | <49.95 oder >50.05 |
| Last | `load` | % | 50-70 | >85 |
| Leistung | `power` | kW | basiert auf Last | - |
| Temperatur | `temperature` | °C | 40-55 | >60 |
| Verfügbarkeit | `uptime` | % | >99 | - |

### Anomalie-Typen

| Typ | Trigger | Terminal-Anzeige |
|-----|---------|------------------|
| Voltage | <220V oder >240V | ⚡ VOLTAGE ANOMALY! |
| Frequency | <49.95Hz oder >50.05Hz | 〰️ FREQUENCY ANOMALY! |
| Load | >85% | 📈 LOAD ANOMALY! |
| Temperature | >60°C | 🔥 TEMPERATURE SPIKE! |

### Anomalie-Verhalten
- **Chance:** ~3% pro Sekunde pro Sensor
- **Dauer:** 2 Sekunden (rot im Dashboard)
- **Recovery:** Automatisch nach 2 Sekunden (grün)

### Control Command Payload (von Fleet Control an Sensor)

```json
{
  "command": "start",
  "requestId": "req-1705245600"
}
```

**Mögliche Commands:** `start`, `stop`, `pause`

### Status Response (von Sensor an Fleet Control)

```json
{
  "sensorId": "TRF-MIT-042",
  "status": "running",
  "timestamp": "2026-01-14T15:30:00.000Z"
}
```

---

## 7. Sensor IDs und Bezirke

### ID Format

```
TRF-{DISTRICT_CODE}-{NUMBER}
```

### Bezirks-Codes

| Code | Bezirk | Anzahl Sensoren |
|------|--------|-----------------|
| MIT | Mitte | 15 |
| KRZ | Kreuzberg | 12 |
| CHA | Charlottenburg | 12 |
| PRZ | Prenzlauer Berg | 12 |
| FRH | Friedrichshain | 10 |
| NEU | Neukölln | 10 |
| TMP | Tempelhof | 8 |
| SCH | Schöneberg | 8 |
| WED | Wedding | 7 |
| SPA | Spandau | 6 |
| **Total** | | **100** |

### Sensor-Verteilung (Round-Robin)
Die Sensoren sind so sortiert, dass bei jeder Auswahl (z.B. 25) alle Bezirke gleichmäßig vertreten sind:
- 10 Sensoren = 1 pro Bezirk
- 20 Sensoren = 2 pro Bezirk
- 25 Sensoren = 2-3 pro Bezirk (alle 10 Bezirke)

---

## 8. Dateien

### Projektstruktur

```
/Users/sissyhaegele/Projekte/GRIDGermany/
├── dashboard-multi.html         # Echtzeit-Visualisierung (SMF)
├── solclient-full.js            # Solace JavaScript API (lokal)
├── fleet-control.html           # Sensor-Steuerung (MQTT)
├── remote_controlled_sensor.py  # Python Sensor mit Grid-KPIs
├── start.sh                     # Bash Script für 1-100 Sensoren
└── BS_GRID_POC_DOKUMENTATION.md # Diese Dokumentation
```

### Datei-Details

| Datei | Protokoll | Library | Funktion |
|-------|-----------|---------|----------|
| `dashboard-multi.html` | SMF/WSS | solclient-full.js (lokal) | Visualisierung, Berlin-Karte, Live Event Stream |
| `fleet-control.html` | MQTT/WSS | mqtt.min.js (jsDelivr CDN) | Start/Stop 1-100 Sensoren |
| `remote_controlled_sensor.py` | MQTT/TLS | paho-mqtt | Sensor-Simulation mit Grid-KPIs |
| `start.sh` | - | - | Startet N Sensoren parallel (round-robin) |

---

## 9. Dashboard Features

### Sensor-Kacheln (2x2 Grid)
```
┌──────────────┬──────────────┐
│ Voltage      │ Frequency    │
│ 230 V        │ 50.01 Hz     │
├──────────────┼──────────────┤
│ Load         │ Temperature  │
│ 65 %         │ 45 °C        │
└──────────────┴──────────────┘
```

### Summary Statistics
- Avg Voltage (V)
- Avg Frequency (Hz)
- Avg Load (%)
- Events/Sec
- Anomalies (aktuell aktive)

### Live Event Stream
- Alle Sensor-Events in Echtzeit
- Anomalien rot hervorgehoben
- Live Counter: `● 25 events/sec | Total: 1,247`

### Berlin-Karte
- Marker pro Sensor (positioniert nach Bezirk)
- Grün = Normal, Rot = Anomalie (pulsierend)
- Tooltip mit Details bei Hover

---

## 10. JavaScript Libraries

### Dashboard (SMF)

```html
<script src="solclient-full.js"></script>
```
**Hinweis:** Lokal eingebunden wegen CDN-Problemen mit `file://`

### Fleet Control (MQTT)

```html
<script src="https://cdn.jsdelivr.net/npm/mqtt@5.3.4/dist/mqtt.min.js"></script>
```
**Hinweis:** jsDelivr CDN funktioniert zuverlässiger als unpkg

### Bekannte CDN-Probleme

| CDN | Status |
|-----|--------|
| `products.solace.com` | ❌ Lädt nicht |
| `unpkg.com/solclientjs` | ❌ Datei nicht gefunden |
| `unpkg.com/mqtt` | ⚠️ Manchmal blockiert bei `file://` |
| `cdn.jsdelivr.net/npm/mqtt` | ✅ Funktioniert |

---

## 11. Start-Befehle

### Sensoren starten (Terminal)

```bash
cd /Users/sissyhaegele/Projekte/GRIDGermany
./start.sh
# → Wähle 1/3/7/10/25/50/100
```

### Einzelnen Sensor starten

```bash
cd /Users/sissyhaegele/Projekte/GRIDGermany
export SOLACE_HOST="mr-connection-gu0w0pjgchg.messaging.solace.cloud"
export SOLACE_PORT="8883"
export SOLACE_USERNAME="solace-cloud-client"
export SOLACE_PASSWORD="iejmgp94muv7m5ahsfe9b50dvb"
export SENSOR_ID="TRF-MIT-001"
python3 remote_controlled_sensor.py
```

### Browser öffnen

```bash
open /Users/sissyhaegele/Projekte/GRIDGermany/fleet-control.html
open /Users/sissyhaegele/Projekte/GRIDGermany/dashboard-multi.html
```

### Falls CDN-Probleme auftreten → HTTP Server

```bash
cd /Users/sissyhaegele/Projekte/GRIDGermany
python3 -m http.server 8080
```
Dann öffnen:
- `http://localhost:8080/fleet-control.html`
- `http://localhost:8080/dashboard-multi.html`

---

## 12. Demo-Ablauf

1. **Terminal:** `./start.sh` → z.B. "25" wählen
2. **Browser 1:** `fleet-control.html` öffnen → Connect → "25" → Start Selected
3. **Browser 2:** `dashboard-multi.html` öffnen → Connect → Live-Daten erscheinen
4. **Zeigen:**
   - Berlin-Karte mit Sensoren in allen 10 Bezirken
   - Live Event Stream mit Sensor-Logs
   - Events/Sec Counter
   - Anomalien (rot pulsierend, 2 Sekunden, dann Recovery)
5. **Stoppen:** Fleet Control → Stop All

### Demo-Highlights
- **Event-Driven:** Daten fließen in Echtzeit ohne Polling
- **Multi-Protokoll:** MQTT (Sensoren) → SMF (Dashboard)
- **Skalierung:** 1 bis 100 Sensoren mit einem Klick
- **Anomalie-Erkennung:** Automatische Alerts bei Grid-Stress

---

## 13. Zielarchitektur (SAP Integration)

```
Sensoren → Solace Event Mesh → SAP Integration Suite (AEM)
                             → SAP Build (Apps, Process Automation)
                             → SAP Business Data Cloud (BDC)
                             → SAP Analytics Cloud (SAC)
```

### Geplante Erweiterungen

- **AEM:** Event-Flows für Routing und Transformation
- **SAP Build Apps:** Mobile App für Techniker
- **SAP Build Process Automation:** Automatische Workflows bei Anomalien
- **BDC:** Zentrale Datenschicht für Event-Persistenz
- **SAC:** Dashboards, Predictive Maintenance KPIs, SAIDI/SAIFI Reporting

---

## 14. Fehlerbehebung

### Problem: "Solace library not loaded"
**Lösung:** `solclient-full.js` muss lokal im gleichen Ordner liegen

### Problem: "mqtt is not defined"
**Lösung:** jsDelivr CDN verwenden: `https://cdn.jsdelivr.net/npm/mqtt@5.3.4/dist/mqtt.min.js`

### Problem: CDN Libraries laden nicht
**Lösung:** HTTP Server starten: `python3 -m http.server 8080`

### Problem: Sensoren empfangen keine Commands
**Prüfen:**
1. Fleet Control connected?
2. Sensor läuft und wartet auf Commands?
3. Topic stimmt: `control/sensor/{sensorId}/command`

### Problem: Dashboard zeigt keine Daten
**Prüfen:**
1. Dashboard connected (SMF)?
2. Sensoren senden Daten (MQTT)?
3. Topic-Subscription: `bs/*/mv/transformer/powerline/statusUpdated/v1/*`

### Problem: Nur ein Bezirk im Dashboard
**Lösung:** Neue `start.sh` und `fleet-control.html` verwenden (round-robin Sortierung)

### Problem: Anomalien bleiben dauerhaft rot
**Lösung:** Neue `remote_controlled_sensor.py` verwenden (2-Sekunden Recovery)

---

## 15. Python Dependencies

```bash
pip install paho-mqtt
```

---

## 16. Kontakt & Projekt

**Projekt:** BS GRID POC  
**Ordner:** `/Users/sissyhaegele/Projekte/GRIDGermany/`  
**Broker:** Solace Cloud (germangrid_berlin)

---

*Dokumentation aktualisiert am 14. Januar 2026*
