"""Test offline: ogni errore incontrato in passato ha qui il suo caso, così non può tornare.
Esecuzione:  python3 -m unittest discover -s tests -v"""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rassegna import composizione, ia, parsers, rete  # noqa: E402

RSS = b"""<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"
 xmlns:media="http://search.yahoo.com/mrss/"><channel><title>Sito</title>
<item><title>Primo articolo</title><link>https://sito.it/a/primo</link><pubDate>Wed, 21 Oct 2026 08:00:00 GMT</pubDate>
<description>Testo del primo. L'articolo Primo proviene da Sito.</description><media:thumbnail url="https://sito.it/img/foto.jpg"/></item>
<item><title>Secondo &amp; ultimo</title><link>https://sito.it/a/secondo</link><pubDate>Tue, 20 Oct 2026 08:00:00 GMT</pubDate>
<content:encoded><![CDATA[<p>Vedi <a href="https://altro.org/x">altro</a></p><img src="https://sito.it/img/b.png">]]></content:encoded></item>
</channel></rss>"""


class TestRete(unittest.TestCase):
    def test_indirizzi_con_accenti(self):  # errore: UnicodeEncodeError su un'icona con lettera accentata
        self.assertEqual(rete.normalizza("https://sito.it/ícona/ùno.png?x=è"), "https://sito.it/%C3%ADcona/%C3%B9no.png?x=%C3%A8")

    def test_indirizzo_gia_valido(self):
        u = "https://www.sito.it/a/b?x=1&y=2"
        self.assertEqual(rete.normalizza(u), u)


class TestFeed(unittest.TestCase):
    def test_rss_base(self):
        v = parsers.leggi_feed(RSS)
        self.assertEqual(len(v), 2)
        self.assertEqual(v[0]["title"], "Primo articolo")
        self.assertEqual(v[0]["image"], "https://sito.it/img/foto.jpg")
        self.assertNotIn("proviene da", v[0]["text"])  # frase standard di WordPress rimossa
        self.assertEqual(v[1]["title"], "Secondo & ultimo")
        self.assertEqual(v[1]["image"], "https://sito.it/img/b.png")
        self.assertIn("https://altro.org/x", v[1]["links"])

    def test_testo_dopo_il_feed(self):  # errore: «junk after document element» (Le Grand Continent)
        self.assertEqual(len(parsers.leggi_feed(RSS + b"\n<html><body>junk</body></html>")), 2)

    def test_html_sporco_nel_feed(self):  # errore: «mismatched tag» per <link rel=preload> dentro il feed
        sporco = RSS.replace(b"<channel>", b'<channel><link rel="preload" href="/f.woff2" as="font" crossorigin>')
        self.assertEqual(len(parsers.leggi_feed(sporco)), 2)

    def test_spazi_prima_dell_xml(self):  # errore: «XML declaration not at start» (podcast Il Post)
        self.assertEqual(len(parsers.leggi_feed(b"\n\n  " + RSS)), 2)

    def test_riconosce_pagine_html(self):
        self.assertFalse(parsers.e_feed(b"<!DOCTYPE html><html><head></head></html>"))
        self.assertTrue(parsers.e_feed(RSS))

    def test_wordpress_json(self):  # soluzione per i feed rotti (Pandora Rivista)
        dati = json.dumps([{"date_gmt": "2026-10-21T19:10:09", "link": "https://s.it/p/1", "title": {"rendered": "Titolo &#8217;x"},
                            "excerpt": {"rendered": "<p>Riassunto</p>"}, "content": {"rendered": ""},
                            "_embedded": {"wp:featuredmedia": [{"source_url": "https://s.it/i.jpg"}]}}]).encode()
        v = parsers.leggi_feed(dati)
        self.assertEqual(v[0]["title"], "Titolo ’x")
        self.assertEqual(v[0]["image"], "https://s.it/i.jpg")
        self.assertEqual(v[0]["date"].astimezone(timezone.utc).hour, 19)

    def test_archivio_mailchimp(self):  # Areale: lo script restituisce document.write("...")
        js = ('document.write("<div class=\\"display_archive\\"><div class=\\"campaign\\">17\\/10\\/2026 - <a href=\\"https:\\/\\/x.campaign-archive.com\\/?u=1&id=2\\" '
              'title=\\"T\\" target=\\"_blank\\">A cosa serve lo sciopero<\\/a><\\/div><\\/div>");').encode()
        self.assertTrue(parsers.e_feed(js))
        v = parsers.leggi_feed(js)
        self.assertEqual((v[0]["title"], v[0]["date"].day, v[0]["date"].month), ("A cosa serve lo sciopero", 17, 10))


class TestTesto(unittest.TestCase):
    def test_caratteri_letti_male(self):  # errore: «Â«stabilitÃ Â»» (Limes)
        self.assertEqual(parsers.pulisci_html("La Â«stabilitÃ Â» strategica"), "La «stabilità» strategica")

    def test_frasi_standard(self):
        self.assertEqual(parsers.pulisci_html("Testo. The post Foo appeared first on Bar."), "Testo.")
        self.assertEqual(parsers.pulisci_html("Testo. L’articolo Foo proviene da Il Tascabile."), "Testo.")

    def test_date_senza_fuso(self):
        d = parsers.leggi_data("2026-10-21T08:00:00")
        self.assertEqual(d.utcoffset(), timedelta(hours=2))  # ora italiana (legale a ottobre)


class TestPagine(unittest.TestCase):
    PAG = """<html><head><meta property="og:title" content="Un titolo | Nome Sito"><meta property="og:site_name" content="Nome Sito">
    <meta property="og:image" content="/img/c.jpg"><script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-10-21T07:30:00+02:00"}</script></head></html>"""

    def test_meta_articolo(self):
        m = parsers.meta_articolo(self.PAG, "https://sito.it/a/x")
        self.assertEqual(m["title"], "Un titolo")
        self.assertEqual(m["image"], "https://sito.it/img/c.jpg")
        self.assertEqual(m["date"].hour, 7)

    def test_link_candidati(self):
        pag = """<a href="/articoli/la-lettura-profonda-come-infrastruttura">La lettura profonda come infrastruttura culturale</a>
        <a href="/tag/cultura">Cultura generale del paese</a><a href="/chi-siamo">Chi siamo e cosa facciamo davvero</a>
        <a href="https://esterno.com/a/un-articolo-lungo-di-prova">Un articolo di un altro sito esterno</a>
        <a href="/a/un-governo-stabile-un-economia-ferma">Un governo stabile, un’economia ferma</a>"""
        trovati = [u for u, _ in parsers.link_candidati(pag, "https://sito.it/")]
        self.assertEqual(len(trovati), 2)
        self.assertTrue(all("sito.it" in u for u in trovati))

    def test_trova_feed(self):
        pag = '<link rel="alternate" type="application/rss+xml" href="/feed"><link rel="alternate" type="application/rss+xml" href="/comments/feed">'
        self.assertEqual(parsers.trova_feed(pag, "https://s.it/"), ["https://s.it/feed"])


class TestComposizione(unittest.TestCase):
    def _voce(self, titolo, testo, fonte, ruolo):
        return {"title": titolo, "text": testo, "link": "https://x/" + titolo[:8], "date": datetime.now(timezone.utc), "source": fonte, "role": ruolo,
                "kind": "testo", "image": None, "links": []}

    def test_collegamento_per_parole_comuni(self):
        n = [self._voce("Sciopero degli autotrasportatori blocca i supermercati del Sud", "Le proteste degli autotrasportatori continuano", "Il Post", "notizie")]
        c = [self._voce("Perché lo sciopero degli autotrasportatori preoccupa i supermercati", "Analisi dell'effetto sulle forniture dei supermercati", "Valigia Blu", "scritti"),
             self._voce("La filosofia di Kant oggi", "Un saggio sul pensiero critico", "Il Tascabile", "scritti")]
        composizione.assegna_uid(n, c)
        comp = composizione.componi_semplice(n, c, ["Economia e lavoro", "Cultura e idee", "Altro"])
        self.assertEqual(len(comp.storie[0]["ops"]), 1)
        self.assertEqual(comp.storie[0]["ops"][0]["source"], "Valigia Blu")

    def test_nessuna_uscita_persa_con_ai(self):  # le notizie non raggruppate dall'AI restano comunque nella pagina
        n = [self._voce(f"Notizia numero {i}", "", "Il Post", "notizie") for i in range(4)]
        composizione.assegna_uid(n, [])
        risposta = {"fatti": [{"fid": "F1", "argomento": "Altro", "titolo": "Unito", "testo": "x", "ids": [0, 1]}], "altre_notizie": [], "contenuti": []}
        comp = composizione.componi_ai(risposta, n, [], ["Altro"])
        presenti = {r["uid"] for s in comp.storie for r in s["refs"]}
        self.assertEqual(presenti, {"n0", "n1", "n2", "n3"})

    def test_risposta_ai_con_valori_strani(self):  # l'AI sbaglia: id fuori scala, argomenti inventati
        n = [self._voce("Notizia", "", "Il Post", "notizie")]
        c = [self._voce("Opinione", "", "Valigia Blu", "scritti")]
        composizione.assegna_uid(n, c)
        risposta = {"fatti": [{"fid": "F1", "argomento": "Inventato", "titolo": "T", "ids": [0, 99, "x"]}],
                    "contenuti": [{"id": 1000, "argomento": "Boh", "fatto": "F9"}, {"id": 5000}], "tendenze": [{"titolo": "t", "ids": [0]}]}
        comp = composizione.componi_ai(risposta, n, c, ["Altro"])
        self.assertEqual(comp.storie[0]["topic"], "Altro")
        self.assertEqual(c[0]["topic"], "Altro")


class TestMemoria(unittest.TestCase):
    """Nessuna uscita persa (anche se un giorno salta) e nessuna ripetuta (anche se si rilancia lo stesso giorno)."""

    def _esiti(self, voci):
        from rassegna.fonti import Esito, Fonte
        e = Esito(Fonte("S", "https://s.it", "scritti"), voci, "feed")
        return [e]

    def _v(self, link, ore_fa, adesso):
        return {"title": link, "link": link, "date": adesso - timedelta(hours=ore_fa), "source": "S", "role": "scritti", "text": ""}

    def test_finestra_e_visti(self):
        import aggregatore
        adesso = datetime.now(timezone.utc)
        voci = [self._v("nuova", 3, adesso), self._v("ieri_vista", 20, adesso), self._v("persa_ieri", 40, adesso), self._v("vecchia", 200, adesso)]
        stato = {"ultima_esecuzione": (adesso - timedelta(hours=40)).isoformat(), "visti": {"ieri_vista": "2026-10-21"}}
        out = {v["link"] for v in aggregatore.raccogli_voci(self._esiti(voci), stato, adesso, "2026-10-22")}
        self.assertEqual(out, {"nuova", "persa_ieri"})  # recupera quanto è sfuggito, non ripete il già visto, scarta il troppo vecchio

    def test_rilancio_stesso_giorno(self):
        import aggregatore
        adesso = datetime.now(timezone.utc)
        stato = {"ultima_esecuzione": (adesso - timedelta(hours=1)).isoformat(), "visti": {"nuova": "2026-10-22"}}
        out = aggregatore.raccogli_voci(self._esiti([self._v("nuova", 3, adesso)]), stato, adesso, "2026-10-22")
        self.assertEqual(len(out), 1)  # già vista OGGI: deve comparire ancora nell'edizione di oggi

    def test_niente_arretrato_dopo_esecuzione_regolare(self):  # errore: la 2ª esecuzione caricava 72 ore di arretrato
        import aggregatore
        adesso = datetime.now(timezone.utc)
        stato = {"ultima_esecuzione": (adesso - timedelta(hours=24)).isoformat(), "visti": {}}
        out = aggregatore.raccogli_voci(self._esiti([self._v("di_oggi", 5, adesso), self._v("di_2_giorni_fa", 50, adesso)]), stato, adesso, "2026-10-22")
        self.assertEqual([v["link"] for v in out], ["di_oggi"])

    def test_prima_esecuzione_24_ore(self):
        import aggregatore
        adesso = datetime.now(timezone.utc)
        stato = {"ultima_esecuzione": None, "visti": {}}
        out = aggregatore.raccogli_voci(self._esiti([self._v("a", 3, adesso), self._v("b", 30, adesso)]), stato, adesso, "2026-10-22")
        self.assertEqual([v["link"] for v in out], ["a"])

    def test_fonte_senza_date_non_inonda(self):  # Che Fare: nessuna data dichiarata, 22 articoli in elenco
        import aggregatore
        from rassegna.fonti import Esito, Fonte
        adesso = datetime.now(timezone.utc)
        voci = [{**self._v(f"a{i}", 0, adesso), "data_incerta": True} for i in range(22)]
        e = Esito(Fonte("CF", "https://cf.it", "scritti"), voci, "pagina")
        scartate = []
        out = aggregatore.raccogli_voci([e], {"ultima_esecuzione": None, "visti": {}, "salute": {}}, adesso, "2026-10-22", scartate)
        self.assertEqual(len(out), 3)          # solo le prime 3 dell'elenco
        self.assertEqual(len(scartate), 19)    # le altre vengono ricordate, così domani non compaiono

    def test_scarta_date_nel_futuro(self):  # es. pagina di un evento con data futura
        import aggregatore
        adesso = datetime.now(timezone.utc)
        out = aggregatore.raccogli_voci(self._esiti([self._v("futuro", -48, adesso)]), {"ultima_esecuzione": None, "visti": {}}, adesso, "2026-10-22")
        self.assertEqual(out, [])


class TestAI(unittest.TestCase):
    """Errori reali di Gemini: 503 «alta domanda», 429 limite di richieste, modello ritirato (404)."""

    def setUp(self):
        import os
        os.environ["GEMINI_API_KEY"] = "x"
        self._orig = (ia._una, ia.modelli, ia.PAUSE, ia.time.sleep)
        ia.modelli = lambda: ["m1", "m2", "m3"]
        ia.PAUSE = (0, 0)
        ia.time.sleep = lambda s: None

    def tearDown(self):
        ia._una, ia.modelli, ia.PAUSE, ia.time.sleep = self._orig

    @staticmethod
    def _ok(testo='{"ok": true}'):
        return {"candidates": [{"content": {"parts": [{"text": testo}]}}]}

    def test_sovraccarico_passa_al_modello_successivo(self):
        chiamate = []

        def finta(modello, corpo):
            chiamate.append(modello)
            if modello == "m1":
                raise rete.ErroreRete("HTTP 503", codice=503)
            return self._ok()
        ia._una = finta
        self.assertEqual(ia.chiedi("p"), {"ok": True})
        self.assertEqual(ia.ultimo_modello, "m2")
        self.assertEqual(chiamate.count("m1"), 3)  # riprova con pazienza prima di cambiare modello

    def test_modello_ritirato_si_salta_subito(self):
        chiamate = []

        def finta(modello, corpo):
            chiamate.append(modello)
            if modello == "m1":
                raise rete.ErroreRete("HTTP 404", codice=404)
            return self._ok()
        ia._una = finta
        ia.chiedi("p")
        self.assertEqual(chiamate, ["m1", "m2"])

    def test_tutti_falliscono(self):
        def finta(modello, corpo):
            raise rete.ErroreRete("HTTP 429: quota", codice=429)
        ia._una = finta
        with self.assertRaises(rete.ErroreRete):
            ia.chiedi("p")

    def test_risposta_non_json_si_riprova_con_altro_modello(self):
        ia._una = lambda m, c: self._ok("non è json") if m == "m1" else self._ok()
        self.assertEqual(ia.chiedi("p"), {"ok": True})


class TestMemoriaAI(unittest.TestCase):
    def _v(self, titolo, ruolo, fonte="Il Post", testo=""):
        return {"title": titolo, "text": testo, "link": "https://x/" + titolo.replace(" ", "-"), "date": datetime.now(timezone.utc), "source": fonte,
                "role": ruolo, "kind": "testo", "image": None, "links": []}

    def test_ripresa_dalla_memoria(self):
        import os
        import tempfile
        os.environ["RASSEGNA_AI_CACHE"] = os.path.join(tempfile.mkdtemp(), "cache.json")
        n = [self._v("Sciopero camionisti", "notizie"), self._v("Altra notizia", "notizie")]
        c = [self._v("Perché i camionisti scioperano", "scritti", "Valigia Blu"), self._v("Saggio generale", "scritti", "Il Tascabile")]
        composizione.assegna_uid(n, c)
        risposta = {"editoriale": "Il punto.", "fatti": [{"fid": "F1", "argomento": "Economia e lavoro", "titolo": "Sciopero", "testo": "T", "ids": [0], "per_te": True}],
                    "altre_notizie": [{"id": 1, "argomento": "Cronaca"}],
                    "contenuti": [{"id": 1000, "argomento": "Economia e lavoro", "fatto": "F1", "sintesi": "S1"}, {"id": 1001, "argomento": "Cultura e idee", "fatto": None, "sintesi": "S2"}],
                    "tendenze": [{"titolo": "Sciopero", "ids": [0, 1000]}]}
        arg = ["Economia e lavoro", "Cronaca", "Cultura e idee", "Altro"]
        comp = composizione.componi_ai(risposta, n, c, arg)
        composizione.salva_cache(comp, n, c)
        # aggiornamento successivo: stesse uscite + una notizia e un'opinione nuove; l'AI non risponde
        n2 = [self._v("Sciopero camionisti", "notizie"), self._v("Altra notizia", "notizie"), self._v("Notizia arrivata dopo", "notizie")]
        c2 = [self._v("Perché i camionisti scioperano", "scritti", "Valigia Blu"), self._v("Saggio generale", "scritti", "Il Tascabile"),
              self._v("Opinione nuova sulla cultura del libro", "scritti", "Lucy")]
        composizione.assegna_uid(n2, c2)
        cache = composizione.carica_cache()
        self.assertIsNotNone(cache)
        rip = composizione.componi_da_cache(cache, n2, c2, arg)
        presenti = {r["link"] for s in rip.storie for r in s["refs"]}
        self.assertEqual(presenti, {x["link"] for x in n2})                 # nessuna notizia persa
        self.assertEqual(rip.editoriale, "Il punto.")
        principale = next(s for s in rip.storie if not s["minor"])
        self.assertEqual([o["summary"] for o in principale["ops"]], ["S1"])  # collegamento e sintesi dell'AI mantenuti
        self.assertEqual(c2[1]["topic"], "Cultura e idee")
        self.assertIn("topic", c2[2])                                         # l'opinione nuova ha comunque un argomento
        self.assertEqual(len(rip.tendenze), 1)


if __name__ == "__main__":
    unittest.main()
