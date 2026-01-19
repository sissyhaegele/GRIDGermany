# GRIDGermany - SAP BTP Deployment

**Plattform:** GRIDGermany - Echtzeit Netzüberwachung  
**Showcase:** Berliner Stadtwerke (BS) - Kritische Infrastruktur Monitoring

## Architektur

```
┌─────────────────────────────────────────────────────────────────┐
│                        SAP BTP                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    App Router                              │  │
│  │              (Authentication & Routing)                    │  │
│  └───────────────────────────────────────────────────────────┘  │
│              │                              │                    │
│              ▼                              ▼                    │
│  ┌─────────────────────┐      ┌─────────────────────────────┐   │
│  │     Dashboard       │      │      Fleet Control          │   │
│  │   (SMF/WebSocket)   │      │    (MQTT/WebSocket)         │   │
│  │   Scope: viewer     │      │    Scope: operator          │   │
│  └─────────────────────┘      └─────────────────────────────┘   │
│              │                              │                    │
│              └──────────────┬───────────────┘                    │
│                             ▼                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Advanced Event Mesh (Solace)                  │  │
│  │                   germangrid_berlin                        │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Voraussetzungen

- SAP BTP Trial oder Enterprise Account
- Cloud Foundry CLI (`cf`)
- MTA Build Tool (`mbt`)
- Node.js 18+

## Schnellstart

```bash
# 1. Solace Library herunterladen
./scripts/download-solclient.sh

# 2. MTA bauen
mbt build

# 3. Nach BTP deployen
cf login -a <api-endpoint>
cf deploy mta_archives/grid-germany_1.0.0.mtar
```

## Projektstruktur

```
grid-germany/
├── mta.yaml                    # Multi-Target Application Descriptor
├── xs-security.json            # XSUAA Authorization
├── app/
│   ├── dashboard/              # Echtzeit-Visualisierung (SMF)
│   │   ├── webapp/
│   │   │   ├── index.html
│   │   │   ├── solclient-full.js
│   │   │   └── manifest.json
│   │   ├── package.json
│   │   └── xs-app.json
│   └── fleet-control/          # Sensor-Steuerung (MQTT)
│       ├── webapp/
│       │   ├── index.html
│       │   └── manifest.json
│       ├── package.json
│       └── xs-app.json
├── approuter/                  # Central Application Router
│   ├── package.json
│   └── xs-app.json
└── scripts/
    └── download-solclient.sh
```

## BTP Services

| Service | Plan | Zweck |
|---------|------|-------|
| html5-apps-repo | app-host | HTML5 App Hosting |
| html5-apps-repo | app-runtime | Runtime für Apps |
| xsuaa | application | Authentication |
| destination | lite | AEM Connectivity |

## Rollen

| Rolle | Berechtigungen |
|-------|----------------|
| GRIDGermany_Viewer | Dashboard Zugriff |
| GRIDGermany_Operator | Fleet Control + Dashboard |
| GRIDGermany_Admin | Voller Zugriff |

## Solace AEM Konfiguration

```
Host:     mr-connection-gu0w0pjgchg.messaging.solace.cloud
VPN:      germangrid_berlin
SMF Port: 443 (Dashboard)
MQTT Port: 8443 (Fleet Control)
```

## Lokale Entwicklung

```bash
# HTTP Server für lokales Testen
cd app/dashboard/webapp && python3 -m http.server 8080
cd app/fleet-control/webapp && python3 -m http.server 8081
```

## Nächste Schritte

1. **SAP Integration Suite**: Event Flows für S/4HANA Integration
2. **SAP Business Data Cloud**: Event Persistence
3. **SAP Analytics Cloud**: Predictive Maintenance Dashboards
4. **SAP AI Core**: ML-basierte Anomalie-Erkennung

---

*Projekt: GRIDGermany - Berliner Stadtwerke Netzüberwachung*
