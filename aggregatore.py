#!/usr/bin/env python3
"""Genera docs/index.html: fatti del giorno + tutte le uscite delle ultime 24 ore,
ordinati per argomento e impaginati.

Solo libreria standard. Con GEMINI_API_KEY aggiunge argomenti, fatti neutri e
sintesi; senza chiave l'elenco delle uscite è comunque completo.
"""
import html
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).parent
SOURCES = ROOT / "sources.txt"
OUT = ROOT / "docs" / "index.html"
HOURS = int(os.environ.get("ORE", "24"))
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"
DEFAULT_TOPICS = ["Politica italiana", "Esteri e geopolitica", "Economia e lavoro",
                  "Scienza e salute", "Tecnologia e AI", "Cultura e idee", "Altro"]


# ---------- rete ----------

def http_get(url, timeout=20, retries=1):
    """GET con ripiego su curl (certificati) e nuovi tentativi (YouTube è ballerino)."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.read()
            except urllib.error.URLError as e:
                if "CERTIFICATE_VERIFY_FAILED" not in str(e):
                    raise
                out = subprocess.run(["curl", "-sSLf", "--max-time", str(timeout), "-A", UA,
                                      "-H", "Accept-Language: it-IT,it;q=0.9", url],
                                     capture_output=True, check=True)
                return out.stdout
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


# ---------- fonti ----------

def read_sources():
    """Ritorna (fonti, voci, argomenti). Fonte = dict con nome, url, ruolo, etichetta, filtro."""
    entries, voices, topics = [], [], []
    role, label = None, ""
    for raw in SOURCES.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"\[([^\]:]+)(?::\s*([^\]]*))?\]", line)
        if m:
            role, label = m.group(1).strip().lower(), (m.group(2) or "").strip()
            continue
        if role == "voci":
            voices.append(line)
        elif role == "argomenti":
            topics.append(line)
        elif "=" in line and role:
            name, rest = (p.strip() for p in line.split("=", 1))
            url, _, opts = rest.partition("|")
            filt = []
            om = re.search(r"solo:\s*(.+)", opts)
            if om:
                filt = [w.strip().lower() for w in om.group(1).split(",") if w.strip()]
            entries.append({"name": name, "url": url.strip(), "role": role,
                            "label": label, "filter": filt})
    return entries, voices, topics or DEFAULT_TOPICS


def resolve_feed(url):
    """Trasforma un canale YouTube nel suo feed RSS; il resto resta com'è."""
    if "youtube.com" not in url or "feeds/videos.xml" in url:
        return url
    m = re.search(r"/channel/(UC[\w-]{22})", url)
    if not m:
        page = http_get(url, retries=3).decode("utf-8", "ignore")
        m = re.search(r'"channelId":"(UC[\w-]{22})"', page) or re.search(r"channel_id=(UC[\w-]{22})", page)
    if not m:
        raise ValueError("canale YouTube non riconosciuto")
    return "https://www.youtube.com/feeds/videos.xml?channel_id=" + m.group(1)


BOILERPLATE = re.compile(r"(L['’]articolo .{0,200}? proviene da .{0,80}?\.?$|The post .{0,200}? appeared first on .{0,80}?\.?$|"
                         r"\s*(Continua a leggere|Leggi tutto|Read more)\b.*$)", re.I | re.S)


def strip_html(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    if "Â" in text or "Ã" in text:  # UTF-8 letto come latin-1 dal sito
        try:
            text = text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*\[?(?:…|\.\.\.)\]?\s*$", "…", BOILERPLATE.sub("", text).strip())
    return text


def parse_date(text):
    if not text:
        return None
    text = text.strip()
    try:
        d = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def local(tag):
    return tag.rsplit("}", 1)[-1]


def video_id(link):
    m = re.search(r"(?:v=|youtu\.be/|/shorts/)([\w-]{11})", link or "")
    return m.group(1) if m else None


IMG_BAD = re.compile(r"(pixel|1x1|spacer|gravatar|emoji|feedburner|/ads?/|\.gif(\?|$)|logo|avatar|sprite|badge)", re.I)
IMG_EXT = re.compile(r"\.(jpe?g|png|webp|avif)(\?|$)", re.I)


def good_image(url):
    if not url:
        return None
    url = html.unescape(url.strip())
    if url.startswith("//"):
        url = "https:" + url
    return url if url.startswith("http") and not IMG_BAD.search(url) else None


def parse_feed(data):
    try:
        root = ET.fromstring(data.lstrip())
    except ET.ParseError:
        # alcuni siti inseriscono HTML sporco nel feed (es. <link rel="preload">)
        cleaned = re.sub(rb"<link\s+[^>]*rel=[\"'](?:preload|preconnect|stylesheet)[\"'][^>]*>", b"", data.lstrip())
        root = ET.fromstring(cleaned)
    items = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        f, media = {}, []
        for ch in el:
            name = local(ch.tag)
            if name == "link":
                href = ch.get("href")
                if href and (ch.get("rel") in (None, "alternate") or "link" not in f):
                    f["link"] = href
                elif (ch.text or "").strip():
                    f.setdefault("link", ch.text.strip())
            elif name == "thumbnail" and ch.get("url"):
                media.append(ch.get("url"))
            elif name in ("content", "enclosure", "image") and (ch.get("url") or ch.get("href")):
                url = ch.get("url") or ch.get("href")
                if name == "enclosure":
                    f["enclosure"] = url
                if (ch.get("medium") == "image" or (ch.get("type") or "").startswith("image")
                        or IMG_EXT.search(url) or name == "image"):
                    media.append(url)
            elif name == "guid" and (ch.text or "").startswith("http"):
                f["guid"] = ch.text.strip()
            elif name in ("title", "pubDate", "published", "updated", "description",
                          "summary", "content", "encoded", "subtitle"):
                f.setdefault(name, ch.text or "")
            elif name == "group":  # media:group (YouTube)
                for g in ch:
                    if local(g.tag) == "description":
                        f["description"] = g.text or ""
        link = f.get("link") or f.get("guid") or f.get("enclosure")
        date = parse_date(f.get("pubDate") or f.get("published") or f.get("updated"))
        if not date or not f.get("title") or not link:
            continue
        raw = f.get("encoded") or f.get("content") or f.get("description") or f.get("summary") or f.get("subtitle") or ""
        body = f.get("description") or f.get("summary") or f.get("encoded") or f.get("content") or f.get("subtitle")
        html_imgs = re.findall(r"<img[^>]+src=[\"']([^\"']+)", html.unescape(raw) if "&lt;img" in raw else raw)
        image = next((u for u in (good_image(x) for x in media + html_imgs) if u), None)
        items.append({"title": strip_html(f["title"]), "link": link, "date": date,
                      "text": strip_html(body)[:700], "image": image})
    return items


def fetch_og_image(item):
    """Immagine di anteprima dalla pagina dell'articolo (og:image)."""
    try:
        page = http_get(item["link"], timeout=10, retries=1)[:200000].decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return
    for pat in (r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]*content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\']'):
        m = re.search(pat, page)
        if m and good_image(m.group(1)):
            item["image"] = good_image(m.group(1))
            return


def add_missing_images(items):
    todo = [i for i in items if not i.get("image") and i["kind"] == "testo"]
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(fetch_og_image, todo))


def fetch_source(src):
    try:
        feed = resolve_feed(src["url"])
        is_yt = "youtube.com" in feed
        items = parse_feed(http_get(feed, retries=7 if is_yt else 4))
        role = src["role"]
        kind = "video" if is_yt else ("audio" if role in ("podcast", "selezione") else "testo")
        for it in items:
            it.update(source=src["name"], role=role, label=src["label"], kind=kind)
            if is_yt and video_id(it["link"]):
                it["image"] = "https://i.ytimg.com/vi/%s/mqdefault.jpg" % video_id(it["link"])
        if src["filter"]:
            items = [i for i in items if any(w in i["title"].lower() for w in src["filter"])]
        return src["name"], items, None
    except Exception as e:  # noqa: BLE001  una fonte rotta non deve fermare le altre
        return src["name"], [], f"{type(e).__name__}: {e}"


def collect(entries, since):
    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(fetch_source, entries))
    items, errors = [], []
    for name, found, err in results:
        if err:
            errors.append((name, err))
        items += [i for i in found if i["date"] >= since]
    items.sort(key=lambda i: i["date"], reverse=True)
    return items, errors


def search_voices(voices, known_titles, now):
    """Video di oggi su YouTube con una persona nel titolo, da canali non elencati."""
    found, seen = [], set(known_titles)

    def one(name):
        q = urllib.parse.quote(name)
        page = http_get(f"https://www.youtube.com/results?search_query={q}&sp=EgQIAhAB", retries=3).decode("utf-8", "ignore")
        m = re.search(r"var ytInitialData = (\{.*?\});</script>", page, re.S)
        if not m:
            return name, []
        data = json.loads(m.group(1))
        out = []

        def walk(o):
            if isinstance(o, dict):
                if "videoRenderer" in o:
                    out.append(o["videoRenderer"])
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(data)
        return name, out

    with ThreadPoolExecutor(3) as ex:
        results = list(ex.map(lambda n: _safe(one, n), voices))
    for res in results:
        if not res:
            continue
        name, vids = res
        surname = name.split()[-1].lower()
        for v in vids[:12]:
            try:
                vid = v["videoId"]
                title = "".join(r["text"] for r in v["title"]["runs"])
                chan = v["ownerText"]["runs"][0]["text"]
            except (KeyError, IndexError):
                continue
            if vid in seen or surname not in title.lower():
                continue
            seen.add(vid)
            desc = "".join(r["text"] for r in (v.get("detailedMetadataSnippets") or [{}])[0].get("snippetText", {}).get("runs", []))
            found.append({"title": title, "link": "https://www.youtube.com/watch?v=" + vid, "date": now,
                          "text": strip_html(desc)[:300], "source": chan, "role": "voci", "label": "",
                          "kind": "video", "guest": name,
                          "image": "https://i.ytimg.com/vi/%s/mqdefault.jpg" % vid})
    return found


def _safe(fn, arg):
    try:
        return fn(arg)
    except Exception:  # noqa: BLE001
        return None


# ---------- classificazione e collegamenti (senza AI) ----------

KEYWORDS = {
    "Guerra in Ucraina": ["ucraina", "ucrain", "kiev", "kyiv", "zelensky", "putin", "mosca", "russia", "starlink"],
    "Medio Oriente": ["gaza", "israele", "israelian", "netanyahu", "hamas", "libano", "iran", "palestin", "houthi", "yemen", "siria", "arabia saudita"],
    "Stati Uniti": ["trump", "stati uniti", "usa ", "biden", "casa bianca", "washington", "vance", "midterm", "congresso"],
    "Europa e Unione Europea": ["unione europea", " ue ", "bruxelles", "commissione europea", "parlamento europeo", "von der leyen", "eurozona"],
    "Politica italiana": ["meloni", "governo", "salvini", "schlein", "parlamento", "senato", "camera dei deputati", "m5s", "forza italia", "tajani", "mattarella", "ministro", "elezioni", "referendum", "pd "],
    "Economia e lavoro": ["econom", "inflazione", "banca", "tasse", "lavoro", "sindacat", "pil ", "mercati", "borsa", "stipend", "spread", "bce", "manovra", "ilva", "imprese", "autotrasportat", "affitt"],
    "Scienza e salute": ["scienza", "scienziat", "ricerca", "medic", "salute", "vaccin", "tumore", "cancro", "farmac", "nasa", "clima", "fisica", "astronom", "ospedal", "sanit", "biolog"],
    "Tecnologia e AI": ["intelligenza artificiale", " ai ", "chatgpt", "openai", "algoritm", "tecnolog", "google", "apple", "social network", "cyber", "software", "tiktok", "revolut", "robot", "linguaggio di programmazione"],
    "Ambiente ed energia": ["energia", "nucleare", "gas ", "petrolio", "rinnovabil", "ambiente", "emission", "carbonio"],
    "Diritti e società": ["diritti", "migrant", "immigra", "aborto", "razzis", "donne", "femminicid", "carcere", "scuola", "universit", "giovani", "protest"],
    "Cultura e idee": ["libro", "romanzo", "film", "cinema", "musica", "mostra", "filosof", "storia", "letteratur", "cultura", "teatro", "arte "],
    "Sport": ["calcio", "serie a", "champions", "nba", "tennis", "sinner", "olimpiad", "gol ", "formula 1", "motogp", "baseball", "squadra"],
    "Cronaca": ["arrest", "omicid", "incendio", "furto", "rubat", "incidente", "morti", "polizia", "carabinieri", "indagin"],
}
RUBRICS = re.compile(r"^(ep\.?\s*\d+|peanuts|oroscopo|cruciverba|la newsletter|il podcast)\b", re.I)
STOP = set("""che con per una uno della delle dello degli dei del nel nella sono come anche più questo questa tra fra dopo prima
ogni gli dai dal alla alle contro sulla sulle sugli essere stato stati hanno dove quando quale quali cosa tutto tutti dalla dalle
nello negli nelle sotto sopra verso senza oltre ancora ormai stesso stessa altri altre molto molti poco tanto mentre perché però
quello quella questi queste ecco dice dicono secondo anni anno giorno giorni oggi ieri nuovo nuova nuovi nuove primo prima""".split())


def guess_topic(text):
    t = " " + text.lower() + " "
    best, score = "Altro", 0
    for topic, words in KEYWORDS.items():
        n = sum(t.count(w) for w in words)
        if n > score:
            best, score = topic, n
    return best


def tokens(text):
    return {w[:6] for w in re.findall(r"[a-zàèéìòù]{5,}", text.lower()) if w not in STOP}


def clip(text, n):
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


def first_image(refs):
    return next((r["image"] for r in refs if r.get("image")), None)


def make_story(sid, topic, titolo, testo, refs):
    return {"id": sid, "topic": topic, "titolo": titolo, "testo": testo, "refs": refs,
            "image": first_image(refs), "ops": []}


def compose_fallback(news, contents):
    """Storie, collegamenti e argomenti senza AI: parole chiave e parole in comune."""
    stories, seen = [], set()
    for n in news:
        if RUBRICS.match(n["title"]) or n["title"] in seen:
            continue
        seen.add(n["title"])
        body = n["text"] if n["text"] and n["text"].lower() != n["title"].lower() else ""
        stories.append(make_story(f"s{len(stories)}", guess_topic(n["title"] + " " + n["text"]),
                                  n["title"], clip(body, 280), [n]))
    st_tokens = [tokens(s["titolo"] + " " + s["testo"]) for s in stories]
    for c in contents:
        ct = tokens(c["title"] + " " + c["text"])
        best, score = None, 0
        for s, tk in zip(stories, st_tokens):
            sc = len(ct & tk)
            if sc > score:
                best, score = s, sc
        c["summary"] = clip(c["text"], 200)
        if best is not None and score >= 3:
            best["ops"].append(c)
            c["topic"] = best["topic"]
        else:
            c["topic"] = guess_topic(c["title"] + " " + c["text"])
    for s in stories:
        s["ops"].sort(key=lambda o: o["date"], reverse=True)
    return stories


# ---------- AI (opzionale) ----------

def ask_gemini(prompt):
    key = os.environ["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}"
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"responseMimeType": "application/json",
                                            "maxOutputTokens": 32000, "temperature": 0.2,
                                            "thinkingConfig": {"thinkingBudget": 0}}}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=300)
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" not in str(e) or not Path("/etc/ssl/cert.pem").exists():
            raise
        # Python senza certificati di sistema (tipico su macOS): usa quelli del sistema
        r = urllib.request.urlopen(req, timeout=300, context=ssl.create_default_context(cafile="/etc/ssl/cert.pem"))
    with r:
        data = json.load(r)
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    (ROOT / ".cache").mkdir(exist_ok=True)
    (ROOT / ".cache" / "ultima_risposta_ai.json").write_text(text, encoding="utf-8")  # per controllare cosa ha risposto
    return json.loads(text)


def build_prompt(news, contents, topics):
    def pack(items, offset):
        return [{"id": offset + n, "fonte": i["source"], "titolo": i["title"], "testo": i["text"][:300]}
                for n, i in enumerate(items)]
    return (
        "Sei il caporedattore di un quotidiano italiano. Rispondi SOLO con JSON di questa forma:\n"
        '{"fatti":[{"fid":"F1","argomento":"...","titolo":"...","testo":"...","ids":[0,1]}],'
        '"altre_notizie":[{"id":7,"argomento":"..."}],'
        '"contenuti":[{"id":1000,"argomento":"...","fatto":"F1","sintesi":"..."}]}\n\n'
        f"ARGOMENTI AMMESSI (usa solo questi nomi): {json.dumps(topics, ensure_ascii=False)}\n\n"
        "REGOLE:\n"
        "- 'fatti': ordinati per importanza nella giornata; il PRIMO è l'apertura del giornale (testo fino a 4 "
        "frasi). Ogni fatto ha un 'titolo' di cronaca (max 12 parole, informativo, senza giudizi) e un 'testo' di "
        "1-3 frasi neutre: chi, cosa, dove, quando, numeri. Niente aggettivi valutativi, opinioni o retroscena. "
        "Unisci le notizie che raccontano lo stesso evento ('ids' = tutte le notizie che lo riportano). "
        "In tutto 10-30 fatti.\n"
        "- 'altre_notizie': OGNI notizia che NON hai usato in nessun fatto (rubriche e pezzi minori compresi) "
        "con il suo argomento. Nessuna notizia può mancare: o è in un fatto o è qui.\n"
        "- 'contenuti': per OGNI contenuto di approfondimento/opinione (nessuno escluso) indica 'argomento', "
        "'sintesi' di una frase basata solo su titolo e testo (se il testo è scarso, solo ciò che dice il titolo) e "
        "'fatto': il fid del fatto a cui il contenuto si riferisce direttamente, oppure null se tratta un tema "
        "generale. Collega solo se il contenuto parla proprio di quell'evento.\n"
        "- Usa SOLO informazioni presenti nei testi forniti.\n\n"
        f"NOTIZIE:\n{json.dumps(pack(news, 0), ensure_ascii=False)}\n\n"
        f"CONTENUTI:\n{json.dumps(pack(contents, 1000), ensure_ascii=False)}"
    )


def compose_ai(out, news, contents, topics):
    valid = set(topics)
    ok_topic = lambda t: t if t in valid else guess_topic(str(t))  # noqa: E731
    stories, by_fid, used = [], {}, set()
    for f in out.get("fatti", []):
        ids = [i for i in f.get("ids", []) if isinstance(i, int) and 0 <= i < len(news)]
        if not f.get("titolo"):
            continue
        st = make_story(f"s{len(stories)}", ok_topic(f.get("argomento", "")), str(f["titolo"]),
                        str(f.get("testo", "")), [news[i] for i in ids])
        stories.append(st)
        by_fid[str(f.get("fid", st["id"]))] = st
        used.update(ids)
    topic_of = {c["id"]: c.get("argomento") for c in out.get("altre_notizie", []) if isinstance(c.get("id"), int)}
    for i, n in enumerate(news):  # nessuna notizia può mancare: quelle non raggruppate restano singole
        if i in used or RUBRICS.match(n["title"]):
            continue
        stories.append(make_story(f"s{len(stories)}", ok_topic(topic_of.get(i) or guess_topic(n["title"] + " " + n["text"])),
                                  n["title"], clip(n["text"] if n["text"].lower() != n["title"].lower() else "", 240), [n]))
        stories[-1]["minor"] = True
    for c in out.get("contenuti", []):
        idx = c.get("id", -1) - 1000 if isinstance(c.get("id"), int) else -1
        if not 0 <= idx < len(contents):
            continue
        it = contents[idx]
        it["summary"] = str(c.get("sintesi", "")).strip()
        st = by_fid.get(str(c.get("fatto")))
        if st:
            st["ops"].append(it)
            it["topic"] = st["topic"]
        else:
            it["topic"] = ok_topic(c.get("argomento", ""))
    for it in contents:
        it.setdefault("summary", clip(it["text"], 200))
        it.setdefault("topic", guess_topic(it["title"] + " " + it["text"]))
    for s in stories:
        s["ops"].sort(key=lambda o: o["date"], reverse=True)
    return stories


def enrich(news, contents, topics):
    try:
        return compose_ai(ask_gemini(build_prompt(news, contents, topics)), news, contents, topics), None
    except Exception as e:  # noqa: BLE001
        return compose_fallback(news, contents), f"AI non disponibile ({type(e).__name__}: {e}): pagina composta senza AI."


# ---------- HTML ----------

CSS = """
:root{--paper:#fbfaf6;--ink:#1d1d1a;--mut:#7a766b;--rule:#e7e3d8;--soft:#f3f0e7;
--fact:#2f5d8c;--op:#a4552f}
@media(prefers-color-scheme:dark){:root{--paper:#161613;--ink:#e9e6dc;--mut:#9a9689;--rule:#2d2b25;--soft:#1e1d19;
--fact:#7fb0e6;--op:#e99a74}}
*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;background:var(--paper);color:var(--ink);font:16.5px/1.5 'Iowan Old Style','Palatino Linotype',Palatino,Georgia,serif;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}a:hover{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px}
img{display:block}
.sn{font:11.5px/1.3 -apple-system,'Helvetica Neue',system-ui,sans-serif;color:var(--mut)}
.sc{font:600 10.5px/1.2 -apple-system,'Helvetica Neue',system-ui,sans-serif;letter-spacing:.12em;text-transform:uppercase}
.page{max-width:1100px;margin:0 auto;padding:0 24px 80px}
.f{color:var(--fact)}.o{color:var(--op)}
.sq:before{content:"";display:inline-block;width:8px;height:8px;background:currentColor;margin-right:6px;vertical-align:0}

/* testata */
.np{display:flex;align-items:baseline;justify-content:space-between;gap:16px;padding:26px 0 14px}
.np h1{margin:0;font-size:30px;letter-spacing:-.01em;font-weight:700}
.np .d{text-align:right}

/* barra dei filtri */
.bar{background:var(--paper);border-top:1px solid var(--ink);border-bottom:1px solid var(--rule);padding:9px 0 8px}
.bar .r1,.bar .r2{display:flex;flex-wrap:wrap;align-items:center;gap:6px 6px}
.bar .r2{margin-top:8px;gap:10px 14px}
.chip{font:12.5px/1 -apple-system,system-ui,sans-serif;border:1px solid var(--rule);background:transparent;color:var(--ink);padding:6px 10px;border-radius:99px;cursor:pointer}
.chip:hover{border-color:var(--ink)}.chip[aria-pressed=true]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.chip i{font-style:normal;color:var(--mut);margin-left:5px}.chip[aria-pressed=true] i{color:inherit;opacity:.7}
select{font:12.5px -apple-system,system-ui,sans-serif;color:var(--ink);background:var(--paper);border:1px solid var(--rule);border-radius:6px;padding:5px 8px;max-width:220px}
.seg{display:inline-flex;border:1px solid var(--rule);border-radius:6px;overflow:hidden}
.seg button{font:12.5px -apple-system,system-ui,sans-serif;border:0;background:transparent;color:var(--ink);padding:5px 11px;cursor:pointer}
.seg button+button{border-left:1px solid var(--rule)}.seg button[aria-pressed=true]{background:var(--ink);color:var(--paper)}
.bar .st{margin-left:auto}
.reset{font:12.5px -apple-system,system-ui,sans-serif;color:var(--mut);background:none;border:0;cursor:pointer;text-decoration:underline}

/* miniature */
a.th{flex:none;display:block;background:var(--soft);overflow:hidden;border-radius:3px}
a.th img{width:100%;height:100%;object-fit:cover}
.story .th{width:104px;height:72px}.lead .th{width:168px;height:112px}.op .th,.card .th{width:52px;height:52px}

/* fatto + opinioni collegate */
.story{border-left:2px solid var(--fact);padding-left:14px;scroll-margin-top:90px}
.fact{display:flex;gap:16px;justify-content:space-between;align-items:flex-start}
.story h3{margin:0 0 4px;font-size:19.5px;line-height:1.22;font-weight:700;letter-spacing:-.005em}
.story .txt{margin:0;font-size:15.5px;line-height:1.48;color:color-mix(in srgb,var(--ink) 86%,var(--paper))}
.src{margin-top:6px}.src a{margin-right:10px;color:var(--fact)}
.thread{margin:12px 0 2px 2px;padding-left:14px;border-left:2px solid var(--op)}
.thread>.hd{margin-bottom:2px;color:var(--op)}
.op{display:flex;gap:12px;align-items:flex-start;padding:9px 0;border-top:1px solid var(--rule)}
.op:first-of-type{border-top:0}
.op .by,.card .by{display:block;margin-bottom:1px}
.op a.t,.card a.t{font-size:16px;line-height:1.28;font-weight:600;font-style:italic}
.op p,.card p{margin:2px 0 0;font-size:14px;line-height:1.4;color:var(--mut)}
.story.ctx .txt,.story.ctx .src,.story.ctx .th{display:none}
.story.ctx h3{font-size:14.5px;font-weight:600;color:var(--mut)}
.story.ctx .thread{margin-top:6px}

/* apertura */
.lead{margin-top:26px;padding-bottom:6px}
.lead h3{font-size:clamp(26px,3.6vw,38px);line-height:1.1;margin:0 0 8px;letter-spacing:-.015em}
.lead .txt{font-size:17.5px;line-height:1.5}
.lead .thread{margin-top:16px}
.lead>.sc{display:block;margin:0 0 8px}

/* sezioni */
section.sez{margin-top:46px}
.sez>.h{display:flex;align-items:baseline;gap:14px;border-bottom:1px solid var(--ink);padding-bottom:7px;margin-bottom:22px}
.sez>.h h2{margin:0;font-size:22px;letter-spacing:-.005em}
.sez>.h .sn{margin-left:auto}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:30px 44px;align-items:start}
.sub{margin-top:30px}.sub>.hd{padding-bottom:6px;margin-bottom:10px;border-bottom:1px solid var(--rule)}
.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:2px 44px}
.card{display:flex;gap:12px;align-items:flex-start;padding:10px 0 10px 12px;border-left:2px solid var(--op);border-bottom:1px solid var(--rule);margin-bottom:-1px}
.others ul{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 44px}
.others li{padding:7px 0 7px 12px;border-left:2px solid var(--fact);border-bottom:1px solid var(--rule);font-size:15.5px;line-height:1.3}
.others li a{font-weight:600}
.others li .sn{display:block}

/* indice completo */
.full{margin-top:60px;border-top:1px solid var(--ink);padding-top:10px}
.full details{border-bottom:1px solid var(--rule);padding:7px 0}
.full summary{cursor:pointer;font:600 13px -apple-system,system-ui,sans-serif;list-style:none}
.full summary::-webkit-details-marker{display:none}.full summary:before{content:"▸ ";color:var(--mut)}
.full details[open] summary:before{content:"▾ "}.full summary i{font-style:normal;color:var(--mut);font-weight:500}
.full ul{list-style:none;margin:6px 0 2px;padding:0}.full li{padding:2px 0 2px 10px;font-size:14.5px;line-height:1.35;border-left:2px solid var(--fact)}
.full li.p{border-left-color:var(--op)}.full li span{font:11px -apple-system,system-ui,sans-serif;color:var(--mut);margin-right:8px}
.warn{margin-top:30px;padding:10px 12px;border:1px solid var(--rule);background:var(--soft);font:12.5px/1.5 -apple-system,system-ui,sans-serif;color:var(--mut)}
.empty{padding:50px 0;text-align:center;color:var(--mut);font-style:italic}
[data-fsrc]{cursor:pointer}[data-fsrc]:hover{color:var(--ink);text-decoration:underline dotted}

@media(max-width:860px){.grid,.cards,.others ul{grid-template-columns:1fr}}
@media(max-width:600px){.bar .r1{flex-wrap:nowrap;overflow-x:auto;padding-bottom:4px;scrollbar-width:none}.bar .r1::-webkit-scrollbar{display:none}.chip{white-space:nowrap}
 .page{padding:0 16px 60px}.np{flex-direction:column;gap:4px;padding-top:18px}.np .d{text-align:left}
 .lead .th{width:96px;height:72px}.bar .st{margin-left:0}}
"""

JS = """
(()=>{
const $=(q,r=document)=>[...r.querySelectorAll(q)];
const st={topic:'',src:'',kind:'all'};
const P=new URLSearchParams(location.hash.slice(1));
st.topic=P.get('tema')||'';st.src=P.get('fonte')||'';st.kind=P.get('tipo')||'all';
const hasSrc=(el)=>!st.src||(el.dataset.src||'').split('|').includes(st.src);
function apply(){
 let n=0;
 const story=(s)=>{
  const factOk=st.kind!=='opinioni'&&hasSrc(s);
  let ops=0;
  $('.op',s).forEach(o=>{const ok=st.kind!=='fatti'&&hasSrc(o);o.hidden=!ok;if(ok)ops++});
  const th=$('.thread',s)[0];if(th){th.hidden=!ops;const c=$('.cnt',th)[0];if(c)c.textContent=ops}
  const show=factOk||ops>0;s.hidden=!show;s.classList.toggle('ctx',show&&!factOk);
  return show?(factOk?1:0)+ops:0;
 };
 $('.lead').forEach(l=>{const ok=!st.topic||l.dataset.topic===st.topic;const s=$('.story',l)[0];const c=ok?story(s):0;l.hidden=!c;n+=c});
 $('section.sez').forEach(sec=>{
  if(st.topic&&sec.dataset.topic!==st.topic){sec.hidden=true;return}
  let c=0;
  $('.story',sec).forEach(s=>{c+=story(s)});
  $('.card',sec).forEach(k=>{const ok=st.kind!=='fatti'&&hasSrc(k);k.hidden=!ok;if(ok)c++});
  $('.others li',sec).forEach(k=>{const ok=st.kind!=='opinioni'&&hasSrc(k);k.hidden=!ok;if(ok)c++});
  $('.sub',sec).forEach(g=>{g.hidden=!$('.card,li',g).some(x=>!x.hidden)});
  $('.grid',sec).forEach(g=>{g.hidden=!$('.story',g).some(x=>!x.hidden)});
  sec.hidden=!c;n+=c;
 });
 $('.full details').forEach(d=>{
  let v=0;$('li',d).forEach(li=>{const nw=li.classList.contains('n');
   const ok=(!st.topic||li.dataset.topic===st.topic)&&(st.kind==='all'||(st.kind==='fatti')===nw)&&(!st.src||d.dataset.src===st.src);
   li.hidden=!ok;if(ok)v++});
  d.hidden=!v;if(st.src&&v)d.open=true;$('summary i',d)[0].textContent='· '+v;
 });
 $('[data-topic-chip]').forEach(b=>b.setAttribute('aria-pressed',String((b.dataset.topicChip||'')===st.topic)));
 $('[data-kind]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.kind===st.kind)));
 $('#fonte')[0].value=st.src;
 const on=st.topic||st.src||st.kind!=='all';
 $('.reset')[0].hidden=!on;
 $('.st')[0].textContent=on?(n+' voci con questi filtri'):'';
 const q=new URLSearchParams();if(st.topic)q.set('tema',st.topic);if(st.src)q.set('fonte',st.src);if(st.kind!=='all')q.set('tipo',st.kind);
 history.replaceState(null,'',q.toString()?'#'+q:location.pathname+location.search);
}
document.addEventListener('click',e=>{
 const t=e.target.closest('[data-topic-chip],[data-kind],.reset,[data-fsrc]');if(!t)return;
 if(t.matches('[data-topic-chip]'))st.topic=t.dataset.topicChip;
 else if(t.matches('[data-kind]'))st.kind=t.dataset.kind;
 else if(t.matches('.reset')){st.topic='';st.src='';st.kind='all'}
 else{st.src=st.src===t.dataset.fsrc?'':t.dataset.fsrc;window.scrollTo(0,0)}
 apply();
});
$('#fonte')[0].addEventListener('change',e=>{st.src=e.target.value;apply()});
apply();
})();
"""

E_ = html.escape
MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
          "settembre", "ottobre", "novembre", "dicembre"]
DAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
FULL_PER_TOPIC = 6  # oltre questa soglia i fatti minori diventano righe compatte


def hhmm(d):
    return d.astimezone().strftime("%H:%M")


def a_(s):
    return E_(s, quote=True)


def thumb(url, link):
    if not url or not link:
        return ""
    return (f'<a class="th" href="{a_(link)}"><img src="{a_(url)}" alt="" loading="lazy" referrerpolicy="no-referrer" '
            f'onerror="this.closest(\'a\').remove()" onload="if(this.naturalWidth<60)this.closest(\'a\').remove()"></a>')


def by_line(it):
    return (f'<span class="by sc"><span data-fsrc="{a_(it["source"])}" title="Mostra solo {a_(it["source"])}">{E_(it["source"])}</span>'
            f' <span style="font-weight:500;opacity:.7">· {hhmm(it["date"])}</span></span>')


def op_row(o):
    s = o.get("summary") or clip(o["text"], 160)
    return (f'<div class="op o" data-src="{a_(o["source"])}">{thumb(o.get("image"), o["link"])}<div>{by_line(o)}'
            f'<a class="t" style="color:var(--ink)" href="{a_(o["link"])}">{E_(o["title"])}</a>'
            + (f'<p>{E_(s)}</p>' if s else "") + "</div></div>")


def story_html(st, lead=False):
    refs = st["refs"]
    link = refs[0]["link"] if refs else None
    title = f'<a href="{a_(link)}">{E_(st["titolo"])}</a>' if link else E_(st["titolo"])
    srcs = "".join(f'<a href="{a_(r["link"])}">{E_(r["source"])}</a>' for r in {r["source"]: r for r in refs}.values())
    thr = ""
    if st["ops"]:
        thr = (f'<div class="thread"><div class="hd sc sq">Opinioni su questo fatto · <span class="cnt">{len(st["ops"])}</span></div>'
               + "".join(op_row(o) for o in st["ops"]) + "</div>")
    tx = (f'<div><h3>{title}</h3>' + (f'<p class="txt">{E_(st["testo"])}</p>' if st["testo"] else "")
          + (f'<div class="src sn">Fonti: {srcs}</div>' if srcs else "") + "</div>")
    return (f'<article class="story" id="{st["id"]}" data-src="{a_("|".join(dict.fromkeys(r["source"] for r in refs)))}">'
            f'<div class="fact">{tx}{thumb(st["image"], link)}</div>{thr}</article>')


def card_html(o):
    s = o.get("summary") or clip(o["text"], 160)
    return (f'<div class="card" data-src="{a_(o["source"])}">{thumb(o.get("image"), o["link"])}<div>{by_line(o)}'
            f'<a class="t" href="{a_(o["link"])}">{E_(o["title"])}</a>' + (f"<p>{E_(s)}</p>" if s else "") + "</div></div>")


def render(news, contents, stories, ai_note, errors, topics, now, ai_order=False, entries=()):
    free = {}
    linked = {id(o) for s in stories for o in s["ops"]}
    for c in contents:
        if id(c) not in linked:
            free.setdefault(c.get("topic") or "Altro", []).append(c)
    by_topic = {}
    for s in stories:
        by_topic.setdefault(s["topic"], []).append(s)
    names = list(dict.fromkeys(s["topic"] for s in stories))
    names += [t for t in free if t not in names]
    if not ai_order:
        weight = lambda t: sum(1 + len(s["ops"]) for s in by_topic.get(t, []) if not s.get("minor")) + len(free.get(t, []))  # noqa: E731
        names.sort(key=lambda t: (t == "Altro", -weight(t)))
        for t in by_topic:  # prima i fatti con opinioni e con foto
            by_topic[t].sort(key=lambda s: (-len(s["ops"]), not s["image"], not s["testo"]))
    else:
        names = [t for t in names if t != "Altro"] + [t for t in names if t == "Altro"]

    lead = None
    for t in names:
        pool = [s for s in by_topic.get(t, []) if not s.get("minor")]
        if pool:
            lead = pool[0] if ai_order else max(pool[:5], key=lambda s: (bool(s["image"]), len(s["ops"]), len(s["testo"])))
            break

    topic_of = {id(r): s["topic"] for s in stories for r in s["refs"]}
    cnt = lambda t: len(by_topic.get(t, [])) + len(free.get(t, []))  # noqa: E731
    date = f"{DAYS[now.weekday()]} {now.day} {MONTHS[now.month - 1]} {now.year}"
    counts = {}
    for it in news + contents:
        counts[it["source"]] = counts.get(it["source"], 0) + 1
    opts = []
    for grp, roles in (("Notizie", ("notizie",)), ("Approfondimenti", ("scritti",))):
        o = "".join(f'<option value="{a_(e["name"])}"{"" if counts.get(e["name"]) else " disabled"}>{E_(e["name"])} ({counts.get(e["name"], 0)})</option>'
                    for e in entries if e["role"] in roles)
        if o:
            opts.append(f'<optgroup label="{grp}">{o}</optgroup>')
    for e in entries:  # eventuali sezioni extra (YouTube, podcast) se riattivate
        if e["role"] not in ("notizie", "scritti") and counts.get(e["name"]):
            opts.append(f'<option value="{a_(e["name"])}">{E_(e["name"])} ({counts[e["name"]]})</option>')

    out = [f'<div class="page"><header class="np"><h1>La Rassegna</h1><div class="d sn">{E_(date)} · aggiornata alle {now:%H:%M}<br>'
           f'{len(news)} notizie · {len(contents)} approfondimenti · ultime {HOURS} ore · <a href="__ARCHIVIO__" style="text-decoration:underline">Edizioni precedenti</a></div></header>',
           '<div class="bar"><div class="r1">'
           f'<button class="chip" data-topic-chip="" aria-pressed="true">Tutti i temi</button>'
           + "".join(f'<button class="chip" data-topic-chip="{a_(t)}">{E_(t)}<i>{cnt(t)}</i></button>' for t in names)
           + '</div><div class="r2"><label class="sn">Fonte <select id="fonte"><option value="">Tutte le fonti</option>'
           + "".join(opts) + '</select></label>'
           '<span class="seg"><button data-kind="all">Tutto</button><button data-kind="fatti">Fatti</button><button data-kind="opinioni">Opinioni</button></span>'
           '<span class="sn"><span class="f sq">Fatti</span> &nbsp; <span class="o sq">Opinioni e analisi</span></span>'
           '<button class="reset" hidden>Azzera filtri</button><span class="st sn"></span></div></div>']
    if not names:
        out.append('<p class="empty">Nessuna uscita nelle ultime ore.</p>')

    if lead:
        out.append(f'<div class="lead" data-topic="{a_(lead["topic"])}"><span class="sc f">Apertura · {E_(lead["topic"])}</span>{story_html(lead, True)}</div>')

    for t in names:
        sl = [s for s in by_topic.get(t, []) if s is not lead]
        major = [s for s in sl if not s.get("minor")]
        minor = [s for s in sl if s.get("minor")]
        shown = major[:FULL_PER_TOPIC]
        compact = major[FULL_PER_TOPIC:] + minor
        fr = sorted(free.get(t, []), key=lambda o: o["date"], reverse=True)
        n_o = len(fr) + sum(len(s["ops"]) for s in sl)
        parts = [f'<div class="h"><h2>{E_(t)}</h2><span class="sn"><span class="f sq">{len(sl)}</span> &nbsp; <span class="o sq">{n_o}</span></span></div>']
        if shown:
            parts.append('<div class="grid">' + "".join(story_html(s) for s in shown) + "</div>")
        if fr:
            parts.append(f'<div class="sub"><div class="hd sc o sq">Idee e approfondimenti su questo tema · {len(fr)}</div>'
                         f'<div class="cards">{"".join(card_html(o) for o in fr)}</div></div>')
        if compact:
            li = "".join(
                f'<li data-src="{a_(s["refs"][0]["source"] if s["refs"] else "")}"><span class="sn">{E_(s["refs"][0]["source"] if s["refs"] else "")} · '
                f'{hhmm(s["refs"][0]["date"]) if s["refs"] else ""}</span>'
                f'<a href="{a_(s["refs"][0]["link"] if s["refs"] else "#")}">{E_(s["titolo"])}</a></li>' for s in compact)
            parts.append(f'<div class="sub others"><div class="hd sc f sq">Altre notizie · {len(compact)}</div><ul>{li}</ul></div>')
        out.append(f'<section class="sez" data-topic="{a_(t)}">{"".join(parts)}</section>')

    # indice completo: garanzia che nulla manchi (segue i filtri)
    groups = {}
    for i in news:
        groups.setdefault((i["source"], "n"), []).append(i)
    for i in contents:
        groups.setdefault((i["source"], "p"), []).append(i)
    det = []
    for (src, k), its in sorted(groups.items(), key=lambda kv: (kv[0][1] != "n", kv[0][0].lower())):
        li = "".join(f'<li class="{k}" data-topic="{a_(topic_of.get(id(i)) or i.get("topic") or "Altro")}"><span>{hhmm(i["date"])}</span>'
                     f'<a href="{a_(i["link"])}">{E_(i["title"])}</a></li>' for i in sorted(its, key=lambda i: i["date"], reverse=True))
        det.append(f'<details data-src="{a_(src)}"><summary>{E_(src)} <i>· {len(its)}</i></summary><ul>{li}</ul></details>')
    out.append(f'<div class="full"><div class="sc">Indice completo · {len(news) + len(contents)} uscite, nessuna esclusa</div>{"".join(det)}</div>')

    notes = [f"Fonte non raggiungibile: {n} ({m}). Le sue uscite potrebbero mancare oggi." for n, m in errors]
    if ai_note:
        notes.append(ai_note)
    if notes:
        out.append('<div class="warn">' + "<br>".join(E_(n) for n in notes) + "</div>")
    out.append("</div>")
    return (f'<!doctype html><html lang="it"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>La Rassegna — {now:%d/%m/%Y}</title>'
            f"<style>{CSS}</style></head><body>{''.join(out)}<script>{JS}</script></body></html>")


ARCHIVE_CSS = """body{margin:0;background:#fbfaf6;color:#1d1d1a;font:17px/1.5 'Iowan Old Style',Georgia,serif}
main{max-width:640px;margin:0 auto;padding:40px 24px 80px}h1{font-size:30px;margin:0 0 6px}p{color:#7a766b;font:13px -apple-system,system-ui,sans-serif;margin:0 0 26px}
a{color:inherit}ul{list-style:none;padding:0;margin:0}li{padding:9px 0;border-bottom:1px solid #e7e3d8}li a{text-decoration:none;font-size:18px}li a:hover{text-decoration:underline}
li span{font:12px -apple-system,system-ui,sans-serif;color:#7a766b;margin-left:10px}
@media(prefers-color-scheme:dark){body{background:#161613;color:#e9e6dc}li{border-color:#2d2b25}p,li span{color:#9a9689}}"""


def save_archive(page, now):
    """Conserva l'edizione del giorno in docs/archivio/ e rigenera l'indice delle edizioni."""
    folder = OUT.parent / "archivio"
    folder.mkdir(exist_ok=True)
    (folder / f"{now:%Y-%m-%d}.html").write_text(page.replace("__ARCHIVIO__", "./"), encoding="utf-8")
    rows = []
    for f in sorted(folder.glob("????-??-??.html"), reverse=True):
        d = datetime.strptime(f.stem, "%Y-%m-%d")
        rows.append(f'<li><a href="{f.name}">{DAYS[d.weekday()].capitalize()} {d.day} {MONTHS[d.month - 1]} {d.year}</a></li>')
    (folder / "index.html").write_text(
        f'<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Edizioni precedenti — La Rassegna</title><style>{ARCHIVE_CSS}</style></head><body><main>"
        f'<h1>Edizioni precedenti</h1><p><a href="../">← Torna all\'ultima edizione</a> · {len(rows)} edizioni conservate</p>'
        f'<ul>{"".join(rows)}</ul></main></body></html>', encoding="utf-8")


def main():
    now = datetime.now(timezone.utc).astimezone()
    since = now - timedelta(hours=HOURS)
    entries, voices, topics = read_sources()
    news, err_n = collect([e for e in entries if e["role"] == "notizie"], since)
    contents, err_c = collect([e for e in entries if e["role"] != "notizie"], since)
    if voices:
        contents += search_voices(voices, {video_id(i["link"]) for i in contents}, now)
    if not os.environ.get("NO_IMAGES"):
        add_missing_images(news + contents)

    ai_order = False
    if os.environ.get("GEMINI_API_KEY") and (news or contents):
        stories, ai_note = enrich(news, contents, topics)
        ai_order = ai_note is None
    else:
        stories = compose_fallback(news, contents)
        ai_note = "Modalità senza AI (manca GEMINI_API_KEY): argomenti e collegamenti per parole chiave, fatti senza riassunto."
    page = render(news, contents, stories, ai_note, err_n + err_c, topics, now, ai_order, entries)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page.replace("__ARCHIVIO__", "archivio/"), encoding="utf-8")
    save_archive(page, now)
    imgs = sum(1 for i in news + contents if i.get("image"))
    print(f"{len(news)} notizie, {len(contents)} contenuti, {imgs} con foto -> {OUT}")
    for n, m in err_n + err_c:
        print(f"  ! {n}: {m}", file=sys.stderr)
    if ai_note:
        print(f"  * {ai_note}", file=sys.stderr)


if __name__ == "__main__":
    main()
