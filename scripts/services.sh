#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# BS GRID - Backend-Dienste (Scheduler + Notification Consumer)
# Startet die beiden Consumer, die für Terminplanung und E-Mails
# nötig sind. Bewusst getrennt von den Sensoren (die startest du
# über scripts/start.sh und wählst dort die Anzahl).
#
#   Terminal 1:  ./scripts/start.sh       (Sensoren)
#   Terminal 2:  ./scripts/services.sh    (dieses Skript)
#   Ein Ctrl+C hier stoppt beide Dienste sauber.
# ═══════════════════════════════════════════════════════════════

cd "$(dirname "$0")/.." || exit 1

PIDS=()
cleanup() {
    echo ""
    echo "🛑 Stoppe Backend-Dienste …"
    for pid in "${PIDS[@]}"; do kill -SIGTERM "$pid" 2>/dev/null; done
    sleep 1
    for pid in "${PIDS[@]}"; do kill -SIGKILL "$pid" 2>/dev/null; done
    echo "✅ Scheduler + Consumer gestoppt."
    exit 0
}
trap cleanup SIGINT SIGTERM

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ⚡ BS GRID - Backend-Dienste                                ║"
echo "║  Scheduler (Terminplanung) + Notification Consumer (E-Mails) ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Verbindungs-Check gegen den Broker (schneller Fehler statt stiller Demo)
echo "🔌 Prüfe Broker-Verbindung …"
if ! python3 - <<'PY'
import bs_env, os, ssl, sys, time
import paho.mqtt.client as mqtt
host=os.getenv('SOLACE_HOST'); port=int(os.getenv('SOLACE_PORT',8883))
u=os.getenv('SOLACE_USERNAME'); p=os.getenv('SOLACE_PASSWORD')
ok={'v':False}
def oc(c,ud,f,rc,*a):
    ok['v'] = (rc if isinstance(rc,int) else getattr(rc,'value',1)) == 0
    c.disconnect()
try: cl=mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
except: cl=mqtt.Client()
cl.username_pw_set(u,p); cl.tls_set(cert_reqs=ssl.CERT_NONE); cl.tls_insecure_set(True)
cl.on_connect=oc
try:
    cl.connect(host,port,10); cl.loop_start(); time.sleep(4); cl.loop_stop()
except Exception as e:
    print(f"   Fehler: {e}"); sys.exit(1)
print(f"   Broker: {host}:{port}  VPN: {os.getenv('SOLACE_VPN_NAME','?')}")
sys.exit(0 if ok['v'] else 1)
PY
then
    echo "❌ Keine Broker-Verbindung. config.env prüfen (Host/VPN/Passwort). Abbruch."
    exit 1
fi
echo "✅ Broker erreichbar."
echo ""

# Scheduler starten (unbuffered → Logs sofort sichtbar)
echo "🗓️  Starte Scheduler (scheduling_service.py) …"
python3 -u scheduling_service.py &
PIDS+=($!)

# Notification Consumer starten
echo "📧 Starte Notification Consumer (notification_consumer.py) …"
python3 -u notification_consumer.py &
PIDS+=($!)

echo ""
echo "✅ Beide Dienste laufen. Ctrl+C zum Beenden."
echo "   Termine → Scheduling-Dashboard · E-Mails → ./outbox/"
echo "───────────────────────────────────────────────────────────────"
echo ""

wait
