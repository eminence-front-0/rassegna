"""Ricerca di fonti nuove: vere (verificate), attive e coerenti con i tuoi interessi.

Come funziona, una volta a settimana:
  1. raccoglie i siti che le tue fonti citano più spesso nei loro articoli;
  2. chiede a Gemini (con la ricerca di Google) altre testate e newsletter affini ai tuoi interessi;
  3. VERIFICA ogni candidato: deve avere un feed funzionante e uscite recenti (niente fonti inventate o morte);
  4. l'AI sceglie le migliori e spiega perché, mostrando le ultime uscite come anteprima.
"""
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from . import ia, parsers, rete
from .composizione import json

ESCLUSI = {
    "twitter.com", "x.com", "facebook.com", "instagram.com", "youtube.com", "youtu.be", "linkedin.com", "tiktok.com", "t.me",
    "wikipedia.org", "it.wikipedia.org", "en.wikipedia.org", "google.com", "apple.com", "podcasts.apple.com", "amazon.com", "amazon.it",
    "doi.org", "archive.org", "bit.ly", "github.com", "reddit.com", "pinterest.com", "spotify.com", "open.spotify.com", "whatsapp.com",
    "paypal.com", "ko-fi.com", "patreon.com", "europa.eu", "ec.europa.eu", "wordpress.com", "medium.com", "mailchi.mp", "eepurl.com",
    "us10.campaign-archive.com", "goo.gl", "t.co", "ow.ly", "fb.me", "vimeo.com", "bsky.app", "threads.net", "mastodon.social", "dropbox.com",
}


GENERALISTI = {  # grandi quotidiani e agenzie: li leggi già tramite le tue testate di notizie; qui cerchiamo voci tematiche
    "repubblica.it", "corriere.it", "lastampa.it", "ilsole24ore.com", "ilfattoquotidiano.it", "ilgiornale.it", "liberoquotidiano.it", "ilmessaggero.it",
    "ansa.it", "rainews.it", "tgcom24.mediaset.it", "fanpage.it", "open.online", "ilpost.it", "internazionale.it", "huffingtonpost.it",
    "theguardian.com", "nytimes.com", "washingtonpost.com", "bbc.com", "bbc.co.uk", "cnn.com", "reuters.com", "lemonde.fr", "elpais.com",
    "lefigaro.fr", "spiegel.de", "bloomberg.com", "ft.com", "wsj.com", "apnews.com", "politico.eu", "politico.com", "euronews.com", "dw.com",
}


def e_escluso(host):
    return host in ESCLUSI or host in GENERALISTI or host.endswith((".gov", ".gov.it", ".edu", ".ac.uk", ".europa.eu", ".istruzione.it")) or any(host.endswith("." + e) for e in ESCLUSI)


def da_aggiornare(stato, giorni=7):
    g = (stato.get("suggerimenti") or {}).get("generato")
    if not g:
        return True
    return datetime.now(timezone.utc) - datetime.fromisoformat(g) > timedelta(days=giorni)


def domini_citati(voci, domini_noti):
    conteggio = Counter()
    for v in voci:
        for h in {urlparse(x).netloc.lower().removeprefix("www.") for x in v.get("links", [])}:
            if h and h not in domini_noti and not e_escluso(h):
                conteggio[h] += 1
    return conteggio


def trova_feed_sito(url):
    """Cerca e verifica un feed per un sito. Ritorna None se non c'è o se non pubblica da tempo."""
    base = url if url.startswith("http") else "https://" + url
    u = urlparse(base)
    origine = f"{u.scheme}://{u.netloc}"
    candidati = []
    try:
        candidati += parsers.trova_feed(rete.scarica_testo(origine + "/", timeout=12, tentativi=2), origine + "/")
    except rete.ErroreRete:
        pass
    if "substack.com" in u.netloc:
        candidati.insert(0, origine + "/feed")
    candidati += [origine + p for p in ("/feed", "/rss", "/feed.xml", "/rss.xml", "/index.xml", "/atom.xml")]
    limite = datetime.now(timezone.utc) - timedelta(days=45)
    for f in list(dict.fromkeys(candidati))[:8]:
        try:
            dati = rete.scarica(f, timeout=12, tentativi=1)
            if not parsers.e_feed(dati):
                continue
            voci = parsers.leggi_feed(dati, f)
        except Exception:  # noqa: BLE001
            continue
        if len(voci) >= 3 and max(v["date"] for v in voci) >= limite:
            m = re.search(r"<channel>.*?<title>(.*?)</title>", dati.decode("utf-8", "ignore"), re.S) or re.search(r"<feed[^>]*>.*?<title[^>]*>(.*?)</title>", dati.decode("utf-8", "ignore"), re.S)
            nome = parsers.pulisci_html(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))) if m else parsers.dominio(url)
            voci.sort(key=lambda v: v["date"], reverse=True)
            return {"nome": nome[:60] or parsers.dominio(url), "url": origine + "/", "feed": f, "dominio": u.netloc.lower().removeprefix("www."),
                    "esempi": [{"titolo": v["title"], "link": v["link"]} for v in voci[:3]], "ultima": voci[0]["date"].isoformat()}
    return None


def proponi_con_ai(interessi, nomi_fonti, scartati):
    """Chiede a Gemini siti da valutare. Prima con la ricerca di Google (fonti reali e aggiornate);
    se il piano gratuito non la concede, dalla sua conoscenza: tanto ogni candidato viene poi verificato."""
    base = (
        "Proponi 16 fonti di informazione scritte (riviste online indipendenti, newsletter, Substack, think tank, blog autorevoli) "
        "in italiano o inglese, ATTIVE e con un feed RSS, adatte a questo lettore.\n"
        f"INTERESSI DEL LETTORE:\n{interessi or '(non indicati)'}\n\n"
        f"FONTI CHE GIÀ SEGUE (non riproporle): {', '.join(nomi_fonti)}\n"
        f"FONTI SCARTATE (non riproporle): {', '.join(scartati) or 'nessuna'}\n\n"
        "Privilegia fonti TEMATICHE e indipendenti. Escludi: grandi quotidiani generalisti, agenzie di stampa, testate locali, "
        "siti di case editrici o aziende, social, video, podcast. Almeno metà in italiano. "
        'Rispondi SOLO con un array JSON: [{"nome":"...","url":"https://pagina-principale-del-sito","perche":"una frase"}]'
    )
    for ricerca in (True, False):
        try:
            prompt = ("Usa la ricerca di Google per trovare fonti reali. " if ricerca else "Usa la tua conoscenza: ogni indirizzo verrà verificato. ") + base
            r = ia.chiedi(prompt, json_atteso=True, ricerca=ricerca, nome="ricerca_fonti")
            trovate = [x for x in r if isinstance(x, dict) and str(x.get("url", "")).startswith("http")]
            if trovate:
                return trovate
        except Exception:  # noqa: BLE001  quota esaurita o risposta non valida: si passa alla via successiva
            continue
    return []


def scegli_con_ai(verificate, interessi, argomenti):
    prompt = (
        "Sei il curatore di una rassegna stampa personale. Dai candidati VERIFICATI (feed attivo) scegli le 6 fonti più utili "
        "per questo lettore, evitando doppioni di tema e preferendo voci tematiche e indipendenti a quotidiani generalisti o testate locali. Rispondi SOLO con JSON: "
        '[{"dominio":"...","tema":"uno tra gli argomenti","perche":"1-2 frasi in italiano: cosa offre e perché si lega ai suoi interessi, '
        'citando uno dei titoli recenti se utile"}]\n\n'
        f"ARGOMENTI: {json.dumps(argomenti, ensure_ascii=False)}\nINTERESSI:\n{interessi or '(non indicati)'}\n\n"
        "CANDIDATI:\n" + json.dumps([{"dominio": v["dominio"], "nome": v["nome"], "citata_dalle_tue_fonti": v.get("citata", 0),
                                      "ultimi_titoli": [e["titolo"] for e in v["esempi"]]} for v in verificate], ensure_ascii=False)
    )
    return ia.chiedi(prompt, nome="scelta_fonti")


def genera(voci, fonti, interessi, argomenti, scartati, massimo=6):
    noti = {f.dominio for f in fonti} | {parsers.dominio(f.url) for f in fonti}
    candidati = {}
    for h, n in domini_citati(voci, noti).most_common(14):
        candidati[h] = {"url": "https://" + h, "citata": n}
    if ia.disponibile():
        for x in proponi_con_ai(interessi, [f.nome for f in fonti], scartati):
            h = parsers.dominio(x["url"])
            if h and h not in noti and not e_escluso(h) and h not in scartati:
                candidati.setdefault(h, {"url": x["url"], "citata": 0})["perche_ai"] = x.get("perche", "")
    candidati = {h: c for h, c in candidati.items() if h not in scartati}
    with ThreadPoolExecutor(6) as ex:
        trovate = list(ex.map(lambda kv: trova_feed_sito(kv[1]["url"]), candidati.items()))
    verificate = []
    for (h, c), t in zip(candidati.items(), trovate):
        if t and t["dominio"] not in noti:
            t["citata"] = c["citata"]
            t["perche"] = c.get("perche_ai", "")
            verificate.append(t)
    verificate.sort(key=lambda t: -t["citata"])
    verificate = verificate[:20]
    scelte = []
    if verificate and ia.disponibile():
        try:
            for r in scegli_con_ai(verificate, interessi, argomenti)[:massimo]:
                v = next((x for x in verificate if x["dominio"] == r.get("dominio")), None)
                if v:
                    scelte.append({**v, "tema": str(r.get("tema", "")), "perche": str(r.get("perche", v["perche"]))})
        except Exception:  # noqa: BLE001
            scelte = []
    if not scelte:
        scelte = [{**v, "tema": "", "perche": v["perche"] or f"Citata {v['citata']} volte dalle tue fonti." if v["citata"] else "Fonte attiva affine alle tue."} for v in verificate[:massimo]]
    return {"generato": datetime.now(timezone.utc).isoformat(), "elenco": scelte}
