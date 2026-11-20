(() => {
  const channels = document.getElementById('live-channels');
  const candidates = document.getElementById('live-candidates');
  const status = document.getElementById('live-error');
  const form = document.getElementById('live-chat-form');
  const labels = {
    off: 'Aus', offline: 'Offline', connected: 'Verbunden', warming: 'Wärmt auf',
    recording: 'Zeichnet auf', waiting: 'Wartet auf freien Recorder', paused: 'Pausiert',
    stopping: 'Wird beendet', error: 'Fehler',
  };
  const megabytes = bytes => `${(Number(bytes || 0) / 1_000_000).toLocaleString('de-DE', {maximumFractionDigits: 1})} MB`;
  const clock = seconds => new Date(seconds * 1000).toLocaleTimeString('de-DE');
  const channelCards = new Map();
  let candidateKey = '';
  let pending = false;

  async function act(path, payload) {
    try {
      await post(`live/${path}`, payload);
      status.textContent = '';
    } catch (error) {
      status.textContent = error.message;
    } finally {
      await refreshLive();
    }
  }

  function renderChannels(state) {
    const wanted = new Set(state.channels.map(row => row.channel));
    for (const [channel, card] of channelCards) {
      if (!wanted.has(channel)) {
        card.node.remove();
        channelCards.delete(channel);
      }
    }
    for (const row of state.channels) {
      let card = channelCards.get(row.channel);
      if (!card) {
        const node = el('article', undefined, 'highlights-card');
        const description = el('p');
        const detail = el('p');
        const button = el('button');
        button.type = 'button';
        node.append(el('strong', row.channel), description, detail, button);
        channels.append(node);
        card = {node, description, detail, button};
        channelCards.set(row.channel, card);
      }
      card.description.textContent = `${labels[row.state] || row.state} · ${Math.round(row.buffer_seconds || 0)} s · ${megabytes(row.bytes)}`;
      card.detail.textContent = row.detail || '';
      card.button.textContent = row.enabled ? 'Stoppen' : 'Aufnahme starten';
      card.button.disabled = state.development;
      card.button.onclick = async () => {
        card.button.disabled = true;
        await act(row.enabled ? 'stop' : 'start', {channel: row.channel});
        card.button.disabled = state.development;
      };
    }
  }

  function renderCandidates(rows) {
    const key = JSON.stringify(rows);
    if (candidateKey === key) return;
    candidateKey = key;
    const cards = rows.map(row => {
      const card = el('article', undefined, 'highlights-card');
      const time = `${clock(row.start)} – ${clock(row.end)}`;
      const chat = `${row.chat.messages} Nachrichten · ${row.chat.participants} Teilnehmer`;
      card.append(el('strong', row.channel), el('p', time), el('p', chat));
      if (row.coverage !== 'complete') card.append(el('p', 'Pufferabdeckung prüfen'));
      if (row.category_review) card.append(el('p', 'Kategorie prüfen'));
      const analyze = el('button', 'Ausschnitt analysieren');
      analyze.type = 'button';
      analyze.disabled = !['complete', 'exported'].includes(row.coverage);
      analyze.onclick = async () => {
        analyze.disabled = true;
        try {
          await post('highlights/analyze-live', {id: row.id});
          document.getElementById('analysis-heading').scrollIntoView({block: 'start'});
        } catch (error) {
          status.textContent = error.message;
          analyze.disabled = false;
        }
      };
      card.append(analyze);
      return card;
    });
    candidates.replaceChildren(...(cards.length ? cards : [el('p', 'Bisher wurden keine Chat-Spitzen erkannt.')]));
  }

  async function refreshLive() {
    if (pending || document.hidden) return;
    pending = true;
    try {
      const response = await fetch('/api/live/state');
      if (!response.ok) throw new Error('Live-Status ist momentan nicht erreichbar.');
      const state = await response.json();
      document.getElementById('live-disk').textContent = `${megabytes(state.bytes)} von ${megabytes(state.limit_bytes)}`;
      for (const element of form.elements) element.disabled = state.development;
      if (state.development) status.textContent = 'Entwicklungsmodus · Live-Aufnahmen sind gesperrt.';
      else if (state.error) status.textContent = state.error;
      renderChannels(state);
      renderCandidates(state.candidates);
    } catch (error) {
      status.textContent = error.message;
    } finally {
      pending = false;
    }
  }

  form.onsubmit = async event => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(form));
    form.elements.access_token.value = '';
    await act('chat-credentials', payload);
    if (!status.textContent) status.textContent = 'Chat-Zugang gespeichert.';
  };
  refreshLive();
  setInterval(refreshLive, 3000);
})();
