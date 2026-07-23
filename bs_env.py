"""
GRIDGermany - zentrale Broker-Konfiguration (Python-Seite).

Beim Import werden die Werte aus `config.env` (im Projekt-Root) in os.environ
geladen — EINE Stelle für Host, VPN, Username, Passwort. Ein bereits gesetztes
Environment (echte Shell-Variablen) hat Vorrang und wird nicht überschrieben.

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
            os.environ.setdefault(key, val)   # Shell-Environment gewinnt


_cfg = os.path.join(_ROOT, 'config.env')
if os.path.isfile(_cfg):
    _load(_cfg)
elif not os.getenv('SOLACE_HOST'):
    print("⚠️  Keine config.env gefunden und SOLACE_HOST nicht gesetzt.\n"
          "    Kopiere config.env.example → config.env und trage die Broker-Werte ein.")
