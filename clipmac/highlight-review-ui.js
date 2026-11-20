(() => {
  const format = value => Number(value).toLocaleString('de-DE', {maximumFractionDigits: 1});
  const factors = new Intl.NumberFormat('de-DE', {maximumFractionDigits: 1});

  function scoreDetails(score) {
    const details = el('details');
    const value = score.score === null ? 'nicht beurteilbar' : `${format(score.score)} / 100`;
    details.append(el('summary', `${score.label} · ${value}${score.recommended ? ' · Empfohlen' : ''}`));
    details.append(el('p', 'Redaktionelle Heuristik. Die Reichweite lässt sich daraus nicht vorhersagen.'));
    const list = el('ul');
    for (const item of Object.values(score.components)) {
      const points = item.score === null ? 'kein Beleg' : `${format(item.score)} Punkte`;
      const weight = factors.format(item.effective_weight);
      list.append(el('li', `${item.label} (${weight} %): ${points}. ${item.reason}`));
    }
    details.append(list);
    for (const reason of score.reasons) details.append(el('p', reason));
    details.append(el('small', [score.version, score.model, score.prompt_version].filter(Boolean).join(' · ')));
    return details;
  }

  function control(label, operation) {
    const button = el('button', label);
    button.type = 'button';
    button.onclick = async () => {
      button.disabled = true;
      try { await operation(); }
      finally { button.disabled = false; }
    };
    return button;
  }

  function reportForm(row, action) {
    const entry = el('details');
    entry.append(el('summary', 'Problem melden'));
    const form = el('form');
    const noteLabel = el('label', 'Beschreibung');
    const note = el('textarea');
    note.required = true;
    note.minLength = 3;
    note.maxLength = 3000;
    const positionLabel = el('label', 'Sekunde in der Vorschau (optional)');
    const position = el('input');
    position.type = 'number';
    position.min = 0;
    position.step = '0.1';
    position.max = Math.ceil(row.end - row.start);
    const submit = el('button', 'Problem speichern');
    submit.type = 'submit';
    noteLabel.append(note);
    positionLabel.append(position);
    form.append(noteLabel, positionLabel, submit);
    form.onsubmit = async event => {
      event.preventDefault();
      submit.disabled = true;
      try {
        const saved = await action('report', {id: row.id, note: note.value,
          position: position.value === '' ? null : position.valueAsNumber});
        if (saved) note.value = '';
      } finally { submit.disabled = false; }
    };
    entry.append(form);
    return entry;
  }

  function render(card, row, action) {
    if (row.score) card.append(scoreDetails(row.score));
    if (!row.preview_ready || !row.review) return;
    const review = row.review;
    const ratings = el('div', undefined, 'highlights-actions');
    ratings.setAttribute('role', 'group');
    ratings.setAttribute('aria-label', 'Schnittfassung bewerten');
    for (const [value, label] of [['good', 'Gut'], ['medium', 'Mittel'], ['bad', 'Schlecht']]) {
      const button = control(label, () => action('rating', {id: row.id, value: review.rating === value ? null : value}));
      button.setAttribute('aria-pressed', String(review.rating === value));
      ratings.append(button);
    }
    card.append(ratings, reportForm(row, action));
    for (const report of review.reports) {
      if (report.status !== 'open') continue;
      const block = el('div');
      block.append(el('p', `${report.position === null ? '' : `${format(report.position)} s · `}${report.note}`),
        control('Meldung zurückziehen', () => action('report-withdraw', {id: row.id, report_id: report.id})));
      card.append(block);
    }
    if (review.promoted_clip_id) card.append(el('p', 'Für die Paketwarteschlange freigegeben.'));
    if (row.can_promote) {
      const request = control('In die Paketwarteschlange', async () => {
        if (window.confirm('Diese Fassung für die bestehende Upload-Automatik freigeben?')) {
          await action('promote', {id: row.id, confirmed: true});
        }
      });
      card.append(request);
    }
  }

  window.clipmacHighlightReview = {render};
})();
