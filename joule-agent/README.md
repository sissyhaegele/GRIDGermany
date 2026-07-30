# Grid Incident Agent — Pro-Code für Joule Studio

Diese Dateien gehören in das **Joule-Agent-Projekt** (nicht in die Demo-Laufzeit).
Der Agent stellt den Transport von **Webhook/RDP auf einen ausgehenden
SMF-Consumer** um: er zieht `alarmRaised` selbst aus dem SAP Advanced Event Mesh
und publiziert `agentActionTaken` über dieselbe Verbindung zurück.

## Dateien

| Datei | Zweck |
|-------|-------|
| `grid_subscriber.py` | SMF-Subscriber (Daemon-Thread): abonniert `alarmRaised`, ruft den Agent lokal (A2A) auf, publiziert die Entscheidung über dieselbe SMF-Verbindung. |
| `main.py` | App-Start: startet den Subscriber + A2A/HTTP-Server + `GET /health/subscriber`. |
| `asset.yaml` | Environment (Broker, Topics, A2A). `SOLACE_PASSWORD` als Secret. |
| `requirements.txt` | `solace-pubsubplus`, `Flask`. |

## Architektur (Transport = ausgehend)

```
  SAP Advanced Event Mesh (ger_dmi)
        │  ▲
 SMF/TLS │  │ SMF/TLS  (beide AUSGEHEND vom Agent initiiert)
 55443   │  │ 55443
        ▼  │
  ┌───────────────────────────────┐
  │  Joule Agent Container         │
  │  grid_subscriber (Thread)      │
  │    alarmRaised ──▶ invoke_agent│──localhost──▶  A2A-Agent (Instructions)
  │    agentActionTaken ◀──────────│◀─ Entscheidung
  └───────────────────────────────┘
```

Kein eingehender Webhook, kein RDP, kein OAuth — nur Messaging-Credentials.

## Verifikation (ohne Runtime-Logs)

Nach dem Deployment:

```
GET /health/subscriber
```
liefert `import_ok`, `connected`, `alarms_received`, `decisions_published`,
`last_error` und Plattform-Diagnostik. So prüfst du die zwei kritischen Punkte:

1. **`import_ok: false`** → `solace-pubsubplus` konnte nicht geladen werden
   (musl/Alpine statt glibc). Basis-Image auf Debian/Ubuntu stellen.
2. **`connected: false`** mit `last_error` zu Timeout/Refused → **Egress** zu
   `…:55443` ist blockiert. In der Runtime den Host/Port freigeben.

`connected: true` + steigende `alarms_received` = die Kette läuft.

## Anpassen an den generierten Joule-Agent

`main.py` enthält einen **Platzhalter-A2A-Handler**. In der echten Joule-App
ersetzt der vom Framework generierte Agent-Endpoint diesen Handler — dann führt
der Agent die Instructions aus `docs/JOULE_AGENT_INSTRUCTIONS.md` aus und liefert
das `agentActionTaken`-JSON zurück. `grid_subscriber._extract_decision()` schält
das JSON robust aus der A2A-Antwort (auch aus ```json-Fences).
