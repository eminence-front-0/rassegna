"""Costruzione della pagina HTML. Tutto in un file autonomo: stile e script sono inseriti nella pagina."""
import html
import json
import re
import zlib
from dataclasses import dataclass, field
from datetime import datetime

from .config import RADICE
from .loghi import slug
from .parsers import accorcia

E = lambda s: html.escape(str(s), quote=True)  # noqa: E731
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
        "settembre", "ottobre", "novembre", "dicembre"]
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
PER_ARGOMENTO = 6  # oltre questa soglia i fatti minori diventano righe compatte

ICONE = {
    "up": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10v12"/><path d="M15 5.9 14 10h5.8a2 2 0 0 1 1.9 2.6l-2.3 7A2 2 0 0 1 17.5 21H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h2.8a2 2 0 0 0 1.8-1.1L12 3a3.1 3.1 0 0 1 3 2.9Z"/></svg>',
    "down": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 14V2"/><path d="M9 18.1 10 14H4.2a2 2 0 0 1-1.9-2.6l2.3-7A2 2 0 0 1 6.5 3H20a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-2.8a2 2 0 0 0-1.8 1.1L12 21a3.1 3.1 0 0 1-3-2.9Z"/></svg>',
    "save": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16Z"/></svg>',
    "cerca": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>',
}


@dataclass
class Contesto:
    adesso: datetime
    notizie: list
    contenuti: list
    comp: object
    argomenti: list
    esiti: list
    fonti: list
    loghi: dict = field(default_factory=dict)
    suggerimenti: list = field(default_factory=list)
    repo: str = ""
    ore: int = 24
    avvisi: list = field(default_factory=list)


def hhmm(d):
    return d.astimezone().strftime("%H:%M")


def quando(d, adesso):
    loc, ora = d.astimezone(), adesso.astimezone()
    return hhmm(d) if loc.date() == ora.date() else f"{loc.day} {MESI[loc.month - 1][:3]} · {hhmm(d)}"


# ---------- elementi ----------

def logo(ctx, nome, extra=""):
    f = ctx.loghi.get(nome)
    if f:
        return f'<img class="lg {extra}" src="__BASE__logos/{E(f)}" alt="" loading="lazy" onerror="this.outerHTML=\'<span class=&quot;lg fb {extra}&quot; style=&quot;background:hsl({zlib.crc32(nome.encode()) % 360} 55% 48%)&quot;>{E(nome[:1].upper())}</span>\'">'
    tinta = zlib.crc32(nome.encode()) % 360
    return f'<span class="lg fb {extra}" style="background:hsl({tinta} 55% 48%)">{E(nome[:1].upper())}</span>'


def azioni():
    return ('<div class="acts">'
            f'<button class="ic" data-act="up" title="Mi interessa" aria-pressed="false">{ICONE["up"]}</button>'
            f'<button class="ic" data-act="down" title="Non mi interessa" aria-pressed="false">{ICONE["down"]}</button>'
            f'<button class="ic" data-act="save" title="Salva per dopo" aria-pressed="false">{ICONE["save"]}</button></div>')


def miniatura(img, link, piccola=False):
    if not img or not link:
        return ""
    return (f'<a class="thumb{" sm" if piccola else ""}" href="{E(link)}" tabindex="-1" aria-hidden="true">'
            f'<img src="{E(img)}" alt="" loading="lazy" referrerpolicy="no-referrer" '
            f'onerror="this.closest(\'a\').remove()" onload="if(this.naturalWidth<60)this.closest(\'a\').remove()"></a>')


def dati(it, uid_chiave):
    return (f'data-link="{E(it["link"])}" data-src="{E(it["source"])}" data-fonte="{E(it["source"])}" '
            f'data-titolo="{E(it["title"])}" data-per="{1 if it.get("per_te") else 0}" {uid_chiave}')


def op_html(ctx, o):
    s = o.get("summary") or accorcia(o["text"], 160)
    return (f'<div class="op" {dati(o, "data-c=" + chr(34) + o["uid"] + chr(34))}>'
            f'{miniatura(o.get("image"), o["link"], True)}<div class="op-body">'
            f'<div class="meta">{logo(ctx, o["source"])}<span class="who" data-fsrc="{E(o["source"])}" title="Mostra solo {E(o["source"])}">{E(o["source"])}</span>'
            f'<span class="num">· {quando(o["date"], ctx.adesso)}</span>{"<span class=" + chr(34) + "badge per" + chr(34) + ">Per te</span>" if o.get("per_te") else ""}</div>'
            f'<a class="t" href="{E(o["link"])}">{E(o["title"])}</a>' + (f"<p>{E(s)}</p>" if s else "") + f'</div>{azioni()}</div>')


def fcard_html(ctx, o):
    s = o.get("summary") or accorcia(o["text"], 160)
    return (f'<article class="fcard rv" {dati(o, "data-c=" + chr(34) + o["uid"] + chr(34))}>'
            f'<div class="op-body"><div class="meta">{logo(ctx, o["source"])}<span class="who" data-fsrc="{E(o["source"])}" style="font-weight:600;color:var(--fg2)">{E(o["source"])}</span>'
            f'<span class="num">· {quando(o["date"], ctx.adesso)}</span>{"<span class=" + chr(34) + "badge per" + chr(34) + ">Per te</span>" if o.get("per_te") else ""}</div>'
            f'<a class="t" href="{E(o["link"])}">{E(o["title"])}</a>' + (f"<p>{E(s)}</p>" if s else "") + "</div>"
            f'{miniatura(o.get("image"), o["link"], True)}{azioni()}</article>')


def dossier_html(ctx, s):
    refs = s["refs"]
    link = refs[0]["link"] if refs else (s["ops"][0]["link"] if s["ops"] else "")
    fonti = list(dict.fromkeys(r["source"] for r in refs))
    titolo = f'<a href="{E(link)}">{E(s["titolo"])}</a>' if link else E(s["titolo"])
    chips = "".join(f'<a class="schip" href="{E(r["link"])}">{logo(ctx, r["source"])}{E(r["source"])}</a>'
                    for r in {r["source"]: r for r in refs}.values())
    ora = quando(min(r["date"] for r in refs), ctx.adesso) if refs else ""
    testo_cerca = " ".join([s["titolo"], s["testo"], *fonti])
    thread = ""
    if s["ops"]:
        thread = (f'<div class="thread"><div class="thread-h">Cosa ne dicono <b>{len(s["ops"])}</b></div>'
                  + "".join(op_html(ctx, o) for o in s["ops"]) + "</div>")
    uids = " ".join(r["uid"] for r in refs)
    return (f'<article class="dossier rv" id="{s["id"]}" data-link="{E(link)}" data-src="{E("|".join(fonti))}" data-n="{uids}" '
            f'data-per="{1 if s.get("per_te") else 0}" data-fonte="{E(fonti[0] if fonti else "")}" data-titolo="{E(s["titolo"])}" '
            f'data-text="{E(testo_cerca)}"><div class="fact"><div class="fact-body"><div class="meta">'
            f'<span class="badge f">Fatto</span>{"<span class=" + chr(34) + "badge per" + chr(34) + ">Per te</span>" if s.get("per_te") else ""}'
            f'<span class="stack">{"".join(logo(ctx, f) for f in fonti[:4])}</span><span class="num">{ora}</span></div>'
            f'<h3>{titolo}</h3>' + (f'<p class="txt">{E(s["testo"])}</p>' if s["testo"] else "")
            + (f'<div class="chips">{chips}</div>' if chips else "") + f'</div>{miniatura(s["image"], link)}</div>{azioni() if link else ""}{thread}</article>')


def oth_li(ctx, s):
    r = s["refs"][0] if s["refs"] else None
    if not r:
        return ""
    return (f'<li class="rv" data-link="{E(r["link"])}" data-src="{E(r["source"])}" data-n="{r["uid"]}" data-fonte="{E(r["source"])}" '
            f'data-titolo="{E(s["titolo"])}" data-per="0">{logo(ctx, r["source"])}<div><span class="sn">{E(r["source"])} · {quando(r["date"], ctx.adesso)}</span>'
            f'<a href="{E(r["link"])}">{E(s["titolo"])}</a></div>{azioni()}</li>')


# ---------- pagina ----------

def ordina_argomenti(ctx, per_argomento, libere):
    nomi = list(dict.fromkeys(s["topic"] for s in ctx.comp.storie))
    nomi += [t for t in libere if t not in nomi]
    if not ctx.comp.con_ai:
        peso = lambda t: sum(1 + len(s["ops"]) for s in per_argomento.get(t, []) if not s["minor"]) + len(libere.get(t, []))  # noqa: E731
        nomi.sort(key=lambda t: (t == "Altro", -peso(t)))
        for t in per_argomento:  # prima i fatti con opinioni e con foto
            per_argomento[t].sort(key=lambda s: (-len(s["ops"]), not s["image"], not s["testo"]))
    else:
        nomi = [t for t in nomi if t != "Altro"] + [t for t in nomi if t == "Altro"]
    return nomi


def pagina(ctx: Contesto):
    comp = ctx.comp
    collegate = {id(o) for s in comp.storie for o in s["ops"]}
    libere = {}
    for c in ctx.contenuti:
        if id(c) not in collegate:
            libere.setdefault(c.get("topic") or "Altro", []).append(c)
    per_argomento = {}
    for s in comp.storie:
        per_argomento.setdefault(s["topic"], []).append(s)
    nomi = ordina_argomenti(ctx, per_argomento, libere)

    apertura = None
    for t in nomi:
        pool = [s for s in per_argomento.get(t, []) if not s["minor"]]
        if pool:
            apertura = pool[0] if comp.con_ai else max(pool[:5], key=lambda s: (bool(s["image"]), len(s["ops"]), len(s["testo"])))
            break

    conteggio = lambda t: len(per_argomento.get(t, [])) + len(libere.get(t, []))  # noqa: E731
    conta_fonti = {}
    for it in ctx.notizie + ctx.contenuti:
        conta_fonti[it["source"]] = conta_fonti.get(it["source"], 0) + 1
    attive = sum(1 for f in ctx.fonti if conta_fonti.get(f.nome))
    n_fatti = sum(1 for s in comp.storie if not s["minor"])
    a = ctx.adesso.astimezone()
    data_txt = f"{GIORNI[a.weekday()]} {a.day} {MESI[a.month - 1]}"
    ha_per_te = any(s.get("per_te") for s in comp.storie) or any(c.get("per_te") for c in ctx.contenuti)

    cfg = {"repo": ctx.repo, "edizione": a.strftime("%Y-%m-%d"),
           "tendenze": {f"t{i}": t["uids"] for i, t in enumerate(comp.tendenze)}}

    # --- barra, presentazione, filtri
    nav = (f'<header class="nav"><div class="wrap nav-in"><a class="brand" href="__BASE__"><span class="mark">R</span><span>La Rassegna</span></a>'
           f'<label class="search">{ICONE["cerca"]}<input id="q" type="search" placeholder="Cerca nelle uscite di oggi…" autocomplete="off"><kbd>/</kbd></label>'
           f'<nav class="links"><a href="#fonti">Fonti</a><a href="#consigli">Consigli</a><a href="__ARCHIVIO__">Archivio</a></nav></div></header>')
    tendenze = ""
    if comp.tendenze:
        tendenze = ('<div class="trends"><span class="lbl">Di cosa si parla</span>' + "".join(
            f'<button class="trend" data-trend="t{i}">{E(t["titolo"])}<i>{len(t["uids"])}</i></button>' for i, t in enumerate(comp.tendenze)) + "</div>")
    hero = (f'<section class="hero"><div class="wrap hero-in"><div><span class="pill"><span class="dot"></span>Edizione di {E(data_txt)} · aggiornata alle {a:%H:%M}</span>'
            f'<h1>Buongiorno. Ecco <em>cosa conta</em> oggi.</h1><p class="lede">{E(comp.editoriale or "")}</p>{tendenze}</div>'
            f'<div class="stats"><div class="stat"><b class="num">{len(ctx.notizie) + len(ctx.contenuti)}</b><span>uscite nelle ultime {ctx.ore} ore</span></div>'
            f'<div class="stat"><b class="num">{attive}<small style="font-size:16px;color:var(--mut2);font-weight:600">/{len(ctx.fonti)}</small></b><span>fonti con novità</span></div>'
            f'<div class="stat f"><b class="num">{n_fatti}</b><span>fatti ricostruiti</span></div>'
            f'<div class="stat o"><b class="num">{len(ctx.contenuti)}</b><span>opinioni e analisi</span></div></div></div></section>')

    gruppi = {"Notizie": [f for f in ctx.fonti if f.ruolo == "notizie"], "Approfondimenti": [f for f in ctx.fonti if f.ruolo != "notizie"]}
    menu = ""
    for g, fs in gruppi.items():
        if fs:
            menu += f"<h6>{g}</h6>" + "".join(
                f'<button data-fsrc-btn="{E(f.nome)}" aria-pressed="false"{"" if conta_fonti.get(f.nome) else " disabled"}>{logo(ctx, f.nome)}{E(f.nome)}<i>{conta_fonti.get(f.nome, 0)}</i></button>' for f in fs)
    barra = ('<div class="bar"><div class="wrap"><div class="bar-in"><div class="tabs">'
             '<button class="tab" data-tema="" aria-pressed="true">Tutti i temi</button>'
             + "".join(f'<button class="tab" data-tema="{E(t)}" aria-pressed="false">{E(t)}<i>{conteggio(t)}</i></button>' for t in nomi)
             + '</div><div class="ctrls"><div class="pop"><button class="btn" id="btn-fonti">Fonte: <b id="fonte-lbl" style="font-weight:600">Tutte le fonti</b> ▾</button>'
             f'<div class="menu" hidden>{menu}</div></div>'
             '<div class="seg"><button data-kind="all" aria-pressed="true">Tutto</button><button data-kind="fatti" aria-pressed="false">Fatti</button>'
             '<button data-kind="opinioni" aria-pressed="false">Opinioni</button></div>'
             + ('<button class="toggle" data-toggle="per" aria-pressed="false">★ Per te</button>' if ha_per_te else '<button class="toggle" data-toggle="per" hidden></button>')
             + '<button class="toggle" data-toggle="saved" aria-pressed="false">Salvati <span class="n" id="n-salvati"></span></button>'
             '<button class="btn" id="invia-pref" hidden>Invia <span>0</span> preferenze</button><button class="reset" hidden>Azzera</button></div></div>'
             '<div class="stato-filtri" hidden></div></div></div>')

    # --- corpo
    corpo = []
    if apertura:
        corpo.append(f'<div class="lead" data-topic="{E(apertura["topic"])}"><div class="eyebrow">Apertura · {E(apertura["topic"])}</div>{dossier_html(ctx, apertura)}</div>')
    for t in nomi:
        sl = [s for s in per_argomento.get(t, []) if s is not apertura]
        maggiori = [s for s in sl if not s["minor"]]
        minori = [s for s in sl if s["minor"]]
        mostrati, compatti = maggiori[:PER_ARGOMENTO], maggiori[PER_ARGOMENTO:] + minori
        fr = sorted(libere.get(t, []), key=lambda o: o["date"], reverse=True)
        n_op = len(fr) + sum(len(s["ops"]) for s in sl)
        parti = [f'<div class="sez-h"><h2>{E(t)}</h2><span class="cnt"><b class="f">{len(sl)} {"fatto" if len(sl) == 1 else "fatti"}</b>'
                 f'<b class="o">{n_op} {"opinione" if n_op == 1 else "opinioni"}</b></span></div>']
        if mostrati:
            parti.append('<div class="grid">' + "".join(dossier_html(ctx, s) for s in mostrati) + "</div>")
        if fr:
            parti.append(f'<div class="sub"><div class="sub-h o">Idee e approfondimenti su questo tema <b>· {len(fr)}</b></div>'
                         f'<div class="fcards">{"".join(fcard_html(ctx, o) for o in fr)}</div></div>')
        if compatti:
            parti.append(f'<div class="sub"><div class="sub-h f">Altre notizie <b>· {len(compatti)}</b></div><ul class="oth">{"".join(oth_li(ctx, s) for s in compatti)}</ul></div>')
        corpo.append(f'<section class="sez" data-topic="{E(t)}">{"".join(parti)}</section>')
    if not nomi:
        corpo.append('<div class="vuoto">Nessuna uscita nelle ultime ore.</div>')
    corpo.append('<div class="vuoto" id="vuoto" hidden>Nessuna voce corrisponde ai filtri scelti. <button class="reset" style="font-size:14px">Azzera i filtri</button></div>')

    # --- fonti consigliate
    if ctx.suggerimenti:
        card = ""
        for sg in ctx.suggerimenti:
            ultime = "".join(f'<li><a href="{E(x["link"])}">{E(accorcia(x["titolo"], 80))}</a></li>' for x in sg.get("esempi", [])[:2])
            riga = f'{sg["nome"]} = {sg["feed"]}'
            card += (f'<article class="sugg rv" data-dominio="{E(sg["dominio"])}"><div class="sugg-top">{logo(ctx, sg["nome"], "xl")}<div><b>{E(sg["nome"])}</b>'
                     f'<span>{E(sg["dominio"])}{" · " + E(sg["tema"]) if sg.get("tema") else ""}</span></div></div><p>{E(sg.get("perche", ""))}</p>'
                     f'{"<ul>" + ultime + "</ul>" if ultime else ""}<div class="sugg-act"><button class="btn-p" data-copia="{E(riga)}">Aggiungi</button>'
                     f'<a class="btn-g" style="display:inline-grid;place-items:center" href="{E(sg["url"])}">Visita</a><button class="btn-g" data-no-sugg title="Non riproporre questa fonte">Nascondi</button></div></article>')
        corpo.append(f'<section class="sez" id="consigli" style="scroll-margin-top:90px"><div class="sez-h"><h2>Fonti nuove da provare</h2>'
                     f'<span class="sn">Scelte in base ai tuoi interessi e alle fonti già seguite · verificate attive</span></div><div class="sugg-grid">{card}</div></section>')

    # --- stato delle fonti
    schede = ""
    esiti = {e.fonte.nome: e for e in ctx.esiti}
    for f in ctx.fonti:
        e = esiti.get(f.nome)
        stato = "bad" if (e and not e.ok) else ("warn" if e and e.degradato else "")
        via = {"feed": "feed diretto", "alternativa": "feed alternativo", "wp-json": "API del sito", "pagina": "lettura della pagina", "google-news": "via Google News"}.get(e.metodo if e else "", "non raggiungibile")
        n = conta_fonti.get(f.nome, 0)
        schede += (f'<button class="fonte" data-fsrc="{E(f.nome)}">{logo(ctx, f.nome, "xl")}<div><b>{E(f.nome)}</b>'
                   f'<span>{n} {"uscita" if n == 1 else "uscite"} · {via}</span></div><span class="st stato-dot {stato}" title="{via}"></span></button>')
    corpo.append(f'<section class="sez" id="fonti" style="scroll-margin-top:90px"><div class="sez-h"><h2>Le tue fonti</h2>'
                 f'<span class="sn">Clicca una fonte per vedere solo le sue uscite</span></div><div class="fonti-grid">{schede}</div></section>')

    # --- indice completo
    gr = {}
    ar_topic = {id(r): s["topic"] for s in comp.storie for r in s["refs"]}
    for i in ctx.notizie:
        gr.setdefault((i["source"], "n"), []).append(i)
    for i in ctx.contenuti:
        gr.setdefault((i["source"], "p"), []).append(i)
    det = []
    for (src, k), its in sorted(gr.items(), key=lambda kv: (kv[0][1] != "n", kv[0][0].lower())):
        li = "".join(f'<li class="{k}" data-link="{E(i["link"])}" data-topic="{E(ar_topic.get(id(i)) or i.get("topic") or "Altro")}"><span class="num">{quando(i["date"], ctx.adesso)}</span>'
                     f'<a href="{E(i["link"])}">{E(i["title"])}</a></li>' for i in sorted(its, key=lambda i: i["date"], reverse=True))
        det.append(f'<details data-src="{E(src)}"><summary>{logo(ctx, src)}{E(src)} <i>· {len(its)}</i></summary><ul>{li}</ul></details>')
    corpo.append(f'<section class="sez full" id="indice"><div class="sez-h"><h2>Indice completo</h2><span class="sn">{len(ctx.notizie) + len(ctx.contenuti)} uscite · nessuna esclusa</span></div>{"".join(det)}</section>')

    if ctx.avvisi:
        corpo.append('<div class="avvisi">' + "<br>".join(ctx.avvisi) + "</div>")
    corpo.append(f'<footer class="foot"><span>Generata il {a:%d/%m/%Y} alle {a:%H:%M}</span><a href="__ARCHIVIO__">Edizioni precedenti</a>'
                 f'<a href="https://github.com/{E(ctx.repo)}/edit/main/sources.txt">Modifica le fonti</a>'
                 f'<a href="https://github.com/{E(ctx.repo)}/edit/main/interessi.txt">Modifica i tuoi interessi</a>'
                 f'<span>{"Sintesi con AI" if comp.con_ai else "Senza AI"}</span></footer>')

    css = (RADICE / "assets" / "stile.css").read_text(encoding="utf-8")
    js = (RADICE / "assets" / "app.js").read_text(encoding="utf-8")
    return (f'<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>La Rassegna — {a:%d/%m/%Y}</title><meta name="color-scheme" content="light">'
            '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap">'
            f'<style>{css}</style></head><body>{nav}{hero}{barra}<main class="wrap">{"".join(corpo)}</main><div class="toast" role="status"></div>'
            f'<script>window.RASSEGNA={json.dumps(cfg, ensure_ascii=False)};</script><script>{js}</script></body></html>')
