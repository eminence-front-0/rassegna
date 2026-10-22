"""Accesso alla rete robusto: tentativi, pause crescenti e vie di ripiego.

Ogni errore ha una causa diversa e una risposta diversa:
  404/410           la pagina non esiste: inutile riprovare, si passa subito alla via successiva
  403/429/503       il sito ci blocca: si riprova con un'altra "impronta" di connessione (curl)
  500/timeout       guasto passeggero: si riprova con pause crescenti
  certificati       problema del computer (macOS): si usano i certificati di sistema
"""
import json
import random
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SYSTEM_CA = "/etc/ssl/cert.pem"


class ErroreRete(Exception):
    def __init__(self, messaggio, codice=None, permanente=False):
        super().__init__(messaggio)
        self.codice = codice
        self.permanente = permanente


def normalizza(url):
    """Indirizzo con soli caratteri ASCII (accenti e simboli codificati): i server vogliono questo."""
    u = urllib.parse.urlsplit(url.strip())
    try:
        host = u.netloc.encode("idna").decode("ascii")
    except UnicodeError:
        host = urllib.parse.quote(u.netloc)
    sicuri = "/:@!$&'()*+,;=%-._~"
    return urllib.parse.urlunsplit((u.scheme, host, urllib.parse.quote(u.path, safe=sicuri),
                                    urllib.parse.quote(u.query, safe=sicuri + "?"), ""))


def _intestazioni(extra=None):
    h = {"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
         "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8"}
    h.update(extra or {})
    return h


def _urllib(url, timeout, headers, data=None, metodo=None):
    req = urllib.request.Request(url, data=data, headers=_intestazioni(headers), method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e) and Path(SYSTEM_CA).exists():
            ctx = ssl.create_default_context(cafile=SYSTEM_CA)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return r.read()
        raise


def _curl(url, timeout, headers, data=None, metodo=None):
    cmd = ["curl", "-sSL", "--max-time", str(timeout), "-w", "\n%{http_code}"]
    if metodo:
        cmd += ["-X", metodo]
    for k, v in _intestazioni(headers).items():
        cmd += ["-H", f"{k}: {v}"]
    if data is not None:
        cmd += ["--data-binary", "@-"]
    out = subprocess.run(cmd + [url], input=data, capture_output=True)
    if out.returncode != 0:
        raise ErroreRete(f"curl: {out.stderr.decode('utf-8', 'ignore').strip()[:120] or out.returncode}")
    body, _, code = out.stdout.rpartition(b"\n")
    code = int(code or 0)
    if code >= 400:
        raise ErroreRete(f"HTTP {code}", codice=code, permanente=code in (404, 410))
    return body


def scarica(url, timeout=20, tentativi=4, headers=None, data=None, metodo=None, ripiego=True):
    """Scarica un indirizzo e ritorna i byte. Solleva ErroreRete se non riesce.
    ripiego=False: per le API, dove riprovare con un altro metodo non serve e peggiora i limiti di richieste."""
    url = normalizza(url)
    ultimo = None
    for n in range(tentativi):
        try:
            return _urllib(url, timeout, headers, data, metodo)
        except urllib.error.HTTPError as e:
            try:
                corpo = e.read().decode("utf-8", "ignore")[:220].replace("\n", " ")
            except Exception:  # noqa: BLE001
                corpo = ""
            ultimo = ErroreRete(f"HTTP {e.code}" + (f": {corpo}" if corpo and not ripiego else ""), codice=e.code, permanente=e.code in (404, 410))
            if ultimo.permanente or not ripiego:
                raise ultimo
            if e.code in (401, 403, 429, 503):  # blocco: un'altra impronta di connessione può passare
                try:
                    return _curl(url, timeout, headers, data, metodo)
                except ErroreRete as e2:
                    ultimo = e2
                    if e.code in (401, 403):  # un blocco fisso non si risolve riprovando
                        raise ultimo
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError, UnicodeError) as e:
            ultimo = ErroreRete(f"{type(e).__name__}: {str(e)[:100]}")
            try:
                return _curl(url, timeout, headers, data, metodo)
            except ErroreRete as e2:
                ultimo = e2
                if e2.permanente:
                    raise
        if n < tentativi - 1:
            time.sleep(min(1.5 * 2 ** n, 10) + random.random())
    raise ultimo or ErroreRete("errore sconosciuto")


def scarica_testo(url, **kw):
    return scarica(url, **kw).decode("utf-8", "ignore")


def scarica_json(url, **kw):
    return json.loads(scarica(url, **kw))
