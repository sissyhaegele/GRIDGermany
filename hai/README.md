# HAI — Hyperspace AI (generischer LLM-Zugang)

Generischer, use-case-unabhängiger Zugang zu den SAP-LLMs über den **lokalen
HAI-Proxy**. Der Proxy ist OpenAI-kompatibel — damit spricht man Anthropic-,
OpenAI- und Google-Modelle über die Standard-OpenAI-API an.

```
Deine App  →  HAI-Proxy (localhost:6655)  →  SAP AI Core  →  Anthropic / OpenAI / Google
   OpenAI-Format         Bearer: HAI_API_KEY
```

Kein Kyma, kein eigener LiteLLM-Proxy, keine AI-Core-Instanz nötig — der lokale
HAI-Proxy liefert den fertigen Endpoint. (Der `litellm-proxy/`-Ordner ist der
alternative Kyma-Weg für den Fall, dass kein lokaler HAI-Proxy verfügbar ist.)

## Setup

```bash
pip install openai python-dotenv
cp hai/.env.example hai/.env      # HAI_API_KEY eintragen
```

Voraussetzung: Der **lokale HAI-Proxy läuft** auf `localhost:6655`.

## Nutzung

```python
from hai.hai_client import chat, client, list_models

chat("Sag Hallo.")                                   # Default-Modell (.env)
chat("Explain X", model="gpt-5.5")                   # anderes Modell
chat("Analysiere ...", system="Du bist ...")         # mit System-Prompt
list_models()                                        # verfügbare Modelle

# Roher OpenAI-Client für alles Weitere (streaming, tools, ...):
client().chat.completions.create(model="...", messages=[...])
```

CLI-Schnelltest:

```bash
python hai/hai_client.py                             # Modelle auflisten
python hai/hai_client.py "Welches Modell bist du?"   # Chat
```

## Verfügbare Modelle (Stand: getestet)

- **Anthropic:** `anthropic--claude-4.8-opus`, `-4.7-opus`, `-4.6-sonnet`,
  `-4.5-sonnet`, `-4.5-haiku`, `-4.5-opus`, `-4-sonnet`
- **OpenAI:** `gpt-5.5`, `gpt-5`, `gpt-5-mini`, `gpt-4.1`, `gpt-4.1-mini`
- **Google:** `gemini-3.5-flash`, `gemini-3.1-flash-lite`, `gemini-2.5-pro`,
  `gemini-2.5-flash`
- **Embeddings:** `text-embedding-3-large/-small`, `gemini-embedding`
- **Perplexity:** `sonar`, `sonar-pro`

Aktuelle Liste jederzeit: `python hai/hai_client.py`.

## Sicherheit

- `hai/.env` mit dem Key ist in `.gitignore` — **nie einchecken**.
- Der Key wurde initial im Klartext geteilt; **im HAI-Portal rotieren**, sobald
  praktikabel, und den neuen Wert nur in `hai/.env` eintragen.
