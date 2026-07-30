#!/usr/bin/env python3
"""
main.py — Einstiegspunkt des Grid Incident Agent (Joule Studio, Pro-Code).

Startet BEIM APP-START:
  1. den SMF-Subscriber (grid_subscriber.start_subscriber) als Daemon-Thread —
     er zieht alarmRaised aus dem SAP Advanced Event Mesh und publiziert die
     Entscheidung als agentActionTaken zurück,
  2. den A2A/HTTP-Server, über den der Subscriber den Agent lokal aufruft und
     der den Health-Endpoint bereitstellt.

WICHTIG (Transport): Es gibt KEINEN eingehenden Webhook/RDP für Alarme. Der Agent
verbindet sich AUSGEHEND zum Broker. Der HTTP-Server hier dient nur (a) dem
lokalen A2A-Aufruf durch den Subscriber (localhost) und (b) dem Health-Check.

Der eigentliche A2A-Agent-Handler (der die Instructions ausführt und die
Entscheidung bildet) wird vom Joule-Studio-Framework bereitgestellt/gemountet.
Hier ist ein minimaler Platzhalter-Handler, falls das Framework keinen liefert —
in der echten Joule-App wird dieser durch den generierten Agent-Endpoint ersetzt.
"""

import os
from flask import Flask, request, jsonify

from grid_subscriber import start_subscriber, get_status

app = Flask(__name__)
A2A_PORT = int(os.getenv("A2A_PORT", "8080"))


@app.route("/health/subscriber", methods=["GET"])
def subscriber_health():
    """Verifikation der SMF-Verbindung OHNE Zugriff auf Runtime-Logs.
    Liefert import_ok, connected, empfangene Alarme, publizierte Entscheidungen,
    letzten Fehler und Plattform-Diagnostik (Python/OS/libc)."""
    return jsonify(get_status())


# ---------------------------------------------------------------------------
# Platzhalter-A2A-Endpoint. In der echten Joule-App ersetzt der vom Framework
# generierte Agent diesen Handler. Er ist NUR aktiv, wenn kein Framework-Handler
# gemountet ist, damit der Subscriber lokal immer ein Ziel hat.
# ---------------------------------------------------------------------------
@app.route("/", methods=["POST"])
def a2a_placeholder():
    rpc = request.get_json(force=True, silent=True) or {}
    # Den Alarm-Text aus der A2A-Message ziehen (nur für den Platzhalter).
    return jsonify({
        "jsonrpc": "2.0",
        "id": rpc.get("id"),
        "result": {
            "message": {
                "role": "agent",
                "parts": [{
                    "kind": "text",
                    "text": "{\"decision\":\"monitor\",\"reasoning\":\"Platzhalter-Handler "
                            "aktiv — der echte Joule-Agent ist nicht gemountet.\","
                            "\"confidence\":0.1,\"parameters\":{}}"
                }]
            }
        }
    })


if __name__ == "__main__":
    # Subscriber VOR / parallel zum HTTP-Server starten (Daemon-Thread).
    start_subscriber()
    app.run(host="0.0.0.0", port=A2A_PORT)
