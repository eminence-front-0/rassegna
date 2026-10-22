"""Loghi delle testate: scaricati una volta sola in docs/logos/ e riusati ogni giorno."""
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

from . import parsers, rete
from .config import RADICE

CARTELLA = RADICE / "docs" / "logos"
FIRME = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpg", b"GIF8": "gif", b"RIFF": "webp", b"\x00\x00\x01\x00": "ico"}


def slug(testo):
    return re.sub(r"[^a-z0-9]+", "-", testo.lower()).strip("-") or "x"


def estensione(dati):
    if dati.lstrip()[:5].lower() in (b"<?xml", b"<svg ") or b"<svg" in dati[:300].lower():
        return "svg"
    return next((e for f, e in FIRME.items() if dati.startswith(f)), None)


def percorso_esistente(nome):
    return next(iter(sorted(CARTELLA.glob(slug(nome) + ".*"))), None)


def _scegli_icona(pagina, base):
    migliori = []
    for tag in re.findall(r"<link\s[^>]*>", pagina, re.I):
        a = parsers.attributi(tag)
        rel = a.get("rel", "").lower()
        if "icon" not in rel or not a.get("href"):
            continue
        m = re.search(r"(\d+)x\d+", a.get("sizes", ""))
        dim = int(m.group(1)) if m else (180 if "apple" in rel else 32)
        if a["href"].lower().endswith((".ico", ".svg")) and "apple" not in rel:
            dim = min(dim, 31)
        migliori.append((dim, urljoin(base, a["href"])))
    migliori.sort(reverse=True)
    return [u for d, u in migliori if d >= 32][:2]


def _scarica_logo(nome_dominio):
    nome, dominio = nome_dominio
    if percorso_esistente(nome):
        return nome, True
    candidati = []
    try:
        pagina = rete.scarica_testo(f"https://{dominio}/", timeout=10, tentativi=2)
        candidati += _scegli_icona(pagina, f"https://{dominio}/")
    except rete.ErroreRete:
        pass
    candidati.append(f"https://www.google.com/s2/favicons?domain={dominio}&sz=128")
    for url in candidati:
        try:
            dati = rete.scarica(url, timeout=10, tentativi=2)
        except rete.ErroreRete:
            continue
        ext = estensione(dati)
        if ext and 80 < len(dati) < 600_000:
            CARTELLA.mkdir(parents=True, exist_ok=True)
            (CARTELLA / f"{slug(nome)}.{ext}").write_bytes(dati)
            return nome, True
    return nome, False


def assicura_loghi(coppie):
    """coppie: [(nome, dominio)]. Scarica i loghi mancanti; ritorna {nome: nome file o None}."""
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(_scarica_logo, list(dict(coppie).items())))
    return {nome: (percorso_esistente(nome).name if percorso_esistente(nome) else None) for nome, _ in coppie}
