"""Chiamate a Gemini. L'AI è opzionale: se non risponde la pagina si compone comunque."""
import json
import os
import re
from pathlib import Path

from . import rete
from .config import RADICE

MODELLO = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
CACHE = RADICE / ".cache"


def disponibile():
    return bool(os.environ.get("GEMINI_API_KEY"))


def chiedi(prompt, json_atteso=True, ricerca=False, nome="risposta"):
    """Ritorna la risposta di Gemini: un oggetto JSON (json_atteso) oppure testo.
    Con ricerca=True usa la ricerca di Google per trovare fonti reali."""
    chiave = os.environ["GEMINI_API_KEY"]
    cfg = {"maxOutputTokens": 32000, "temperature": 0.2, "thinkingConfig": {"thinkingBudget": 0}}
    corpo = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg}
    if ricerca:  # con gli strumenti il formato JSON non è ammesso: si estrae dal testo
        corpo["tools"] = [{"google_search": {}}]
    elif json_atteso:
        cfg["responseMimeType"] = "application/json"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELLO}:generateContent"
    dati = json.loads(rete.scarica(url, data=json.dumps(corpo).encode(), timeout=300, tentativi=3,
                                   headers={"Content-Type": "application/json", "x-goog-api-key": chiave}))
    parti = dati["candidates"][0]["content"]["parts"]
    testo = "".join(p.get("text", "") for p in parti)
    CACHE.mkdir(exist_ok=True)
    (CACHE / f"ultima_{nome}.json").write_text(testo, encoding="utf-8")  # per controllare cosa ha risposto
    return estrai_json(testo) if json_atteso else testo


def estrai_json(testo):
    try:
        return json.loads(testo)
    except ValueError:
        m = re.search(r"```(?:json)?\s*(.*?)```", testo, re.S) or re.search(r"(\{.*\}|\[.*\])", testo, re.S)
        if not m:
            raise
        return json.loads(m.group(1))
