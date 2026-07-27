"""
GRIDGermany - zentrale Broker-Konfiguration (Python-Seite).

Beim Import werden die Werte aus `config.env` (im Projekt-Root) in os.environ
geladen — EINE Stelle für Host, VPN, Username, Passwort. config.env ist die
maßgebliche Quelle und ÜBERSCHREIBT auch bereits gesetzte Shell-Variablen
(verhindert, dass ein altes `export SOLACE_HOST=…` aus der Shell die Skripte
still auf den falschen/alten Broker zeigen lässt).

Verwendung: als ERSTE Zeile eines Skripts `import bs_env`, danach ganz normal
`os.getenv('SOLACE_HOST')` usw.

Broker-Umzug = nur `config.env` anpassen. Vorlage: `config.env.example`.
"""

import os

_ROOT = os.path.dirname(os.path.abspath(__file__))


def _load(path):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[len('export '):]
            if '=' not in line:
                continue
            key, val = line.split('=', 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            os.environ[key] = val   # config.env ist maßgeblich (überschreibt Shell)


_cfg = os.path.join(_ROOT, 'config.env')
if os.path.isfile(_cfg):
    _load(_cfg)
elif not os.getenv('SOLACE_HOST'):
    print("⚠️  Keine config.env gefunden und SOLACE_HOST nicht gesetzt.\n"
          "    Kopiere config.env.example → config.env und trage die Broker-Werte ein.")
