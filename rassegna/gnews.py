"""Google News come via di ripiego: elenca gli articoli di qualunque sito, anche se blocca
i nostri server o non ha un feed. I link di Google vengono tradotti negli indirizzi veri."""
import base64
import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from . import parsers, rete


def indirizzo_ricerca(dominio, giorni=3):
    q = urllib.parse.quote(f"site:{dominio} when:{giorni}d")
    return f"https://news.google.com/rss/search?q={q}&hl=it&gl=IT&ceid=IT:it"


def decodifica(url):
    """Indirizzo reale di un articolo dato il link di Google News (o il link stesso se non riesce)."""
    m = re.search(r"/articles/([^?/]+)", url)
    if not m:
        return url
    gid = m.group(1)
    try:  # vecchio formato: l'indirizzo è dentro l'identificativo
        grezzo = base64.urlsafe_b64decode(gid + "=" * (-len(gid) % 4))
        trovato = re.search(rb"https?://[^\x00-\x20\"\\]+", grezzo)
        if trovato:
            return trovato.group(0).decode()
    except Exception:  # noqa: BLE001
        pass
    try:
        pagina = rete.scarica_testo(f"https://news.google.com/rss/articles/{gid}?hl=it&gl=IT&ceid=IT:it", tentativi=2, timeout=15)
        sg = re.search(r'data-n-a-sg="([^"]+)"', pagina)
        ts = re.search(r'data-n-a-ts="([^"]+)"', pagina)
        if not (sg and ts):
            return url
        carico = ["Fbv4je", '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
                  f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{gid}",{ts.group(1)},"{sg.group(1)}"]']
        corpo = ("f.req=" + urllib.parse.quote(json.dumps([[carico]]))).encode()
        risposta = rete.scarica_testo("https://news.google.com/_/DotsSplashUi/data/batchexecute", data=corpo, tentativi=2, timeout=15,
                                      headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        dati = json.loads(risposta.split("\n\n")[1])[:-2]
        return json.loads(dati[0][2])[1]
    except Exception:  # noqa: BLE001
        return url


def articoli(dominio, nome_fonte="", giorni=3):
    voci = parsers.leggi_feed(rete.scarica(indirizzo_ricerca(dominio, giorni), tentativi=3))
    for v in voci:  # il titolo arriva come "Titolo - Nome del sito [- slogan]"
        if nome_fonte:
            v["title"] = re.sub(r"\s+[-–—|]\s+" + re.escape(nome_fonte) + r".*$", "", v["title"], flags=re.I)
        v["text"] = ""
    with ThreadPoolExecutor(4) as ex:
        for v, reale in zip(voci, ex.map(lambda x: decodifica(x["link"]), voci)):
            v["link"] = reale
    return [v for v in voci if dominio.split(".")[-2] in v["link"]] or voci
