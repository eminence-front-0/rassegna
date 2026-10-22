"""Memoria tra un'esecuzione e l'altra (data/stato.json): articoli già visti, salute delle fonti,
fonti consigliate e preferenze. Garantisce che nessuna uscita manchi e nessuna sia ripetuta."""
import json
from datetime import datetime, timedelta
from pathlib import Path

from .config import RADICE

PERCORSO = RADICE / "data" / "stato.json"
VUOTO = {"ultima_esecuzione": None, "visti": {}, "salute": {}, "suggerimenti": {}, "feedback": [], "scartati": []}


def carica():
    try:
        s = json.loads(PERCORSO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        s = {}
    return {**json.loads(json.dumps(VUOTO)), **s}


def salva(stato, oggi):
    limite = (datetime.fromisoformat(oggi) - timedelta(days=21)).date().isoformat()
    stato["visti"] = {k: v for k, v in stato["visti"].items() if v >= limite}
    stato["feedback"] = stato["feedback"][-400:]
    PERCORSO.parent.mkdir(exist_ok=True)
    PERCORSO.write_text(json.dumps(stato, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def aggiorna_salute(stato, esiti, conteggi, adesso):
    """Registra per ogni fonte se ha risposto, con quale via e quanti giorni è senza uscite."""
    for e in esiti:
        s = stato["salute"].setdefault(e.fonte.nome, {"fallimenti": 0, "ultimo_ok": None, "ultimo_articolo": None})
        if e.ok:
            s.update(ultimo_ok=adesso.isoformat(), fallimenti=0, metodo=e.metodo, errore="")
            if e.voci:
                s["ultimo_articolo"] = max(v["date"] for v in e.voci).isoformat()
        else:
            s.update(fallimenti=s["fallimenti"] + 1, metodo="", errore="; ".join(e.errori)[:200])
        s["oggi"] = conteggi.get(e.fonte.nome, 0)
    return stato["salute"]
