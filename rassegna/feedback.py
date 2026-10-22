"""Preferenze (👍/👎) inviate dalla pagina come segnalazioni GitHub con etichetta «feedback».
Alla prossima edizione vengono lette, memorizzate in data/stato.json e le segnalazioni si chiudono."""
import json
import os
import re

from . import rete


def _api(percorso, **kw):
    token = os.environ["GITHUB_TOKEN"]
    return rete.scarica("https://api.github.com/repos/" + os.environ["GITHUB_REPOSITORY"] + percorso, tentativi=2, timeout=20,
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "Content-Type": "application/json"}, **kw)


def pulisci(testo, n=80):
    return re.sub(r"[\r\n\t`<>]+", " ", str(testo))[:n].strip()


def raccogli(stato, oggi):
    """Legge le segnalazioni di preferenze aperte. Ritorna quante voci nuove ha trovato."""
    if not (os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY")):
        return 0
    nuove = 0
    try:
        segnalazioni = json.loads(_api("/issues?labels=feedback&state=open&per_page=30"))
    except Exception:  # noqa: BLE001  senza feedback la pagina esce comunque
        return 0
    for s in segnalazioni:
        if "pull_request" in s:
            continue
        m = re.search(r"```json\s*(.*?)```", s.get("body") or "", re.S)
        try:
            voci = json.loads(m.group(1)) if m else []
        except ValueError:
            voci = []
        for v in voci[:50] if isinstance(voci, list) else []:
            if not isinstance(v, dict) or v.get("v") not in (1, -1):
                continue
            voce = {"v": v["v"], "f": pulisci(v.get("f", ""), 60), "t": pulisci(v.get("t", "")), "d": oggi}
            if voce["t"] == "fonte consigliata" and v["v"] == -1:
                if voce["f"] not in stato["scartati"]:
                    stato["scartati"].append(voce["f"])
            else:
                stato["feedback"].append(voce)
            nuove += 1
        try:
            _api(f"/issues/{s['number']}/comments", data=json.dumps({"body": "Preferenze lette: grazie! Le userò per scegliere cosa metterti in evidenza."}).encode())
            _api(f"/issues/{s['number']}", data=json.dumps({"state": "closed"}).encode(), metodo="PATCH")
        except Exception:  # noqa: BLE001
            pass
    return nuove


def riassunto(stato, massimo=25):
    """Testo breve per orientare l'AI: cosa ti è piaciuto e cosa no di recente."""
    su = [f"{v['f']}: «{v['t']}»" for v in stato["feedback"] if v["v"] == 1][-massimo:]
    giu = [f"{v['f']}: «{v['t']}»" for v in stato["feedback"] if v["v"] == -1][-massimo:]
    if not (su or giu):
        return ""
    return "👍 " + "; ".join(su) + "\n👎 " + "; ".join(giu)
