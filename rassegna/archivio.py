"""Archivio delle edizioni: ogni giorno la pagina viene conservata in docs/archivio/ con un indice."""
from datetime import datetime

from .config import RADICE
from .render import FAVICON, GIORNI, MESI

DOCS = RADICE / "docs"

CSS = """*{box-sizing:border-box}body{margin:0;background:#fff;color:#09090b;font:15px/1.55 Inter,ui-sans-serif,-apple-system,system-ui,sans-serif;-webkit-font-smoothing:antialiased;
background:radial-gradient(50% 40% at 10% -10%,rgba(99,102,241,.14),transparent 70%),radial-gradient(40% 40% at 95% 0%,rgba(236,72,153,.1),transparent 70%),#fff}
main{max-width:680px;margin:0 auto;padding:56px 24px 90px}a{color:inherit;text-decoration:none}
.mark{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:9px;background:linear-gradient(135deg,#4f46e5,#7c3aed 55%,#ec4899);color:#fff;font-weight:800;font-size:14px;margin-right:10px;vertical-align:middle}
h1{font-size:34px;letter-spacing:-.035em;margin:18px 0 6px}p{margin:0 0 26px;color:#71717a;font-size:14px}p a{color:#4f46e5;font-weight:600}
ul{list-style:none;padding:0;margin:0;border:1px solid #e4e4e7;border-radius:14px;overflow:hidden;background:#fff;box-shadow:0 1px 2px rgba(9,9,11,.05)}
li+li{border-top:1px solid #f1f1f3}li a{display:flex;justify-content:space-between;padding:14px 18px;font-weight:550;letter-spacing:-.01em;transition:background .15s}
li a:hover{background:#fafafa;color:#4f46e5}li span{color:#a1a1aa;font-weight:400;font-size:13px}"""


def salva(pagina, adesso):
    """Scrive l'edizione di oggi nell'archivio e rigenera l'indice. `pagina` contiene i segnaposto __BASE__ e __ARCHIVIO__."""
    cartella = DOCS / "archivio"
    cartella.mkdir(parents=True, exist_ok=True)
    (cartella / f"{adesso:%Y-%m-%d}.html").write_text(pagina.replace("__BASE__", "../").replace("__ARCHIVIO__", "./"), encoding="utf-8")
    righe = []
    for f in sorted(cartella.glob("????-??-??.html"), reverse=True):
        d = datetime.strptime(f.stem, "%Y-%m-%d")
        righe.append(f'<li><a href="{f.name}">{GIORNI[d.weekday()].capitalize()} {d.day} {MESI[d.month - 1]} {d.year}<span>{d:%d/%m/%Y}</span></a></li>')
    (cartella / "index.html").write_text(
        '<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Edizioni precedenti — La Rassegna</title><meta name="color-scheme" content="light">' + FAVICON +
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap">'
        f'<style>{CSS}</style></head><body><main><a href="../"><span class="mark">R</span><b>La Rassegna</b></a><h1>Edizioni precedenti</h1>'
        f'<p>{len(righe)} edizioni conservate · <a href="../">← Torna all\'ultima edizione</a></p><ul>{"".join(righe)}</ul></main></body></html>',
        encoding="utf-8")
