"""Chiamate a Gemini. L'AI è opzionale: se non risponde la pagina si compone comunque.

Per non dipendere da un solo modello (che può essere sovraccarico, o ritirato) si prova una catena:
i modelli «flash» stabili più recenti disponibili in quel momento, poi quelli leggeri, poi l'alias «latest».
Con un sovraccarico (503) o un limite di richieste (429) si aspetta di più prima di riprovare.
"""
import json
import os
import re
import time

from . import rete
from .config import RADICE

BASE = "https://generativelanguage.googleapis.com/v1beta"
CACHE = RADICE / ".cache"
PAUSE = (20, 45)          # secondi di attesa tra due tentativi sullo stesso modello
BUDGET = 480              # secondi massimi spesi per una domanda, poi si rinuncia
ultimo_modello = ""       # quale modello ha risposto (per mostrarlo in pagina)
_elenco = None


def disponibile():
    return bool(os.environ.get("GEMINI_API_KEY"))


def _intest():
    return {"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]}


def modelli():
    """Modelli da provare, in ordine. GEMINI_MODEL forza un modello in testa."""
    global _elenco
    if _elenco is None:
        scelti = []
        try:
            dati = json.loads(rete.scarica(f"{BASE}/models?pageSize=200", tentativi=1, ripiego=False, headers=_intest(), timeout=20))
            veri = []
            for m in dati.get("models", []):
                n = m["name"].removeprefix("models/")
                g = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash(-lite)?", n)  # solo versioni stabili: niente preview, image, tts, latest
                if g and "generateContent" in m.get("supportedGenerationMethods", []):
                    veri.append((float(g.group(1)), bool(g.group(2)), n))
            pieni = sorted((v for v in veri if not v[1]), reverse=True)
            leggeri = sorted((v for v in veri if v[1]), reverse=True)
            scelti = [n for _, _, n in pieni[:3]] + [n for _, _, n in leggeri[:1]]
        except Exception:  # noqa: BLE001  senza elenco si usa una lista di ripiego
            scelti = ["gemini-3.6-flash", "gemini-3.5-flash"]
        scelti.append("gemini-flash-latest")
        if os.environ.get("GEMINI_MODEL"):
            scelti.insert(0, os.environ["GEMINI_MODEL"])
        _elenco = list(dict.fromkeys(scelti))
    return _elenco


def _una(modello, corpo):
    """Una richiesta a un modello. Se rifiuta le impostazioni di ragionamento, ritenta senza."""
    for senza_ragionamento in (False, True):
        c = json.loads(json.dumps(corpo))
        if senza_ragionamento:
            c["generationConfig"].pop("thinkingConfig", None)
        try:
            return json.loads(rete.scarica(f"{BASE}/models/{modello}:generateContent", data=json.dumps(c).encode(), timeout=300,
                                           tentativi=1, ripiego=False, headers=_intest()))
        except rete.ErroreRete as e:
            if e.codice == 400 and not senza_ragionamento:
                continue
            raise


def chiedi(prompt, json_atteso=True, ricerca=False, nome="risposta"):
    """Ritorna la risposta di Gemini: un oggetto JSON (json_atteso) oppure testo.
    Con ricerca=True usa la ricerca di Google per trovare fonti reali."""
    global ultimo_modello
    cfg = {"maxOutputTokens": 32000, "temperature": 0.2, "thinkingConfig": {"thinkingBudget": 0}}
    corpo = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg}
    if ricerca:  # con gli strumenti il formato JSON non è ammesso: si estrae dal testo
        corpo["tools"] = [{"google_search": {}}]
    elif json_atteso:
        cfg["responseMimeType"] = "application/json"
    inizio, errori = time.time(), []
    for modello in modelli():
        for n in range(len(PAUSE) + 1):
            if time.time() - inizio > BUDGET:
                raise rete.ErroreRete("AI: tempo massimo esaurito. " + " | ".join(errori[-3:]))
            try:
                dati = _una(modello, corpo)
                testo = "".join(p.get("text", "") for p in dati["candidates"][0]["content"]["parts"])
                if not testo.strip():
                    raise rete.ErroreRete("risposta vuota")
                risultato = estrai_json(testo) if json_atteso else testo
                CACHE.mkdir(exist_ok=True)
                (CACHE / f"ultima_{nome}.json").write_text(testo, encoding="utf-8")  # per controllare cosa ha risposto
                ultimo_modello = modello
                return risultato
            except (rete.ErroreRete, ValueError, KeyError, IndexError) as e:
                codice = getattr(e, "codice", None)
                errori.append(f"{modello}: {str(e)[:110]}")
                if codice in (429, 500, 502, 503, 504) and n < len(PAUSE):
                    time.sleep(PAUSE[n] * (1.5 if codice == 429 else 1))  # sovraccarico o limite: si aspetta di più
                    continue
                break  # modello non disponibile o risposta inutilizzabile: si passa al successivo
    raise rete.ErroreRete("AI non raggiunta con nessun modello. " + " | ".join(errori[-4:]))


def estrai_json(testo):
    try:
        return json.loads(testo)
    except ValueError:
        m = re.search(r"```(?:json)?\s*(.*?)```", testo, re.S) or re.search(r"(\{.*\}|\[.*\])", testo, re.S)
        if not m:
            raise
        return json.loads(m.group(1))
