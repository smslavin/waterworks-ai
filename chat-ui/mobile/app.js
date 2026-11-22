// Read-only mobile view of this plant's live alerts and pending insight
// reviews (waterworks-ai#6). Plain browser JS, no build step.
//
// Token: when chat-ui is bound off loopback (BIND_HOST), /api/reviews needs
// WATERWORKS_API_TOKEN. Open /mobile/?token=… once and it is kept in
// localStorage. An iOS homescreen app gets its own storage, separate from
// Safari's, so the form is the fallback when nothing is stored.
'use strict';

const TOKEN_KEY = 'waterworks.apiToken';
const MAX_ALERTS = 50;

const $ = (id) => document.getElementById(id);
const alerts = new Map(); // `${instance_id}_${attribute}` -> {evt, el, at}

// ── Token ────────────────────────────────────────────────────────────────────

function storedToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; }
}

function storeToken(value) {
  try { localStorage.setItem(TOKEN_KEY, value); } catch { /* private mode: lives for this page only */ }
  memoryToken = value;
}

let memoryToken = storedToken();

(function takeTokenFromUrl() {
  const url = new URL(location.href);
  const given = url.searchParams.get('token');
  if (!given) return;
  storeToken(given);
  url.searchParams.delete('token');
  history.replaceState(null, '', url.pathname + url.search + url.hash);
})();

function authHeaders() {
  return memoryToken ? { Authorization: `Bearer ${memoryToken}` } : {};
}

$('token-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const value = $('token-input').value.trim();
  if (!value) return;
  storeToken(value);
  $('token-input').value = '';
  $('token-form').hidden = true;
  loadReviews();
});

// ── Time ─────────────────────────────────────────────────────────────────────

function ago(date) {
  const s = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (s < 45) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function stamp(el, date) {
  el.dateTime = date.toISOString();
  el.textContent = ago(date);
  el.title = date.toLocaleString();
}

setInterval(() => {
  document.querySelectorAll('time[datetime]').forEach((t) => {
    t.textContent = ago(new Date(t.dateTime));
  });
}, 30000);

// ── Site ─────────────────────────────────────────────────────────────────────

async function loadSite() {
  try {
    const resp = await fetch('/api/site');
    if (!resp.ok) return;
    const site = await resp.json();
    if (site.site_name) {
      $('site-name').textContent = site.site_name;
      document.title = `${site.site_name} Mobile`;
    }
    $('region-name').textContent = site.region_name || '';
  } catch { /* keep the default header */ }
}

// ── Reviews ──────────────────────────────────────────────────────────────────

async function loadReviews() {
  const status = $('reviews-status');
  let resp;
  try {
    resp = await fetch('/api/reviews', { headers: authHeaders(), cache: 'no-store' });
  } catch {
    status.textContent = 'Could not reach the plant.';
    status.hidden = false;
    return;
  }
  if (resp.status === 401) {
    $('token-form').hidden = false;
    status.textContent = memoryToken ? 'That token was refused.' : 'Needs the API token.';
    status.hidden = false;
    return;
  }
  if (!resp.ok) {
    let detail = '';
    try { detail = (await resp.json()).detail || ''; } catch { /* not JSON */ }
    status.textContent = `Review queue unavailable${detail ? `: ${detail}` : '.'}`;
    status.hidden = false;
    return;
  }
  const { reviews } = await resp.json();
  renderReviews(reviews);
}

function renderReviews(reviews) {
  const list = $('reviews');
  list.replaceChildren(...reviews.map(reviewEl));
  $('review-count').textContent = reviews.length ? String(reviews.length) : '';
  const status = $('reviews-status');
  status.textContent = 'Nothing waiting for review.';
  status.hidden = reviews.length > 0;
}

function reviewEl(r) {
  const el = $('review-tpl').content.firstElementChild.cloneNode(true);
  el.querySelector('.tag').textContent = r.category_label;
  el.querySelector('.node').textContent = r.node_id;
  stamp(el.querySelector('.when'), new Date(r.created_at));
  el.querySelector('.note').textContent = r.note || '';
  return el;
}

// ── Alerts ───────────────────────────────────────────────────────────────────

function alertKey(evt) {
  return `${evt.instance_id}_${evt.attribute || 'unknown'}`;
}

function formatReading(evt) {
  const value = typeof evt.value === 'number' ? evt.value.toFixed(2) : String(evt.value ?? '?');
  const nr = Array.isArray(evt.normal_range) ? evt.normal_range.join('–') : String(evt.normal_range ?? '?');
  return `${evt.attribute}: ${value} (normal ${nr})`;
}

function setDiagnosis(el, content, running) {
  const diag = el.querySelector('.diag');
  diag.querySelector('.content').textContent = content || '';
  diag.hidden = !content;
  el.querySelector('.pending').hidden = !running;
}

function upsertAlert(evt, severity) {
  const key = alertKey(evt);
  const existing = alerts.get(key);
  const el = existing ? existing.el : $('alert-tpl').content.firstElementChild.cloneNode(true);

  el.dataset.sev = severity;
  el.querySelector('.sev').textContent = severity;
  el.querySelector('.node').textContent = evt.instance_id;
  el.querySelector('.reading').textContent = formatReading(evt);
  el.querySelector('.reason').textContent = evt.reason || '';
  stamp(el.querySelector('.when'), evt.ts ? new Date(evt.ts) : new Date());
  // The diagnosis arrives later, in reactive_warning_update /
  // reactive_critical_update.
  setDiagnosis(el, evt.content, !evt.content);

  alerts.delete(key);
  alerts.set(key, { el });
  $('alerts').prepend(el);

  while (alerts.size > MAX_ALERTS) {
    const [oldest] = alerts.keys();
    alerts.get(oldest).el.remove();
    alerts.delete(oldest);
  }
  refreshAlertCount();
}

function patchAlertContent(evt) {
  const entry = alerts.get(alertKey(evt));
  if (entry) setDiagnosis(entry.el, evt.content, false);
}

// The live stream only carries what fires while this page is connected; the
// backend keeps the last few so a reload, sleep or app switch loses nothing.
// Its list replaces ours: it has everything we have, plus what we missed.
async function loadAlerts() {
  let resp;
  try {
    resp = await fetch('/api/alerts/recent', { headers: authHeaders(), cache: 'no-store' });
  } catch {
    return; // the connection badge already says the plant is unreachable
  }
  if (!resp.ok) return; // 401 is surfaced by loadReviews' token form
  const { alerts: recent, pending_actions: pending = [] } = await resp.json();
  alerts.forEach(({ el }) => el.remove());
  alerts.clear();
  for (const evt of recent.slice().reverse()) {
    upsertAlert(evt, evt.type === 'reactive_critical' ? 'critical' : 'warning');
  }
  refreshAlertCount();

  actions.forEach((el) => el.remove());
  actions.clear();
  pending.forEach(addAction);
  refreshActions();
}

// ── Actions awaiting approval (read-only) ────────────────────────────────────

const actions = new Map(); // action_id -> element

function addAction(evt) {
  if (!evt.action_id || actions.has(evt.action_id)) return;
  const el = $('action-tpl').content.firstElementChild.cloneNode(true);
  const what = [evt.action_type, evt.target, evt.attribute].filter(Boolean).join(' · ');
  const value = evt.value !== '' && evt.value != null ? ` → ${evt.value}` : '';
  el.querySelector('.what').textContent = (what || 'Control action') + value;
  el.querySelector('.desc').textContent = evt.description || '';
  stamp(el.querySelector('.when'), evt.ts ? new Date(evt.ts) : new Date());
  actions.set(evt.action_id, el);
  $('actions').append(el);
  refreshActions();
}

function removeAction(actionId) {
  const el = actions.get(actionId);
  if (!el) return;
  el.remove();
  actions.delete(actionId);
  refreshActions();
}

function refreshActions() {
  $('action-count').textContent = actions.size ? String(actions.size) : '';
  $('actions-section').hidden = actions.size === 0;
}

function refreshAlertCount() {
  $('alert-count').textContent = alerts.size ? String(alerts.size) : '';
  $('alerts-empty').hidden = alerts.size > 0;
}

// ── Live stream ──────────────────────────────────────────────────────────────

function setConn(state, label) {
  const el = $('conn');
  el.dataset.state = state;
  el.textContent = label;
}

function handleEvent(evt) {
  switch (evt.type) {
    case 'reactive_critical':
      if (evt.instance_id) upsertAlert(evt, 'critical');
      break;
    case 'reactive_warning':
      if (evt.instance_id) upsertAlert(evt, 'warning');
      break;
    case 'reactive_warning_update':
    case 'reactive_critical_update':
      patchAlertContent(evt);
      break;
    case 'action_proposed':
      addAction(evt);
      break;
    case 'action_decision':
      removeAction(evt.action_id);
      break;
    case 'insight_review_created':
      loadReviews();
      break;
    default:
      // ping and reactive_advisory, which the desktop ignores too.
      break;
  }
}

function connect() {
  const qs = memoryToken ? `?token=${encodeURIComponent(memoryToken)}` : '';
  const source = new EventSource(`/api/events${qs}`);
  source.onopen = () => {
    setConn('live', 'live');
    // Catch up on anything that happened while disconnected.
    loadAlerts();
    loadReviews();
  };
  source.onerror = () => setConn('down', 'reconnecting');
  source.onmessage = (msg) => {
    try { handleEvent(JSON.parse(msg.data)); } catch { /* malformed frame */ }
  };
}

// Tap a card to show its full text; tap again to collapse. Taps on the
// Diagnosis disclosure are left to <details>.
document.querySelector('main').addEventListener('click', (e) => {
  if (e.target.closest('summary, .diag')) return;
  const card = e.target.closest('.card');
  if (card && card.querySelector('.clamp')) card.classList.toggle('expanded');
});

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    loadAlerts();
    loadReviews();
  }
});

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(() => { /* works without it */ });
}

loadSite();
loadReviews();
connect();
