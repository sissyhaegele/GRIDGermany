# BS GRID – Demo Runbook

Kurzanleitung für die Live-Demo (Event-Driven Architecture). Jeder Block ist ein
eigenes Terminal-Tab im Repo-Root `GRIDGermany/`.

---

## 0 · Vorab-Check (einmalig, vor Publikum)

- [ ] **SAM (Solace Agent Mesh)** läuft, **GridIncidentAgent deployed** und mit dem
      LLM verbunden (Hyperspace AI / Anthropic). → Ohne LLM kommen Alarme an, aber
      **keine** `agentActionTaken`-Entscheidung. Das ist der häufigste Ausfall.
- [ ] **Broker** stimmt: `config.env` zeigt auf `mr-connection-89lyiztvo72…` (VPN `ger_dmi`).
- [ ] `python3 -c "import paho.mqtt.client"` läuft ohne Fehler (Client-Lib da).

---

## 1 · Starten (Reihenfolge egal, alle vor dem ersten Alarm)

**Tab A – Sensoren** (Netz „lebt", nur seltene Zufallsanomalien):
```bash
./scripts/start.sh          # Auswahl z.B. 4) 25 Sensoren
```

**Tab B – Backend-Dienste** (Scheduler + Notification Consumer, mit Broker-Check;
ein Ctrl+C stoppt beide):
```bash
./scripts/services.sh
```
> Startet `scheduling_service.py` (Terminplanung) **und** `notification_consumer.py`
> (E-Mails) zusammen. **Beide sind nötig**, sonst kommen weder Termine noch Mails.
> Fällt die Broker-Verbindung, bricht das Skript sofort mit klarer Meldung ab.

**Dashboards** – lokalen Webserver starten, dann im eigenen Chrome öffnen:
```bash
python3 -m http.server 8000
```
- Grid-Dashboard: <http://localhost:8000/dashboards/dashboard-fiori.html>
- Einsatzplanung ist von dort oben rechts verlinkt (🔧 Einsatzplanung →).

> Beide Dashboards verbinden sich automatisch und stellen den letzten Stand aus
> `localStorage` wieder her (kein leeres Bild beim Reload).

---

## 2 · Alarme – laufen automatisch

Die Alarme kommen **automatisch** über den in `bsgrid` integrierten Taktgeber:
**zufällige** Störfälle (Bezirk/Metrik/Typ) im festen Rhythmus — **1. nach ~15s,
dann alle ~10s**, endlos bis Ctrl+C. Kein zweites Terminal, kein Extra-Befehl.

> Die Sensoren selbst alarmieren NICHT (in der Demo mit `SENSOR_ANOMALY_CHANCE=0`
> gestartet) — sie liefern nur den Telemetrie-Hintergrund. So bleibt der Takt sauber.

Falls du mal manuell nachhelfen willst (zweites Terminal):
```bash
DEMO_MAX_ALARMS=1 python3 demo_scenario.py     # ein einzelner Alarm
```

Steuer-Variablen (der Taktgeber in `start.sh` nutzt 15s / 10s):
`DEMO_FIRST_DELAY` (s bis 1. Alarm), `DEMO_GAP` (s dazwischen),
`DEMO_MAX_ALARMS` (0 = Dauerbetrieb, >0 = so viele dann Stopp),
`DEMO_RANDOM` (0 = feste Szenarien), `DEMO_LEADIN` (1 = fester Einstieg monitor→dispatch).

Taktgeber ganz abschalten: `BSGRID_NO_ALARMS=1 bsgrid`

---

## 3 · Der „rote Faden" (was wo sichtbar wird)

| Schritt | Event | Sichtbar in |
|---|---|---|
| Sensor meldet Anomalie | `alarmRaised` | Grid-Dashboard, Event-Log |
| Agent (LLM) entscheidet | `agentActionTaken` | Grid-Dashboard: Agent-Karte |
| → `escalate` | — | E-Mail an Leitwarte (`outbox/`) |
| → `dispatch_technician` | `technicianScheduled` | **Einsatzplanung-Dashboard** (Slot + Ampel) **und** E-Mail „eingeplant" (`outbox/`) |

Erzähl-Kern: **deterministisch** (Scheduler/Workflow, feste Regeln) trifft
**nicht-deterministisch** (Agent/LLM entscheidet), lose gekoppelt über den Broker.

Mails live zeigen:
```bash
ls -t outbox/ | head        # neueste zuerst
open outbox/<datei>.eml     # öffnet im Mail-Client
```

---

## 4 · Stoppen & Reset (nach der Demo / zwischen Durchläufen)

- Sensoren: **Ctrl+C** in Tab A (stoppt alle sauber).
- Backend-Dienste (Scheduler + Consumer): **Ctrl+C** in Tab B (stoppt beide).
- Webserver: **Ctrl+C** im jeweiligen Tab.
- `outbox/` leeren: `rm -f outbox/*.eml`
- Dashboards zurücksetzen (leerer Startzustand): im Browser DevTools-Konsole
  `localStorage.clear()` — oder einfach neue Test-Termine kommen lassen.

---

## 5 · Schnelldiagnose

| Symptom | Ursache | Fix |
|---|---|---|
| Alarme im Log, aber **keine** Agent-Karte | LLM/Guthaben | Hyperspace/Anthropic prüfen, Agent in SAM re-deployen |
| Keine E-Mail / kein Termin bei `dispatch_technician` | Backend-Dienste aus | `./scripts/services.sh` in Tab B läuft? |
| Termin, aber Dashboard leer | Falscher Broker / nicht verbunden | Status-Badge im Dashboard, `config.env` prüfen |
| Gar keine Anomalie | Taktgeber aus / abgestürzt | Läuft `demo_scenario.py`? Log: `/tmp/bsgrid_demo.log`. Sonst `bsgrid` neu. |
