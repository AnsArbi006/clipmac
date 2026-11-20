(() => {
  const jobs = document.getElementById('highlight-jobs');
  const candidates = document.getElementById('highlight-candidates');
  const status = document.getElementById('highlight-error');
  const form = document.getElementById('highlight-import');
  const phases = {
    queued: 'Wartet', running: 'Analysiert', analyzing: 'Analysiert',
    downloading: 'Lädt Quelle', rendering: 'Rendert Vorschau', complete: 'Fertig',
    done: 'Fertig', completed: 'Fertig', ready: 'Fertig', error: 'Fehler', failed: 'Fehler',
    cancelled: 'Abgebrochen', interrupted: 'Unterbrochen',
  };
  const done = new Set(['complete', 'completed', 'done', 'ready', 'error', 'failed', 'cancelled', 'interrupted']);
  const sourceLabels = {live: 'Twitch Live', vod: 'Twitch-VOD', local: 'Lokale Datei'};
  const timestamp = value => {
    const total = Math.max(0, Math.floor(Number(value)));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
  };
  let jobsKey = '';
  let candidateKey = '';
  let pending = false;

  async function action(path, payload) {
    try {
      const result = await post(`highlights/${path}`, payload);
      status.textContent = '';
      return result;
    } catch (error) {
      status.textContent = error.message;
      return null;
    } finally {
      await refreshHighlights();
    }
  }

  function button(text, operation) {
    const control = el('button', text);
    control.type = 'button';
    control.onclick = async () => {
      control.disabled = true;
      try { await operation(); }
      finally { control.disabled = false; }
    };
    return control;
  }

  function renderJobs(rows) {
    const key = JSON.stringify(rows);
    if (key === jobsKey) return;
    jobsKey = key;
    const cards = rows.map(row => {
      const card = el('article', undefined, 'highlights-card');
      const display = phases[row.status] || row.status;
      card.append(el('strong', sourceLabels[row.kind] || 'Analyse'), el('p', display));
      if (row.error || row.detail) card.append(el('p', row.error || row.detail));
      if (!done.has(row.status)) {
        const progress = el('progress');
        progress.setAttribute('aria-label', 'Fortschritt der Highlight-Analyse');
        if (Number.isFinite(row.progress)) {
          progress.max = 100;
          progress.value = Math.max(0, Math.min(100, row.progress));
        }
        card.append(progress, button('Abbrechen', () => action('cancel', {id: row.id})));
      }
      return card;
    });
    jobs.replaceChildren(...cards);
  }

  function renderCandidates(rows) {
    const key = JSON.stringify(rows);
    if (key === candidateKey) return;
    candidateKey = key;
    const cards = rows.map(row => {
      const card = el('article', undefined, 'highlights-card');
      const label = [sourceLabels[row.kind], row.channel].filter(Boolean).join(' · ');
      card.append(el('strong', label), el('p', `${timestamp(row.start)} – ${timestamp(row.end)}`));
      for (const [key, name] of [['hook', 'Einstieg'], ['context', 'Kontext'], ['payoff', 'Höhepunkt und Ende']]) {
        const evidence = row.evidence?.[key];
        if (evidence?.quote) card.append(el('p', `${name}: „${evidence.quote}“`));
      }
      if (row.review_required) card.append(el('p', 'Dieser Ausschnitt braucht eine redaktionelle Prüfung.'));
      if (row.preview_error) card.append(el('p', row.preview_error));
      if (row.preview_ready) {
        const video = el('video');
        video.controls = true;
        video.playsInline = true;
        video.preload = 'none';
        video.src = `/highlight-video/${encodeURIComponent(row.id)}`;
        card.append(video);
      } else {
        card.append(button('Vorschau rendern', () => action('render', {id: row.id})));
      }
      return card;
    });
    candidates.replaceChildren(...(cards.length ? cards : [el('p', 'Bisher sind keine Schnittvorschläge vorhanden.')]));
  }

  async function refreshHighlights() {
    if (pending || document.hidden) return;
    pending = true;
    try {
      const response = await fetch('/api/highlights/state');
      if (!response.ok) throw new Error('Analyse-Status ist momentan nicht erreichbar.');
      const data = await response.json();
      form.elements.kind.options[1].disabled = data.development;
      renderJobs(data.jobs);
      renderCandidates(data.candidates);
    } catch (error) {
      status.textContent = error.message;
    } finally { pending = false; }
  }

  form.elements.kind.onchange = () => {
    document.getElementById('highlight-source-label').textContent = form.elements.kind.value === 'vod' ? 'Twitch-VOD-URL' : 'Absoluter Dateipfad';
  };
  form.onsubmit = async event => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(form));
    if (await action('start', payload)) form.elements.source.value = '';
  };
  refreshHighlights();
  setInterval(refreshHighlights, 3000);
})();
