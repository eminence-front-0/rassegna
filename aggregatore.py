#!/usr/bin/env python3
"""La Rassegna: legge le tue fonti, compone fatti e opinioni, scrive docs/index.html e conserva l'edizione.

  python3 aggregatore.py                 prova locale (non modifica la memoria tra un giorno e l'altro)
  RASSEGNA_STATO=1 python3 aggregatore.py   esecuzione ufficiale (usata da GitHub Actions)
  --consigli       forza la ricerca di nuove fonti   --senza-immagini   salta le anteprime
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

from rassegna import archivio, composizione, config, feedback, fonti, immagini, loghi, parsers, render, stato as memoria, suggerimenti
from rassegna.parsers import ROMA

RADICE = config.RADICE
ORE = int(os.environ.get("ORE", "24"))
REPO = os.environ.get("GITHUB_REPOSITORY", "eminence-front-0/rassegna")


def raccogli_voci(esiti, stato, adesso, oggi, scartate=None):
    """Applica la finestra temporale e la memoria: nessuna uscita persa, nessuna ripetuta.
    `scartate` raccoglie le uscite senza data che non mostriamo ma che vanno ricordate come già viste."""
    ha_storia = bool(stato["ultima_esecuzione"])
    inizio = adesso - timedelta(hours=ORE)
    if ha_storia:  # si parte dall'ultima esecuzione (con un margine), così un giorno saltato viene recuperato ma l'arretrato non esplode
        ultima = datetime.fromisoformat(stato["ultima_esecuzione"])
        inizio = max(adesso - timedelta(hours=72), min(inizio, ultima - timedelta(hours=6)))
    viste, voci = set(), []
    for e in esiti:
        prima_volta = not stato.get("salute", {}).get(e.fonte.nome, {}).get("ultimo_ok")
        incerte = 0
        for v in e.voci:
            if v.get("data_incerta"):
                # fonti che non dichiarano la data: all'inizio solo le prime dell'elenco (le più recenti), poi solo le nuove
                incerte += 1
                if incerte > (3 if prima_volta else 8):
                    if scartate is not None:
                        scartate.append(v["link"])
                    continue
            if v["date"] > adesso + timedelta(hours=6) or v["date"] < inizio:
                continue
            if ha_storia:
                prima = stato["visti"].get(v["link"])
                if prima and prima != oggi:
                    continue  # già comparso in un'edizione precedente
            chiave = (v["source"], v["title"].lower())
            if v["link"] in viste or chiave in viste:
                continue
            viste.update([v["link"], chiave])
            voci.append(v)
    voci.sort(key=lambda v: v["date"], reverse=True)
    return voci


def avvisi_fonti(esiti, stato):
    out = []
    nomi = {"google-news": "Google News", "pagina": "la lettura diretta delle pagine", "wp-json": "l'API del sito", "alternativa": "un indirizzo alternativo"}
    for e in esiti:
        n = stato["salute"].get(e.fonte.nome, {}).get("fallimenti", 0)
        if not e.ok:
            out.append(f"<b>{e.fonte.nome}</b> non raggiungibile ({'; '.join(e.errori[-2:])[:160]}). "
                       f"Le sue uscite di oggi potrebbero mancare{f' · {n} giorni di fila' if n > 1 else ''}.")
        elif e.metodo in ("google-news", "pagina"):
            out.append(f"<b>{e.fonte.nome}</b> è letta tramite {nomi[e.metodo]}: copre le uscite principali ma potrebbe essere meno completa.")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--consigli", action="store_true")
    ap.add_argument("--senza-immagini", action="store_true")
    args = ap.parse_args()
    adesso = datetime.now(ROMA)
    oggi = adesso.strftime("%Y-%m-%d")
    persisti = os.environ.get("RASSEGNA_STATO") == "1"

    elenco, argomenti = config.leggi_fonti()
    interessi = config.leggi_interessi()
    stato = memoria.carica()
    nuove_pref = feedback.raccogli(stato, oggi)
    if nuove_pref:
        print(f"  preferenze nuove: {nuove_pref}")

    esiti = fonti.scarica_tutte(elenco, visti=frozenset(l for l, d in stato["visti"].items() if d != oggi))
    scartate = []
    voci = raccogli_voci(esiti, stato, adesso, oggi, scartate)
    if not voci and any(not e.ok for e in esiti):
        print("Nessuna uscita e alcune fonti irraggiungibili: non sostituisco la pagina esistente.", file=sys.stderr)
        for e in esiti:
            if not e.ok:
                print(f"  ! {e.fonte.nome}: {'; '.join(e.errori)}", file=sys.stderr)
        sys.exit(2)
    if not args.senza_immagini and not os.environ.get("NO_IMAGES"):
        immagini.completa(voci)
    notizie = [v for v in voci if v["role"] == "notizie"]
    contenuti = [v for v in voci if v["role"] != "notizie"]

    comp = composizione.componi(notizie, contenuti, argomenti, interessi, feedback.riassunto(stato))

    if args.consigli or suggerimenti.da_aggiornare(stato):
        try:
            stato["suggerimenti"] = suggerimenti.genera(voci, elenco, interessi, argomenti, stato["scartati"])
        except Exception as ex:  # noqa: BLE001  i consigli sono un extra: non bloccano mai l'edizione
            print(f"  consigli non generati: {type(ex).__name__}: {ex}", file=sys.stderr)
    sugg = [s for s in (stato["suggerimenti"] or {}).get("elenco", []) if s["dominio"] not in stato["scartati"]]

    conteggi = {}
    for v in voci:
        conteggi[v["source"]] = conteggi.get(v["source"], 0) + 1
    memoria.aggiorna_salute(stato, esiti, conteggi, adesso)

    mappa_loghi = loghi.assicura_loghi([(f.nome, f.dominio) for f in elenco] + [(s["nome"], s["dominio"]) for s in sugg])
    avvisi = avvisi_fonti(esiti, stato) + ([comp.nota] if comp.nota else [])
    ctx = render.Contesto(adesso=adesso, notizie=notizie, contenuti=contenuti, comp=comp, argomenti=argomenti, esiti=esiti, fonti=elenco,
                          loghi=mappa_loghi, suggerimenti=sugg, repo=REPO, ore=ORE, avvisi=avvisi)
    if os.environ.get("RASSEGNA_DUMP"):  # strumento per chi sviluppa: salva i dati per rifare solo la grafica
        import pickle
        with open(os.environ["RASSEGNA_DUMP"], "wb") as fh:
            pickle.dump(ctx, fh)
    pagina = render.pagina(ctx)
    (RADICE / "docs").mkdir(exist_ok=True)
    (RADICE / "docs" / "index.html").write_text(pagina.replace("__BASE__", "").replace("__ARCHIVIO__", "archivio/"), encoding="utf-8")
    archivio.salva(pagina, adesso)

    if persisti:
        for v in voci:
            stato["visti"].setdefault(v["link"], oggi)
        for link in scartate:
            stato["visti"].setdefault(link, oggi)
        stato["ultima_esecuzione"] = adesso.isoformat()
        memoria.salva(stato, oggi)

    metodi = {}
    for e in esiti:
        metodi[e.metodo or "NESSUNA"] = metodi.get(e.metodo or "NESSUNA", 0) + 1
    print(f"{len(notizie)} notizie, {len(contenuti)} contenuti, {sum(1 for v in voci if v.get('image'))} con foto · vie: {metodi}")
    for a in avvisi:
        print("  *", a.replace("<b>", "").replace("</b>", ""), file=sys.stderr)


if __name__ == "__main__":
    main()
