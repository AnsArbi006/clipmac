'use strict';
const $ = (id) => document.getElementById(id);
const LABEL = { waiting: 'Wartet', uploading: 'Lädt hoch', review: 'In Prüfung', public: '✓ Öffentlich',
  failed: 'Fehlgeschlagen', unknown: 'Prüfen', paused: 'Pausiert' };
const STAGES = ['Erkennung', 'Analyse', 'Schnitt', 'Upload'];
let state = null;
const views = {};

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') node.className = v; else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v === true ? '' : v);
  }
  for (const child of children.flat()) if (child !== null && child !== undefined)
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
}

async function post(path, body) {
  const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-ClipMac': '1' },
    body: JSON.stringify(body || {}) });
  const data = await response.json().catch(() => ({}));
  $('error').textContent = response.ok ? '' : (data.error || 'Aktion fehlgeschlagen.');
  refresh();
  return data;
}

function time(ts) { return new Date(ts * 1000).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' }); }

function streamCard(ch, index) {
  const others = state.streamers;
  const select = el('select', { disabled: state.running, onchange: (e) => {
    const chosen = [...state.selected]; chosen[index] = e.target.value; post('/api/select', { channels: chosen }); } },
    others.map((name) => el('option', { value: name, selected: name === ch.name }, name)));
  return el('div', { class: 'card stream' },
    el('h3', {}, el('span', {}, el('span', { class: 'dot ' + (ch.live ? 'live' : '') }), select),
      el('span', { class: 'meta' }, ch.state)),
    el('div', { class: 'kv' },
      'Live', el('b', {}, ch.live ? 'live' : 'offline'),
      'Chat', el('b', {}, ch.chat),
      'Aktivität', el('b', {}, `${ch.messages_10s} / 10 s` + (ch.baseline !== null ? ` (normal ${ch.baseline})` : '')),
      'Aufnahme', el('b', {}, el('span', { class: 'dot ' + (ch.recording ? 'on' : '') }), ch.recording ? 'läuft (5-min-Puffer)' : 'aus'),
      'Kategorie', el('b', {}, ch.category || '–'),
      'Spitzen', el('b', {}, ch.spikes)),
    ch.warning ? el('div', { class: 'warning' }, ch.warning) : null);
}

function progress() {
  const active = state.worker.stage;
  const uploading = state.clips.some((c) => Object.values(c.posts).some((p) => p.status === 'uploading'));
  const c = state.counts;
  return [
    ...STAGES.map((s) => el('span', { class: 'step' + (s === active || (s === 'Upload' && uploading) ? ' active' : '') }, s)),
    el('span', { class: 'meta' }, ` ${c.erkannt} erkannt · ${c.fertig} geschnitten · ${c.geeignet} geeignet · ` +
      `${c.veröffentlicht} veröffentlicht` + (state.queued ? ` · ${state.queued} in Warteschlange` : '') +
      (state.worker.detail ? ` · ${state.worker.detail}` : ''))];
}

function platformCard(name, label) {
  const p = state.platforms[name];
  const confirm = p.account && p.account !== p.confirmed
    ? el('button', { onclick: () => post('/api/confirm', { platform: name }) }, `Konto „${p.account}“ bestätigen`) : null;
  return el('div', { class: 'card' },
    el('div', {}, el('b', {}, label), ' ', el('span', { class: 'meta' },
      p.confirmed ? `Zielkonto: ${p.confirmed}` : 'Zielkonto nicht bestätigt')),
    el('div', { class: p.detail ? 's-paused' : 'meta' }, p.detail || (state.platforms_enabled.includes(name) ? 'aktiv' : 'deaktiviert')),
    confirm);
}

function postBox(clip, name, label) {
  const p = clip.posts[name];
  if (!p) return el('div', { class: 'post' }, el('div', { class: 'name' }, label), el('span', { class: 'meta' }, '–'));
  const retry = (p.status === 'failed' || p.status === 'paused')
    ? el('button', { onclick: () => post('/api/retry', { clip: clip.id, platform: name }) }, 'Erneut') : null;
  return el('div', { class: 'post' }, el('div', { class: 'name' }, label),
    el('div', { class: 's-' + p.status }, LABEL[p.status] || p.status),
    p.url ? el('a', { href: p.url, target: '_blank', rel: 'noopener noreferrer' }, p.url) : null,
    p.detail && p.status !== 'public' ? el('div', { class: 'meta' }, p.detail) : null, retry);
}

function clipCard(clip) {
  const view = views[clip.id] || 'final';
  const video = clip[view]
    ? el('video', { controls: true, preload: 'metadata', src: `/media/${clip.id}/${view}`,
      poster: clip.thumb ? `/media/${clip.id}/thumb` : null }) : el('div', { class: 'meta' }, clip.detail);
  const tabs = clip.final ? el('div', { class: 'tabs' },
    el('button', { class: view === 'final' ? 'on' : '', onclick: () => { views[clip.id] = 'final'; render(true); } }, 'Fertiger Schnitt'),
    clip.original ? el('button', { class: view === 'original' ? 'on' : '',
      onclick: () => { views[clip.id] = 'original'; render(true); } }, 'Originalausschnitt') : null) : null;
  const cut = clip.cut ? `Schnitt ${clip.cut[0].toFixed(1)}–${clip.cut[1].toFixed(1)} s` : '';
  return el('div', { class: 'card clip', 'data-id': clip.id },
    el('div', { class: 'head' },
      clip.thumb ? el('img', { class: 'thumb', src: `/media/${clip.id}/thumb`, alt: '' }) : null,
      el('div', { style: 'flex:1' }, el('b', {}, clip.channel), el('div', { class: 'meta' },
        `${time(clip.created)}${clip.duration ? ' · ' + clip.duration.toFixed(1) + ' s' : ''}${cut ? ' · ' + cut : ''}`),
        el('div', { class: 'meta' }, clip.status === 'done' ? (clip.eligible ? 'Geeignet' : clip.reason || '') : clip.detail)),
      el('div', { class: 'score' }, clip.score === null || clip.score === undefined ? '–' : Math.round(clip.score),
        el('small', {}, 'Viral Score (experimentell)'))),
    tabs, video,
    el('div', { class: 'posts' }, postBox(clip, 'tiktok', 'TikTok'), postBox(clip, 'youtube', 'YouTube')));
}

let lastClips = '';
function render(force) {
  $('mode').textContent = state.demo ? 'Entwicklungsmodus – synthetisch, keine echten Uploads' : '';
  $('start').disabled = state.running; $('stop').disabled = !state.running;
  $('streams').replaceChildren(...state.channels.map(streamCard));
  $('progress').replaceChildren(...progress());
  if (document.activeElement !== $('threshold')) $('threshold').value = state.threshold;
  $('upload').checked = state.upload_enabled;
  $('p-tiktok').checked = state.platforms_enabled.includes('tiktok');
  $('p-youtube').checked = state.platforms_enabled.includes('youtube');
  $('platforms').replaceChildren(platformCard('tiktok', 'TikTok'), platformCard('youtube', 'YouTube'));
  // Keep playing videos untouched: rebuild the gallery only when its data changed.
  const signature = JSON.stringify(state.clips) + JSON.stringify(views);
  if (force || signature !== lastClips) {
    const playing = [...document.querySelectorAll('video')].some((v) => !v.paused);
    if (!playing || force) {
      lastClips = signature;
      $('clips').replaceChildren(...(state.clips.length ? state.clips.map(clipCard)
        : [el('p', { class: 'meta' }, 'Noch keine Clips. Start drücken; Clips erscheinen nach einer Chat-Spitze.')]));
    }
  }
}

async function refresh() {
  try {
    state = await (await fetch('/api/state')).json();
    render(false);
  } catch (e) { $('error').textContent = 'Dashboard-Server nicht erreichbar.'; }
}

$('start').onclick = () => post('/api/start');
$('stop').onclick = () => post('/api/stop');
$('threshold').onchange = (e) => post('/api/settings', { score_threshold: parseInt(e.target.value, 10) });
$('upload').onchange = (e) => post('/api/settings', { upload_enabled: e.target.checked });
const platforms = () => ['tiktok', 'youtube'].filter((p) => $('p-' + p).checked);
$('p-tiktok').onchange = () => post('/api/settings', { platforms_enabled: platforms() });
$('p-youtube').onchange = () => post('/api/settings', { platforms_enabled: platforms() });
refresh();
setInterval(refresh, 2000);
