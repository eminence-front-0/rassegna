"""Anteprime: per gli articoli senza foto nel feed si legge l'immagine di copertina dalla pagina."""
from concurrent.futures import ThreadPoolExecutor

from . import parsers, rete


def _og(voce):
    try:
        pagina = rete.scarica(voce["link"], timeout=10, tentativi=1)[:250000].decode("utf-8", "ignore")
    except rete.ErroreRete:
        return
    meta = parsers.meta_articolo(pagina, voce["link"])
    if meta["image"]:
        voce["image"] = meta["image"]
    if not voce.get("text") and meta["text"]:
        voce["text"] = meta["text"][:400]


def completa(voci):
    da_fare = [v for v in voci if not v.get("image") and v.get("kind") == "testo"]
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(_og, da_fare))
