"""Dai feed alla pagina: fatti (storie), opinioni collegate, argomenti, editoriale e tendenze."""
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import ia
from .config import RADICE
from .parsers import accorcia

PAROLE = {
    "Guerra in Ucraina": ["ucraina", "ucrain", "kiev", "kyiv", "zelensky", "putin", "mosca", "russia", "starlink"],
    "Medio Oriente": ["gaza", "israele", "israelian", "netanyahu", "hamas", "libano", "iran", "palestin", "houthi", "yemen", "siria", "arabia saudita"],
    "Stati Uniti": ["trump", "stati uniti", "usa ", "biden", "casa bianca", "washington", "vance", "midterm", "congresso"],
    "Europa e Unione Europea": ["unione europea", " ue ", "bruxelles", "commissione europea", "parlamento europeo", "von der leyen", "eurozona"],
    "Politica italiana": ["meloni", "governo", "salvini", "schlein", "parlamento", "senato", "camera dei deputati", "m5s", "forza italia", "tajani", "mattarella", "ministro", "elezioni", "referendum", "pd "],
    "Economia e lavoro": ["econom", "inflazione", "banca", "tasse", "lavoro", "sindacat", "pil ", "mercati", "borsa", "stipend", "spread", "bce", "manovra", "ilva", "imprese", "autotrasportat", "affitt"],
    "Scienza e salute": ["scienza", "scienziat", "ricerca", "medic", "salute", "vaccin", "tumore", "cancro", "farmac", "nasa", "fisica", "astronom", "ospedal", "sanit", "biolog"],
    "Tecnologia e AI": ["intelligenza artificiale", " ai ", "chatgpt", "openai", "algoritm", "tecnolog", "google", "apple", "social network", "cyber", "software", "tiktok", "revolut", "robot", "linguaggio di programmazione"],
    "Ambiente ed energia": ["energia", "nucleare", "gas ", "petrolio", "rinnovabil", "ambiente", "emission", "carbonio", "clima", "climatic"],
    "Diritti e società": ["diritti", "migrant", "immigra", "aborto", "razzis", "donne", "femminicid", "carcere", "scuola", "universit", "giovani", "protest"],
    "Cultura e idee": ["libro", "romanzo", "film", "cinema", "musica", "mostra", "filosof", "storia", "letteratur", "cultura", "teatro", "arte "],
    "Sport": ["calcio", "serie a", "champions", "nba", "tennis", "sinner", "olimpiad", "gol ", "formula 1", "motogp", "baseball", "squadra"],
    "Cronaca": ["arrest", "omicid", "incendio", "furto", "rubat", "incidente", "morti", "polizia", "carabinieri", "indagin"],
}
RUBRICHE = re.compile(r"^(ep\.?\s*\d+|peanuts|oroscopo|cruciverba|la newsletter|il podcast)\b", re.I)
STOP = set("""che con per una uno della delle dello degli dei del nel nella sono come anche più questo questa tra fra dopo prima
ogni gli dai dal alla alle contro sulla sulle sugli essere stato stati hanno dove quando quale quali cosa tutto tutti dalla dalle
nello negli nelle sotto sopra verso senza oltre ancora ormai stesso stessa altri altre molto molti poco tanto mentre perché però
quello quella questi queste ecco dice dicono secondo anni anno giorno giorni oggi ieri nuovo nuova nuovi nuove primo""".split())


@dataclass
class Composizione:
    storie: list = field(default_factory=list)
    editoriale: str = ""
    tendenze: list = field(default_factory=list)   # [{titolo, descrizione, uids}]
    con_ai: bool = False
    nota: str = ""
    modello: str = ""


def indovina_argomento(testo, ammessi=None):
    t = " " + testo.lower() + " "
    meglio, punti = "Altro", 0
    for argomento, parole in PAROLE.items():
        n = sum(t.count(p) for p in parole)
        if n > punti and (ammessi is None or argomento in ammessi):
            meglio, punti = argomento, n
    return meglio


def token(testo):
    return {w[:6] for w in re.findall(r"[a-zàèéìòù]{5,}", testo.lower()) if w not in STOP}


def storia(sid, argomento, titolo, testo, riferimenti, per_te=False):
    return {"id": sid, "topic": argomento, "titolo": titolo, "testo": testo, "refs": riferimenti,
            "image": next((r["image"] for r in riferimenti if r.get("image")), None),
            "ops": [], "per_te": per_te, "minor": False}


def assegna_uid(notizie, contenuti):
    for i, n in enumerate(notizie):
        n["uid"] = f"n{i}"
    for j, c in enumerate(contenuti):
        c["uid"] = f"c{j}"


# ---------- senza AI ----------

def componi_semplice(notizie, contenuti, argomenti):
    storie, visti = [], set()
    for n in notizie:
        if RUBRICHE.match(n["title"]) or n["title"] in visti:
            continue
        visti.add(n["title"])
        corpo = n["text"] if n["text"] and n["text"].lower() != n["title"].lower() else ""
        storie.append(storia(f"s{len(storie)}", indovina_argomento(n["title"] + " " + n["text"], argomenti),
                             n["title"], accorcia(corpo, 280), [n]))
    tk = [token(s["titolo"] + " " + s["testo"]) for s in storie]
    for c in contenuti:
        ct = token(c["title"] + " " + c["text"])
        migliore, punti = None, 0
        for s, t in zip(storie, tk):
            p = len(ct & t)
            if p > punti:
                migliore, punti = s, p
        c["summary"] = accorcia(c["text"], 200)
        if migliore is not None and punti >= 3:
            migliore["ops"].append(c)
            c["topic"] = migliore["topic"]
        else:
            c["topic"] = indovina_argomento(c["title"] + " " + c["text"], argomenti)
    for s in storie:
        s["ops"].sort(key=lambda o: o["date"], reverse=True)
    comp = Composizione(storie=storie)
    pesi = {}
    for s in storie:
        pesi[s["topic"]] = pesi.get(s["topic"], 0) + 1
    top = [t for t, _ in sorted(pesi.items(), key=lambda kv: -kv[1]) if t != "Altro"][:3]
    comp.editoriale = (f"Oggi {len(notizie)} notizie e {len(contenuti)} approfondimenti dalle tue fonti"
                       + (f"; i temi più presenti: {', '.join(top)}." if top else "."))
    return comp


# ---------- con AI ----------

def prompt_giornaliero(notizie, contenuti, argomenti, interessi, preferenze):
    def pacchetto(voci, base):
        return [{"id": base + i, "fonte": v["source"], "titolo": v["title"], "testo": v["text"][:300]} for i, v in enumerate(voci)]
    return (
        "Sei il caporedattore di un quotidiano italiano. Rispondi SOLO con JSON di questa forma:\n"
        '{"editoriale":"...","tendenze":[{"titolo":"...","descrizione":"...","ids":[3,1004]}],'
        '"fatti":[{"fid":"F1","argomento":"...","titolo":"...","testo":"...","ids":[0,1],"per_te":true}],'
        '"altre_notizie":[{"id":7,"argomento":"..."}],'
        '"contenuti":[{"id":1000,"argomento":"...","fatto":"F1","sintesi":"...","per_te":false}]}\n\n'
        f"ARGOMENTI AMMESSI (usa solo questi nomi): {json.dumps(argomenti, ensure_ascii=False)}\n\n"
        f"PROFILO DEL LETTORE (interessi e cose da evitare):\n{interessi or '(non indicato)'}\n"
        f"PREFERENZE RECENTI (👍 piace, 👎 non interessa): {preferenze or '(nessuna)'}\n\n"
        "REGOLE:\n"
        "- 'editoriale': il punto del giorno in 3-4 frasi neutre, per chi legge appena sveglio: cosa è successo di "
        "più importante e di cosa discutono le opinioni. Nessun giudizio tuo.\n"
        "- 'tendenze': 3-5 temi che ricorrono in più fonti oggi (titolo breve 2-5 parole, una frase di descrizione, "
        "'ids' di tutte le notizie e i contenuti che lo toccano).\n"
        "- 'fatti': ordinati per importanza nella giornata; il PRIMO è l'apertura (testo fino a 4 frasi). Ogni fatto ha "
        "un 'titolo' di cronaca (max 12 parole, informativo, senza giudizi) e un 'testo' di 1-3 frasi neutre: chi, "
        "cosa, dove, quando, numeri. Niente aggettivi valutativi, opinioni o retroscena. Unisci le notizie che "
        "raccontano lo stesso evento ('ids' = tutte le notizie che lo riportano). In tutto 10-30 fatti. "
        "'per_te' = true SOLO per i fatti che toccano in modo diretto e forte gli interessi del profilo, al massimo un quarto del totale; se il profilo indica cose da evitare, mai true.\n"
        "- 'altre_notizie': OGNI notizia NON usata in nessun fatto, con il suo argomento. Nessuna può mancare.\n"
        "- 'contenuti': per OGNI contenuto di approfondimento/opinione (nessuno escluso) indica 'argomento', una "
        "'sintesi' di una frase basata solo su titolo e testo, 'per_te' come sopra (al massimo un quarto dei contenuti) e 'fatto': il fid del fatto a cui "
        "si riferisce direttamente, oppure null se tratta un tema generale. Collega SOLO se il contenuto commenta quello stesso evento di cronaca; un tema affine o generale NON basta (in quel caso null). Nel dubbio, null.\n"
        "- Usa SOLO informazioni presenti nei testi forniti.\n\n"
        f"NOTIZIE:\n{json.dumps(pacchetto(notizie, 0), ensure_ascii=False)}\n\n"
        f"CONTENUTI:\n{json.dumps(pacchetto(contenuti, 1000), ensure_ascii=False)}"
    )



def componi_ai(risposta, notizie, contenuti, argomenti):
    ammessi = set(argomenti)
    ok = lambda t: t if t in ammessi else indovina_argomento(str(t), ammessi)  # noqa: E731
    storie, per_fid, usate = [], {}, set()
    for f in risposta.get("fatti", []):
        ids = [i for i in f.get("ids", []) if isinstance(i, int) and 0 <= i < len(notizie)]
        if not f.get("titolo"):
            continue
        s = storia(f"s{len(storie)}", ok(f.get("argomento", "")), str(f["titolo"]), str(f.get("testo", "")),
                   [notizie[i] for i in ids], bool(f.get("per_te")))
        storie.append(s)
        per_fid[str(f.get("fid", s["id"]))] = s
        usate.update(ids)
    argomento_di = {c["id"]: c.get("argomento") for c in risposta.get("altre_notizie", []) if isinstance(c.get("id"), int)}
    for i, n in enumerate(notizie):  # nessuna notizia può mancare: quelle non raggruppate restano singole
        if i in usate or RUBRICHE.match(n["title"]):
            continue
        s = storia(f"s{len(storie)}", ok(argomento_di.get(i) or indovina_argomento(n["title"] + " " + n["text"], ammessi)),
                   n["title"], accorcia(n["text"] if n["text"].lower() != n["title"].lower() else "", 240), [n])
        s["minor"] = True
        storie.append(s)
    for c in risposta.get("contenuti", []):
        idx = c.get("id", -1) - 1000 if isinstance(c.get("id"), int) else -1
        if not 0 <= idx < len(contenuti):
            continue
        it = contenuti[idx]
        it["summary"] = str(c.get("sintesi", "")).strip()
        it["per_te"] = bool(c.get("per_te"))
        s = per_fid.get(str(c.get("fatto")))
        if s:
            s["ops"].append(it)
            it["topic"] = s["topic"]
        else:
            it["topic"] = ok(c.get("argomento", ""))
    for it in contenuti:
        it.setdefault("summary", accorcia(it["text"], 200))
        it.setdefault("per_te", False)
        it.setdefault("topic", indovina_argomento(it["title"] + " " + it["text"], ammessi))
    for s in storie:
        s["ops"].sort(key=lambda o: o["date"], reverse=True)
        s["per_te"] = s["per_te"] or any(o["per_te"] for o in s["ops"])
    tendenze = []
    for t in risposta.get("tendenze", [])[:5]:
        uids = {f"n{i}" if i < 1000 else f"c{i - 1000}" for i in t.get("ids", []) if isinstance(i, int)}
        if t.get("titolo") and len(uids) >= 2:
            tendenze.append({"titolo": str(t["titolo"]), "descrizione": str(t.get("descrizione", "")), "uids": sorted(uids)})
    return Composizione(storie=storie, editoriale=str(risposta.get("editoriale", "")).strip(), tendenze=tendenze, con_ai=True)


# ---------- memoria dell'ultima composizione riuscita ----------
# Se l'AI non risponde (sovraccarico, limiti di richieste) non si torna di colpo alle parole chiave:
# le uscite già classificate dall'AI nell'edizione precedente mantengono argomento, sintesi e collegamenti.

PERCORSO_CACHE = RADICE / "data" / "ai_cache.json"
VALIDITA_CACHE = timedelta(hours=36)


def _percorso():
    return type(PERCORSO_CACHE)(os.environ.get("RASSEGNA_AI_CACHE", PERCORSO_CACHE))


def salva_cache(comp, notizie, contenuti):
    per_uid = {n["uid"]: n for n in notizie} | {c["uid"]: c for c in contenuti}
    maggiori = [s for s in comp.storie if not s["minor"]]
    indice = {id(s): i for i, s in enumerate(maggiori)}
    collegato = {id(o): indice[id(s)] for s in maggiori for o in s["ops"]}
    cache = {
        "ts": datetime.now(timezone.utc).isoformat(), "modello": ia.ultimo_modello, "editoriale": comp.editoriale,
        "tendenze": [{"titolo": t["titolo"], "descrizione": t["descrizione"], "links": [per_uid[u]["link"] for u in t["uids"] if u in per_uid]} for t in comp.tendenze],
        "fatti": [{"argomento": s["topic"], "titolo": s["titolo"], "testo": s["testo"], "per_te": s["per_te"], "links": [r["link"] for r in s["refs"]]} for s in maggiori],
        "notizie": {s["refs"][0]["link"]: s["topic"] for s in comp.storie if s["minor"] and s["refs"]},
        "contenuti": {c["link"]: {"a": c["topic"], "s": c.get("summary", ""), "p": bool(c.get("per_te")), "f": collegato.get(id(c))} for c in contenuti},
    }
    _percorso().parent.mkdir(exist_ok=True)
    _percorso().write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def carica_cache():
    try:
        c = json.loads(_percorso().read_text(encoding="utf-8"))
        if datetime.now(timezone.utc) - datetime.fromisoformat(c["ts"]) <= VALIDITA_CACHE:
            return c
    except (OSError, ValueError, KeyError):
        pass
    return None


def componi_da_cache(cache, notizie, contenuti, argomenti):
    """Ricostruisce la pagina con le classificazioni dell'AI già note; le uscite nuove vanno per parole chiave."""
    ammessi = set(argomenti)
    ok = lambda t: t if t in ammessi else indovina_argomento(str(t), ammessi)  # noqa: E731
    per_link = {n["link"]: n for n in notizie}
    storie, per_indice, usate = [], {}, set()
    for i, f in enumerate(cache.get("fatti", [])):
        refs = [per_link[l] for l in f.get("links", []) if l in per_link]
        if not refs:
            continue
        st = storia(f"s{len(storie)}", ok(f.get("argomento", "")), f.get("titolo", ""), f.get("testo", ""), refs, bool(f.get("per_te")))
        storie.append(st)
        per_indice[i] = st
        usate.update(r["link"] for r in refs)
    nuove = [n for n in notizie if n["link"] not in usate and not RUBRICHE.match(n["title"])]
    for n in nuove:  # uscite arrivate dopo l'ultima composizione dell'AI
        st = storia(f"s{len(storie)}", ok(cache.get("notizie", {}).get(n["link"]) or indovina_argomento(n["title"] + " " + n["text"], ammessi)),
                    n["title"], accorcia(n["text"] if n["text"].lower() != n["title"].lower() else "", 240), [n])
        st["minor"] = True
        storie.append(st)
    token_storie = [(st, token(st["titolo"] + " " + st["testo"])) for st in storie]
    for c in contenuti:
        info = cache.get("contenuti", {}).get(c["link"])
        if info:
            c["summary"], c["per_te"], c["topic"] = info.get("s") or accorcia(c["text"], 200), bool(info.get("p")), ok(info.get("a", ""))
            st = per_indice.get(info.get("f"))
            if st:
                st["ops"].append(c)
                c["topic"] = st["topic"]
            continue
        c["summary"], c["per_te"] = accorcia(c["text"], 200), False
        ct = token(c["title"] + " " + c["text"])
        migliore, punti = None, 0
        for st, tk in token_storie:
            p = len(ct & tk)
            if p > punti:
                migliore, punti = st, p
        if migliore is not None and punti >= 3:
            migliore["ops"].append(c)
            c["topic"] = migliore["topic"]
        else:
            c["topic"] = indovina_argomento(c["title"] + " " + c["text"], ammessi)
    for st in storie:
        st["ops"].sort(key=lambda o: o["date"], reverse=True)
        st["per_te"] = st["per_te"] or any(o["per_te"] for o in st["ops"])
    link_uid = {n["link"]: n["uid"] for n in notizie} | {c["link"]: c["uid"] for c in contenuti}
    tendenze = []
    for t in cache.get("tendenze", []):
        uids = sorted({link_uid[l] for l in t.get("links", []) if l in link_uid})
        if len(uids) >= 2:
            tendenze.append({"titolo": t["titolo"], "descrizione": t.get("descrizione", ""), "uids": uids})
    return Composizione(storie=storie, editoriale=cache.get("editoriale", ""), tendenze=tendenze, con_ai=True)


def componi(notizie, contenuti, argomenti, interessi="", preferenze="", salva=False):
    assegna_uid(notizie, contenuti)
    if ia.disponibile() and (notizie or contenuti):
        try:
            risposta = ia.chiedi(prompt_giornaliero(notizie, contenuti, argomenti, interessi, preferenze), nome="giornaliera")
            comp = componi_ai(risposta, notizie, contenuti, argomenti)
            comp.modello = ia.ultimo_modello
            if salva:
                salva_cache(comp, notizie, contenuti)
            return comp
        except Exception as e:  # noqa: BLE001  l'AI non deve mai impedire l'uscita della pagina
            motivo = f"{type(e).__name__}: {str(e)[:200]}"
            cache = carica_cache()
            if cache:
                comp = componi_da_cache(cache, notizie, contenuti, argomenti)
                comp.nota = ("L'AI non ha risposto in questo aggiornamento: uso la composizione dell'edizione precedente per le uscite già note "
                             f"e le parole chiave per le nuove. Riproverò al prossimo aggiornamento. ({motivo})")
                comp.modello = "memoria"
                return comp
            comp = componi_semplice(notizie, contenuti, argomenti)
            comp.nota = f"AI non disponibile ({motivo}): pagina composta senza AI."
            return comp
    comp = componi_semplice(notizie, contenuti, argomenti)
    comp.nota = "Modalità senza AI (manca GEMINI_API_KEY): argomenti e collegamenti per parole chiave, fatti senza riassunto."
    return comp
