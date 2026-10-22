"""Lettura di sources.txt e interessi.txt."""
import re
from pathlib import Path

from . import parsers
from .fonti import Fonte

RADICE = Path(__file__).resolve().parent.parent


def leggi_fonti(percorso=None):
    """Ritorna (fonti, argomenti). Una fonte è «Nome = indirizzo | opzione: valore | ...»."""
    percorso = percorso or RADICE / "sources.txt"
    fonti, argomenti, ruolo, etichetta = [], [], None, ""
    for riga in Path(percorso).read_text(encoding="utf-8").splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#"):
            continue
        m = re.fullmatch(r"\[([^\]:]+)(?::\s*([^\]]*))?\]", riga)
        if m:
            ruolo, etichetta = m.group(1).strip().lower(), (m.group(2) or "").strip()
            continue
        if ruolo == "argomenti":
            argomenti.append(riga)
        elif ruolo in ("notizie", "scritti", "podcast", "selezione", "canali") and "=" in riga:
            nome, resto = (p.strip() for p in riga.split("=", 1))
            url, *opzioni = (p.strip() for p in resto.split("|"))
            f = Fonte(nome=nome, url=url, ruolo=ruolo, etichetta=etichetta, dominio=parsers.dominio(url))
            for o in opzioni:
                chiave, _, valore = o.partition(":")
                lista = [v.strip() for v in valore.split(",") if v.strip()]
                chiave = chiave.strip().lower()
                if chiave == "solo":
                    f.solo = [v.lower() for v in lista]
                elif chiave in ("alternativa", "alternative"):
                    f.alternative = lista
                elif chiave == "domini":
                    f.domini = lista
                elif chiave == "sito":
                    f.dominio = parsers.dominio(valore.strip())
            fonti.append(f)
    return fonti, argomenti or ["Altro"]


def leggi_interessi(percorso=None):
    percorso = Path(percorso or RADICE / "interessi.txt")
    return percorso.read_text(encoding="utf-8").strip() if percorso.exists() else ""
