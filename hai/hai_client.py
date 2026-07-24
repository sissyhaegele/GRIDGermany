#!/usr/bin/env python3
"""
HAI (Hyperspace AI) — generischer LLM-Zugang über den lokalen SAP-Proxy.

Der HAI-Proxy (default: http://localhost:6655/litellm/v1) ist OpenAI-kompatibel.
Damit spricht man alle SAP-AI-Core-Modelle (Anthropic / OpenAI / Google) über die
Standard-OpenAI-API an — use-case-unabhängig in beliebigen Projekten wiederverwendbar.

Setup:
    pip install openai python-dotenv
    cp hai/.env.example hai/.env   # und HAI_API_KEY eintragen

Nutzung als Modul:
    from hai.hai_client import chat, client
    print(chat("Sag Hallo."))                          # Default-Modell aus .env
    print(chat("Explain X", model="gpt-5.5"))          # anderes Modell
    resp = client().chat.completions.create(...)       # roher OpenAI-Client

CLI-Schnelltest:
    python hai/hai_client.py                           # Modelle auflisten
    python hai/hai_client.py "Welches Modell bist du?" # Chat
"""

import os
import sys
from functools import lru_cache
from typing import List, Optional

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from openai import OpenAI

_HERE = os.path.dirname(os.path.abspath(__file__))

# hai/.env laden (echte Shell-Variablen haben Vorrang).
if load_dotenv:
    load_dotenv(os.path.join(_HERE, ".env"), override=False)

BASE_URL = os.getenv("HAI_BASE_URL", "http://localhost:6655/litellm/v1")
API_KEY = os.getenv("HAI_API_KEY", "")
DEFAULT_MODEL = os.getenv("HAI_MODEL", "anthropic--claude-4.6-sonnet")


@lru_cache(maxsize=1)
def client() -> OpenAI:
    """OpenAI-Client, der gegen den HAI-Proxy zeigt (gecacht)."""
    if not API_KEY:
        raise RuntimeError(
            "HAI_API_KEY fehlt. Kopiere hai/.env.example -> hai/.env und trage den Key ein."
        )
    return OpenAI(base_url=BASE_URL, api_key=API_KEY)


def chat(prompt, model=None, system=None, **kwargs):
    """Ein-Prompt-Chat, gibt den Antworttext zurück.

    prompt : User-Nachricht
    model  : Modell-ID (default: HAI_MODEL aus .env)
    system : optionaler System-Prompt
    kwargs : werden an chat.completions.create durchgereicht (temperature, max_tokens, ...)
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = client().chat.completions.create(
        model=model or DEFAULT_MODEL,
        messages=messages,
        **kwargs,
    )
    return resp.choices[0].message.content


def list_models():
    """IDs aller vom Proxy angebotenen Modelle."""
    return [m.id for m in client().models.list().data]


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(chat(" ".join(sys.argv[1:])))
    else:
        print(f"HAI-Proxy: {BASE_URL}")
        print(f"Default-Modell: {DEFAULT_MODEL}\n")
        print("Verfügbare Modelle:")
        for mid in list_models():
            marker = "  * " if mid == DEFAULT_MODEL else "    "
            print(f"{marker}{mid}")
