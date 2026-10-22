"""Lettura dei formati che incontriamo: feed RSS/Atom, JSON di WordPress, pagine HTML."""
import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

ROMA = ZoneInfo("Europe/Rome")

# ---------- testo ----------

FRASI_STANDARD = re.compile(
    r"(L['’]articolo .{0,200}? proviene da .{0,80}?\.?$|The post .{0,200}? appeared first on .{0,80}?\.?$|"
    r"\s*(Continua a leggere|Leggi tutto|Read more)\b.*$)", re.I | re.S)


def pulisci_html(testo):
    testo = html.unescape(re.sub(r"<[^>]+>", " ", testo or ""))
    if "Â" in testo or "Ã" in testo:  # UTF-8 letto come latin-1 dal sito
        try:
            testo = testo.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    testo = re.sub(r"\s+", " ", testo).strip()
    testo = FRASI_STANDARD.sub("", testo).strip()
    return re.sub(r"\s*\[?(?:…|\.\.\.)\]?\s*$", "…", testo)


def accorcia(testo, n):
    return testo if len(testo) <= n else testo[:n].rsplit(" ", 1)[0] + "…"


# ---------- date ----------

def leggi_data(testo):
    if not testo:
        return None
    testo = str(testo).strip()
    try:
        d = parsedate_to_datetime(testo)
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.fromisoformat(testo.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=ROMA)  # senza fuso: ora italiana


# ---------- immagini ----------

IMG_NO = re.compile(r"(pixel|1x1|spacer|gravatar|emoji|feedburner|/ads?/|\.gif(\?|$)|logo|avatar|sprite|badge|placeholder)", re.I)
IMG_EST = re.compile(r"\.(jpe?g|png|webp|avif)(\?|$)", re.I)


def immagine_valida(url, base=""):
    if not url:
        return None
    url = html.unescape(str(url).strip())
    if url.startswith("//"):
        url = "https:" + url
    elif base and not url.startswith("http"):
        url = urljoin(base, url)
    return url if url.startswith("http") and not IMG_NO.search(url) else None


# ---------- feed ----------

def locale(tag):
    return tag.rsplit("}", 1)[-1]


def e_feed(dati):
    """True se i byte sembrano un feed (XML o JSON di WordPress) e non una pagina HTML."""
    testa = dati[:600].lstrip().lower()
    if testa.startswith(b"document.write("):  # archivio newsletter Mailchimp
        return True
    if testa.startswith((b"<!doctype html", b"<html")):
        return False
    return testa[:1] in (b"<", b"[") and (b"<rss" in dati[:3000].lower() or b"<feed" in dati[:3000].lower()
                                          or b"<rdf" in dati[:3000].lower() or testa[:1] == b"[")


def link_esterni(raw, base):
    host = urlparse(base).netloc.removeprefix("www.")
    out = []
    for h in re.findall(r"href=[\"'](https?://[^\"'#\s]+)", html.unescape(raw or "")):
        n = urlparse(h).netloc.removeprefix("www.")
        if n and n != host and h not in out:
            out.append(h)
    return out[:25]


def leggi_mailchimp(dati):
    """Archivio di newsletter Mailchimp (script 'generate-js'): data, titolo e link di ogni numero."""
    t = dati.decode("utf-8", "ignore").strip()
    t = t[t.index("(") + 1: t.rindex(")")]
    corpo = json.loads(t)
    voci = []
    for g, m, a, link, titolo in re.findall(r"(\d{2})/(\d{2})/(\d{4})\s*-\s*<a\s+href=\"([^\"]+)\"[^>]*>(.*?)</a>", corpo):
        voci.append({"title": pulisci_html(titolo), "link": html.unescape(link),
                     "date": datetime(int(a), int(m), int(g), 6, 0, tzinfo=ROMA),
                     "text": "", "links": [], "image": None})
    return voci


def leggi_feed(dati, base=""):
    dati = dati.lstrip()
    if dati[:15].lower() == b"document.write(":
        return leggi_mailchimp(dati)
    if dati[:1] in (b"[", b"{"):
        return leggi_wp_json(dati)
    for fine in (b"</rss>", b"</feed>", b"</rdf:RDF>"):  # alcuni siti accodano HTML dopo il feed
        i = dati.rfind(fine)
        if i != -1:
            dati = dati[: i + len(fine)]
            break
    try:
        radice = ET.fromstring(dati)
    except ET.ParseError:
        # HTML sporco dentro il feed (es. <link rel="preload">)
        pulito = re.sub(rb"<link\s+[^>]*rel=[\"'](?:preload|preconnect|stylesheet)[\"'][^>]*>", b"", dati)
        radice = ET.fromstring(pulito)
    voci = []
    for el in radice.iter():
        if locale(el.tag) not in ("item", "entry"):
            continue
        f, media = {}, []
        for ch in el:
            nome = locale(ch.tag)
            if nome == "link":
                href = ch.get("href")
                if href and (ch.get("rel") in (None, "alternate") or "link" not in f):
                    f["link"] = href
                elif (ch.text or "").strip():
                    f.setdefault("link", ch.text.strip())
            elif nome == "thumbnail" and ch.get("url"):
                media.append(ch.get("url"))
            elif nome in ("content", "enclosure", "image") and (ch.get("url") or ch.get("href")):
                url = ch.get("url") or ch.get("href")
                if nome == "enclosure":
                    f["enclosure"] = url
                if (ch.get("medium") == "image" or (ch.get("type") or "").startswith("image")
                        or IMG_EST.search(url) or nome == "image"):
                    media.append(url)
            elif nome == "guid" and (ch.text or "").startswith("http"):
                f["guid"] = ch.text.strip()
            elif nome in ("title", "pubDate", "published", "updated", "date", "description", "summary",
                          "content", "encoded", "subtitle"):
                f.setdefault(nome, ch.text or "")
            elif nome == "group":  # media:group (YouTube)
                for g in ch:
                    if locale(g.tag) == "description":
                        f["description"] = g.text or ""
        link = f.get("link") or f.get("guid") or f.get("enclosure")
        data = leggi_data(f.get("pubDate") or f.get("published") or f.get("updated") or f.get("date"))
        if not data or not f.get("title") or not link:
            continue
        raw = f.get("encoded") or f.get("content") or f.get("description") or f.get("summary") or f.get("subtitle") or ""
        corpo = f.get("description") or f.get("summary") or f.get("encoded") or f.get("content") or f.get("subtitle")
        imgs = re.findall(r"<img[^>]+src=[\"']([^\"']+)", html.unescape(raw) if "&lt;img" in raw else raw)
        voci.append({"title": pulisci_html(f["title"]), "link": link, "date": data,
                     "text": pulisci_html(corpo)[:700], "links": link_esterni(raw, link),
                     "image": next((u for u in (immagine_valida(x) for x in media + imgs) if u), None)})
    return voci


def leggi_wp_json(dati):
    """Articoli dall'API di WordPress (per i siti con il feed RSS rotto)."""
    voci = []
    for post in json.loads(dati):
        try:
            data = leggi_data((post.get("date_gmt") or "") + "+00:00") or leggi_data(post["date"])
            media = (post.get("_embedded") or {}).get("wp:featuredmedia") or [{}]
            raw = (post.get("content") or {}).get("rendered", "")
            voci.append({"title": pulisci_html(post["title"]["rendered"]), "link": post["link"], "date": data,
                         "text": pulisci_html((post.get("excerpt") or {}).get("rendered", ""))[:700],
                         "links": link_esterni(raw, post["link"]),
                         "image": immagine_valida(media[0].get("source_url"))})
        except (KeyError, TypeError, AttributeError):
            continue
    return voci


# ---------- pagine HTML ----------

def attributi(tag):
    return {k.lower(): html.unescape(a or b) for k, a, b in
            re.findall(r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", tag)}


def _json_ld(pagina):
    out = []
    for blocco in re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", pagina, re.S | re.I):
        try:
            out.append(json.loads(blocco.strip()))
        except ValueError:
            continue
    return out


def _cerca_chiave(oggetto, chiave):
    if isinstance(oggetto, dict):
        if chiave in oggetto:
            return oggetto[chiave]
        for v in oggetto.values():
            r = _cerca_chiave(v, chiave)
            if r:
                return r
    elif isinstance(oggetto, list):
        for v in oggetto:
            r = _cerca_chiave(v, chiave)
            if r:
                return r
    return None


def meta_articolo(pagina, url):
    """Titolo, descrizione, immagine e data di pubblicazione di una pagina di articolo."""
    meta = {}
    for tag in re.findall(r"<meta\s[^>]*>", pagina[:300000], re.I):
        a = attributi(tag)
        chiave = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
        if chiave and a.get("content"):
            meta.setdefault(chiave, a["content"])
    ld = _json_ld(pagina)
    data = (meta.get("article:published_time") or meta.get("og:article:published_time") or meta.get("datepublished")
            or _cerca_chiave(ld, "datePublished") or meta.get("date") or meta.get("dc.date")
            or meta.get("article:modified_time") or meta.get("og:updated_time"))
    if not data:
        m = re.search(r"<time[^>]+datetime=[\"']([^\"']+)", pagina)
        data = m.group(1) if m else None
    img = meta.get("og:image") or meta.get("twitter:image")
    if not img:
        i = _cerca_chiave(ld, "image")
        img = i if isinstance(i, str) else (i.get("url") if isinstance(i, dict) else (i[0] if isinstance(i, list) and i and isinstance(i[0], str) else None))
    titolo = meta.get("og:title") or _cerca_chiave(ld, "headline")
    if not titolo:
        m = re.search(r"<title[^>]*>(.*?)</title>", pagina, re.S | re.I)
        titolo = m.group(1) if m else ""
    sito = meta.get("og:site_name") or ""
    titolo = pulisci_html(titolo)
    if sito and titolo.lower().endswith(sito.lower()):  # "Titolo | Nome sito"
        titolo = re.sub(r"\s*[|\-–—:]\s*" + re.escape(sito) + r"\s*$", "", titolo, flags=re.I)
    return {"title": titolo, "text": pulisci_html(meta.get("og:description") or meta.get("description") or ""),
            "image": immagine_valida(img, url), "date": leggi_data(data), "site": sito}


NO_ARTICOLO = re.compile(
    r"^/(tag|tags|category|categoria|categorie|autore|autori|author|authors|chi-siamo|about|contatti|contact|privacy|cookie|"
    r"sostienici|abbonati|abbonamenti|newsletter|login|accedi|registrati|search|cerca|page|pagina|serie|sezione|sezioni|"
    r"rubrica|rubriche|archivio|archive|feed|rss|wp-|shop|negozio|podcast|eventi|pubblicazioni|collane|riviste)(/|$)", re.I)


def sembra_articolo(percorso):
    percorso = percorso.rstrip("/")
    if not percorso or NO_ARTICOLO.match(percorso):
        return False
    ultimo = percorso.rsplit("/", 1)[-1]
    return ultimo.count("-") >= 2 or len(ultimo) >= 24 or re.search(r"/\d{4}/\d{2}/", percorso) is not None


def link_candidati(pagina, base, domini=()):
    """Collegamenti a probabili articoli in una pagina di elenco (home, archivio)."""
    host = urlparse(base).netloc.removeprefix("www.")
    ammessi = {host, *[d.removeprefix("www.") for d in domini]}
    visti, out = set(), []
    for m in re.finditer(r"<a\s([^>]*)>(.*?)</a>", pagina, re.S | re.I):
        a = attributi(m.group(1))
        href = a.get("href", "")
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urljoin(base, href.split("#")[0])
        u = urlparse(url)
        if u.netloc.removeprefix("www.") not in ammessi and not any(u.netloc.endswith("." + d) for d in ammessi):
            continue
        percorso = u.path
        if "substack.com" in u.netloc:  # newsletter: gli articoli stanno sotto /p/
            if not percorso.startswith("/p/"):
                continue
        elif not sembra_articolo(percorso) or re.search(r"\.(jpg|png|pdf|zip|mp3|webp|gif)$", percorso, re.I):
            continue
        chiave = u.netloc.removeprefix("www.") + percorso.rstrip("/")
        if chiave in visti:
            continue
        titolo = pulisci_html(m.group(2))
        if len(titolo.split()) < 3 and "substack.com" not in u.netloc:
            continue
        visti.add(chiave)
        out.append((url, titolo))
    return out


def trova_feed(pagina, base):
    """Indirizzi di feed dichiarati da una pagina (<link rel=alternate>)."""
    out = []
    for tag in re.findall(r"<link\s[^>]*>", pagina, re.I):
        a = attributi(tag)
        if a.get("type", "").lower() in ("application/rss+xml", "application/atom+xml") and a.get("href"):
            u = urljoin(base, a["href"])
            if "comments" not in u and u not in out:
                out.append(u)
    return out


def dominio(url):
    host = urlparse(url if "//" in url else "//" + url).netloc.lower()
    host = host.split(":")[0]
    for prefisso in ("www.", "feeds.", "feed.", "rss."):
        host = host.removeprefix(prefisso)
    return host
