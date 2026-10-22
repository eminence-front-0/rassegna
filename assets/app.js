/* La Rassegna — comportamento della pagina: filtri, ricerca, letti/salvati, preferenze, animazioni. Nessuna dipendenza. */
(() => {
  const CFG = window.RASSEGNA || {};
  const $ = (q, r = document) => [...r.querySelectorAll(q)];
  const $1 = (q, r = document) => r.querySelector(q);
  document.documentElement.classList.add('js');

  /* ---------- memoria locale (solo in questo browser) ---------- */
  const mem = {
    get(k, v) { try { return JSON.parse(localStorage.getItem('rassegna:' + k)) ?? v; } catch { return v; } },
    set(k, v) { try { localStorage.setItem('rassegna:' + k, JSON.stringify(v)); } catch { /* spazio finito o navigazione privata */ } },
  };
  let letti = new Set(mem.get('letti', []));
  let salvati = new Set(mem.get('salvati', []));
  let pref = mem.get('pref', {});            // link -> {v: 1|-1, f: fonte, t: titolo}
  const sugDismiss = new Set(mem.get('sugg_no', []));

  /* ---------- filtri ---------- */
  const st = { tema: '', fonte: '', tipo: 'all', q: '', tend: '', per: false, salvati: false };
  const P = new URLSearchParams(location.hash.slice(1));
  st.tema = P.get('tema') || ''; st.fonte = P.get('fonte') || ''; st.tipo = P.get('tipo') || 'all';
  st.q = P.get('q') || ''; st.tend = P.get('tend') || ''; st.per = P.get('per') === '1'; st.salvati = P.get('salvati') === '1';
  const tendenze = CFG.tendenze || {};

  const norm = s => (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const testo = el => el._t || (el._t = norm(el.dataset.text || el.textContent));

  function passa(el, ids) {
    if (st.fonte && !(el.dataset.src || '').split('|').includes(st.fonte)) return false;
    if (st.per && el.dataset.per !== '1') return false;
    if (st.salvati && !salvati.has(el.dataset.link)) return false;
    if (st.tend) {
      const set = tendenze[st.tend] || [];
      if (!(ids || '').split(' ').some(i => set.includes(i))) return false;
    }
    if (st.q && !norm(st.q).split(/\s+/).every(w => testo(el).includes(w))) return false;
    return true;
  }

  function applica() {
    let n = 0;
    const dossier = d => {
      const fattoOk = st.tipo !== 'opinioni' && passa(d, d.dataset.n);
      let ops = 0;
      $('.op', d).forEach(o => {
        const ok = st.tipo !== 'fatti' && passa(o, o.dataset.c);
        o.hidden = !ok; if (ok) ops++;
      });
      const th = $1('.thread', d);
      if (th) { th.hidden = !ops; const c = $1('.thread-h b', th); if (c) c.textContent = ops; }
      const mostra = fattoOk || ops > 0;
      d.hidden = !mostra; d.classList.toggle('ctx', mostra && !fattoOk);
      return { f: mostra && fattoOk ? 1 : 0, o: mostra ? ops : 0 };
    };
    const lead = $1('.lead');
    if (lead) {
      const ok = !st.tema || lead.dataset.topic === st.tema;
      const r = ok ? dossier($1('.dossier', lead)) : { f: 0, o: 0 };
      lead.hidden = !(r.f + r.o); n += r.f + r.o;
    }
    $('section.sez[data-topic]').forEach(sec => {
      if (st.tema && sec.dataset.topic !== st.tema) { sec.hidden = true; return; }
      let nf = 0, no = 0;
      $('.dossier', sec).forEach(d => { const r = dossier(d); nf += r.f; no += r.o; });
      $('.fcard', sec).forEach(k => { const ok = st.tipo !== 'fatti' && passa(k, k.dataset.c); k.hidden = !ok; if (ok) no++; });
      $('.oth li', sec).forEach(k => { const ok = st.tipo !== 'opinioni' && passa(k, k.dataset.n); k.hidden = !ok; if (ok) nf++; });
      $('.sub', sec).forEach(g => { g.hidden = !$('.fcard,.oth li', g).some(x => !x.hidden); });
      $('.grid', sec).forEach(g => { g.hidden = !$('.dossier', g).some(x => !x.hidden); });
      const c = nf + no;
      const cf = $1('.cnt .f', sec), co = $1('.cnt .o', sec);
      if (cf) cf.textContent = `${nf} ${nf === 1 ? 'fatto' : 'fatti'}`;
      if (co) co.textContent = `${no} ${no === 1 ? 'opinione' : 'opinioni'}`;
      sec.hidden = !c; n += c;
      if (!sec.hidden) revela(sec);
    });
    const attivoF = st.tema || st.fonte || st.tipo !== 'all' || st.q || st.tend || st.per || st.salvati;
    ['consigli', 'fonti'].forEach(id => { const e = document.getElementById(id); if (e) e.hidden = !!attivoF; });
    $('.full details').forEach(d => {
      let v = 0;
      $('li', d).forEach(li => {
        const nw = li.classList.contains('n');
        const ok = (!st.tema || li.dataset.topic === st.tema) && (st.tipo === 'all' || (st.tipo === 'fatti') === nw)
          && (!st.fonte || d.dataset.src === st.fonte) && (!st.q || norm(li.textContent).includes(norm(st.q)))
          && (!st.salvati || salvati.has(li.dataset.link));
        li.hidden = !ok; if (ok) v++;
      });
      d.hidden = !v; $1('summary i', d).textContent = '· ' + v;
      if ((st.fonte || st.q) && v) d.open = true;
    });
    $('[data-tema]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.tema === st.tema)));
    $('[data-kind]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.kind === st.tipo)));
    $('[data-fsrc-btn]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.fsrcBtn === st.fonte)));
    $('[data-trend]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.trend === st.tend)));
    $1('[data-toggle=per]').setAttribute('aria-pressed', String(st.per));
    $1('[data-toggle=saved]').setAttribute('aria-pressed', String(st.salvati));
    const q = $1('#q'); if (q && q.value !== st.q) q.value = st.q;
    const lbl = $1('#fonte-lbl'); if (lbl) lbl.textContent = st.fonte || 'Tutte le fonti';
    const attivo = st.tema || st.fonte || st.tipo !== 'all' || st.q || st.tend || st.per || st.salvati;
    $1('.reset').hidden = !attivo;
    $1('.stato-filtri').hidden = !attivo;
    $1('.stato-filtri').textContent = attivo ? (n ? `${n} ${n === 1 ? 'voce' : 'voci'} con questi filtri` : 'Nessuna voce con questi filtri') : '';
    $1('#vuoto').hidden = !(attivo && !n);
    $1('#n-salvati').textContent = salvati.size ? salvati.size : '';
    segnaStati();
    const h = new URLSearchParams();
    [['tema', st.tema], ['fonte', st.fonte], ['tipo', st.tipo !== 'all' ? st.tipo : ''], ['q', st.q], ['tend', st.tend], ['per', st.per ? '1' : ''], ['salvati', st.salvati ? '1' : '']]
      .forEach(([k, v]) => v && h.set(k, v));
    history.replaceState(null, '', h.toString() ? '#' + h : location.pathname + location.search);
  }

  /* ---------- stati degli articoli: letto, salvato, preferenza ---------- */
  function segnaStati() {
    $('[data-link]').forEach(el => {
      const l = el.dataset.link;
      el.classList.toggle('letto', letti.has(l));
      const a = $1(':scope > .acts, :scope .acts', el);
      if (!a) return;
      $1('[data-act=save]', a).setAttribute('aria-pressed', String(salvati.has(l)));
      $1('[data-act=up]', a).setAttribute('aria-pressed', String(pref[l]?.v === 1));
      $1('[data-act=down]', a).setAttribute('aria-pressed', String(pref[l]?.v === -1));
      a.classList.toggle('on', salvati.has(l) || !!pref[l]);
    });
    const nPref = Object.keys(pref).length;
    const b = $1('#invia-pref');
    if (b) { b.hidden = !nPref; $1('span', b).textContent = nPref; }
  }

  /* ---------- eventi ---------- */
  document.addEventListener('click', e => {
    const t = e.target;
    let el;
    if ((el = t.closest('[data-tema]'))) st.tema = el.dataset.tema;
    else if ((el = t.closest('[data-kind]'))) st.tipo = el.dataset.kind;
    else if ((el = t.closest('[data-trend]'))) st.tend = st.tend === el.dataset.trend ? '' : el.dataset.trend;
    else if ((el = t.closest('[data-toggle]'))) st[el.dataset.toggle === 'per' ? 'per' : 'salvati'] = !st[el.dataset.toggle === 'per' ? 'per' : 'salvati'];
    else if ((el = t.closest('[data-fsrc-btn]'))) { if (el.disabled) return; st.fonte = st.fonte === el.dataset.fsrcBtn ? '' : el.dataset.fsrcBtn; $1('.menu').hidden = true; }
    else if ((el = t.closest('[data-fsrc]'))) { e.preventDefault(); st.fonte = st.fonte === el.dataset.fsrc ? '' : el.dataset.fsrc; window.scrollTo({ top: $1('.bar').offsetTop - 60, behavior: 'smooth' }); }
    else if (t.closest('.reset')) { Object.assign(st, { tema: '', fonte: '', tipo: 'all', q: '', tend: '', per: false, salvati: false }); }
    else if (t.closest('#btn-fonti')) { const m = $1('.menu'); m.hidden = !m.hidden; return; }
    else if ((el = t.closest('.ic'))) { azione(el); return; }
    else if ((el = t.closest('[data-copia]'))) { copia(el); return; }
    else if ((el = t.closest('[data-no-sugg]'))) { nascondiSugg(el); return; }
    else if (t.closest('#invia-pref')) { inviaPref(); return; }
    else if ((el = t.closest('a[href]')) && !el.closest('.menu')) {
      const c = el.closest('[data-link]'); if (c) { letti.add(c.dataset.link); mem.set('letti', [...letti].slice(-3000)); c.classList.add('letto'); }
      return;
    } else { if (!t.closest('.pop')) $1('.menu').hidden = true; return; }
    applica();
  });
  const q = $1('#q');
  let tm; q.addEventListener('input', () => { clearTimeout(tm); tm = setTimeout(() => { st.q = q.value.trim(); applica(); }, 120); });
  document.addEventListener('keydown', e => {
    if (e.key === '/' && !/input|textarea|select/i.test(document.activeElement.tagName)) { e.preventDefault(); q.focus(); q.select(); }
    if (e.key === 'Escape') { q.blur(); $1('.menu').hidden = true; }
  });

  function azione(btn) {
    const box = btn.closest('[data-link]'); if (!box) return;
    const l = box.dataset.link, a = btn.dataset.act;
    if (a === 'save') { salvati.has(l) ? salvati.delete(l) : salvati.add(l); mem.set('salvati', [...salvati]); }
    else {
      const v = a === 'up' ? 1 : -1;
      if (pref[l]?.v === v) delete pref[l]; else pref[l] = { v, f: box.dataset.fonte || '', t: (box.dataset.titolo || '').slice(0, 70) };
      mem.set('pref', pref);
      if (pref[l]) toast(v === 1 ? 'Segnato come interessante' : 'Segnato come non interessante');
    }
    segnaStati();
    if (st.salvati) applica();
  }

  function inviaPref() {
    const voci = Object.values(pref).slice(-40).map(p => ({ v: p.v, f: p.f, t: p.t }));
    const corpo = '```json\n' + JSON.stringify(voci) + '\n```\n\nBasta premere «Submit new issue»: alla prossima edizione le preferenze vengono lette e questa segnalazione si chiude da sola.';
    const url = `https://github.com/${CFG.repo}/issues/new?labels=feedback&title=${encodeURIComponent('Preferenze ' + CFG.edizione)}&body=${encodeURIComponent(corpo)}`;
    window.open(url, '_blank', 'noopener');
    pref = {}; mem.set('pref', pref); segnaStati();
  }

  function copia(btn) {
    const riga = btn.dataset.copia;
    (navigator.clipboard ? navigator.clipboard.writeText(riga) : Promise.reject()).catch(() => {}).finally(() => {
      toast('Riga copiata: incollala nella sezione [scritti] e salva');
      window.open(`https://github.com/${CFG.repo}/edit/main/sources.txt`, '_blank', 'noopener');
    });
  }
  function nascondiSugg(btn) {
    const c = btn.closest('.sugg'); sugDismiss.add(c.dataset.dominio); mem.set('sugg_no', [...sugDismiss]);
    pref['sugg:' + c.dataset.dominio] = { v: -1, f: c.dataset.dominio, t: 'fonte consigliata' }; mem.set('pref', pref);
    c.style.display = 'none'; toast('Non te la riproporremo'); segnaStati();
  }
  $('.sugg').forEach(c => { if (sugDismiss.has(c.dataset.dominio)) c.style.display = 'none'; });

  let tt;
  function toast(m) { const t = $1('.toast'); t.textContent = m; t.classList.add('on'); clearTimeout(tt); tt = setTimeout(() => t.classList.remove('on'), 2600); }

  /* ---------- comparsa dolce degli elementi ---------- */
  const io = 'IntersectionObserver' in window ? new IntersectionObserver(es => es.forEach(x => { if (x.isIntersecting) { x.target.classList.add('in'); io.unobserve(x.target); } }), { rootMargin: '0px 0px -6% 0px' }) : null;
  function revela(root) { $('.rv:not(.in)', root || document).forEach(x => io ? io.observe(x) : x.classList.add('in')); }

  applica();
  revela();
  setTimeout(() => $('.rv:not(.in)').forEach(x => x.classList.add('in')), 1800);  // rete di sicurezza
})();
