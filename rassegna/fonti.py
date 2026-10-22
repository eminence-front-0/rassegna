"""Lettura delle fonti con vie di ripiego in cascata.

Per ogni fonte si prova, nell'ordine:
  1. il suo feed (con nuovi tentativi)         2. gli indirizzi alternativi indicati in sources.txt
  3. l'API di WordPress del sito               4. la lettura diretta delle pagine (se non c'è un feed)
  5. Google News, con i link tradotti in indirizzi reali
Il risultato dice quale via ha funzionato, così la pagina può avvisarti se una fonte è degradata.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from . import gnews, parsers, rete


@dataclass
class Fonte:
    nome: str
    url: str
    ruolo: str
    etichetta: str = ""
    solo: list = field(default_factory=list)
    alternative: list = field(default_factory=list)
    domini: list = field(default_factory=list)
    dominio: str = ""


@dataclass
class Esito:
    fonte: Fonte
    voci: list = field(default_factory=list)
    metodo: str = ""
    errori: list = field(default_factory=list)

    @property
    def ok(self):
        return bool(self.metodo)

    @property
    def degradato(self):
        return self.metodo in ("google-news", "pagina")


# ---------- vie di lettura ----------

def _youtube(url):
    if "youtube.com" not in url or "feeds/videos.xml" in url:
        return url
    m = re.search(r"/channel/(UC[\w-]{22})", url)
    if not m:
        pagina = rete.scarica_testo(url, tentativi=3)
        m = re.search(r'"channelId":"(UC[\w-]{22})"', pagina) or re.search(r"channel_id=(UC[\w-]{22})", pagina)
    if not m:
        raise ValueError("canale YouTube non riconosciuto")
    return "https://www.youtube.com/feeds/videos.xml?channel_id=" + m.group(1)


def _da_feed(url):
    dati = rete.scarica(_youtube(url), tentativi=7 if "youtube.com" in url else 4)
    if not parsers.e_feed(dati):
        return None, dati  # non è un feed: probabilmente una pagina
    voci = parsers.leggi_feed(dati, url)
    if "youtube.com" in url:
        for v in voci:
            m = re.search(r"v=([\w-]{11})", v["link"])
            if m:
                v["image"] = f"https://i.ytimg.com/vi/{m.group(1)}/mqdefault.jpg"
    return voci, dati


def _wp_json(url):
    u = urlparse(url)
    api = f"{u.scheme}://{u.netloc}/wp-json/wp/v2/posts?per_page=20&_embed=wp:featuredmedia"
    return parsers.leggi_wp_json(rete.scarica(api, tentativi=2))


def _leggi_articolo(item):
    url, titolo = item
    try:
        pagina = rete.scarica_testo(url, timeout=15, tentativi=2)
    except rete.ErroreRete:
        return None
    m = parsers.meta_articolo(pagina, url)
    return {"title": m["title"] or titolo, "link": url, "date": m["date"], "text": m["text"],
            "image": m["image"], "links": []}


def _da_pagine(url, dati, domini, visti=frozenset(), massimo=30):
    """Fonti senza feed: si legge l'elenco di articoli e poi ogni articolo per data, titolo e foto."""
    pagina = dati.decode("utf-8", "ignore") if isinstance(dati, bytes) else dati
    candidati = [c for c in parsers.link_candidati(pagina, url, domini) if c[0] not in visti][:massimo]
    with ThreadPoolExecutor(6) as ex:
        trovati = [x for x in ex.map(_leggi_articolo, candidati) if x]
    adesso = datetime.now(timezone.utc)
    for v in trovati:
        v["data_incerta"] = v["date"] is None
        v["date"] = v["date"] or adesso  # senza data dichiarata vale "visto oggi"
    return trovati


def _tutti(esito_voci):
    return esito_voci


def scarica_fonte(f: Fonte, visti=frozenset()):
    e = Esito(f)
    dom = f.dominio or parsers.dominio(f.url)
    pagina = None

    def prova(metodo, fn):
        try:
            voci = fn()
            if voci is not None:
                e.voci, e.metodo = voci, metodo
                return True
        except Exception as ex:  # noqa: BLE001  una via che fallisce non ferma la cascata
            e.errori.append(f"{metodo}: {str(ex)[:90]}")
        return False

    def via_feed():
        nonlocal pagina
        voci, dati = _da_feed(f.url)
        pagina = dati
        return voci

    if prova("feed", via_feed):
        return _finisci(e)
    for alt in f.alternative:
        if prova("alternativa", lambda alt=alt: _da_feed(alt)[0]):
            return _finisci(e)
    if pagina is not None and not parsers.e_feed(pagina):  # l'indirizzo era una pagina, non un feed
        if prova("pagina", lambda: _da_pagine(f.url, pagina, f.domini, visti)):
            return _finisci(e)
    if prova("wp-json", lambda: _wp_json(f.url)):
        return _finisci(e)
    if prova("google-news", lambda: gnews.articoli(dom, f.nome)):
        return _finisci(e)
    return e


def _finisci(e):
    f = e.fonte
    for v in e.voci:
        v.update(source=f.nome, role=f.ruolo, label=f.etichetta,
                 kind="video" if "youtube.com" in f.url else ("audio" if f.ruolo in ("podcast", "selezione") else "testo"))
        v.setdefault("data_incerta", False)
    if f.solo:
        e.voci = [v for v in e.voci if any(w in v["title"].lower() for w in f.solo)]
    return e


def scarica_tutte(fonti, visti=frozenset(), lavoratori=4):
    with ThreadPoolExecutor(lavoratori) as ex:
        return list(ex.map(lambda f: scarica_fonte(f, visti), fonti))
