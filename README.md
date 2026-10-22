# La Rassegna

Quattro volte al giorno (08:00, 13:00, 18:00, 23:00, ora italiana) legge le tue fonti e aggiorna una pagina: **i fatti** (in blu), **le opinioni che li commentano** (in arancio), divisi per argomento, con le fonti nuove da provare.

Pagina: <https://eminence-front-0.github.io/rassegna/> · Archivio: `/archivio/`

## Cosa puoi modificare (senza programmare)
| File | A cosa serve |
|---|---|
| `sources.txt` | le tue fonti: una riga per fonte, `Nome = indirizzo` (basta l'indirizzo del sito se non ha un feed) |
| `interessi.txt` | cosa ti interessa e cosa no: guida «Per te» e le fonti consigliate |

Dalla pagina puoi anche segnare 👍/👎, salvare per dopo, filtrare per tema/fonte/tipo e cercare con `/`.
Il pulsante «Invia preferenze» apre una segnalazione GitHub già compilata: premi *Submit*, e l'edizione successiva la legge.

## Come tratta gli errori (403, 500, testo extra, feed rotti…)
Ogni fonte viene letta con una cascata di vie, e la pagina ti dice quale ha funzionato:
1. il suo feed, con nuovi tentativi a pause crescenti · 2. un indirizzo alternativo (`| alternativa:`) ·
3. l'API di WordPress del sito · 4. la lettura diretta delle pagine (siti senza feed) · 5. Google News, con i link tradotti in indirizzi reali.

- `404` → inutile riprovare, si passa alla via successiva · `403/429/503` → altra impronta di connessione (curl) e poi via successiva ·
  `500`/timeout → nuovi tentativi · certificati mancanti (macOS) → certificati di sistema.
- Feed con HTML o testo dopo la fine, spazi iniziali, caratteri letti male, indirizzi con accenti: ripuliti automaticamente.
- **Memoria** (`data/stato.json`): un'uscita che sfugge un giorno (fonte giù, esecuzione saltata) viene recuperata il giorno dopo; una già mostrata non si ripete.
- Una fonte rotta non ferma le altre; l'AI che non risponde non ferma la pagina; se non esce nulla e ci sono errori, **la pagina esistente non viene sostituita** e GitHub ti manda un'email.
- Ogni errore incontrato in passato ha un test in `tests/` (`python3 -m unittest discover -s tests`).

## Struttura
`aggregatore.py` (regia) · `rassegna/` (rete, parser, fonti, Google News, composizione, AI, consigli, preferenze, pagina, archivio) · `assets/` (stile e script) · `docs/` (pagina pubblicata) · `data/` (memoria)
