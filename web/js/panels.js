// The panels around the map: header, summary cards, selected site with its 48-hour chart and
// drift score, the maintenance list, the event log and the what-if projection.

import { SITES, SITE_BY_NAME, COLORS, LABELS, esc, fmt, signed, percent, stamp } from './sensors.js';

const $ = (id) => document.getElementById(id);

const EVENT_COLORS = {
  calibrated: COLORS.healed,
  detect: COLORS.drift,
  heal: COLORS.healing,
  refit: COLORS.healing,
  dismissed: COLORS.warmup,
  recovered: COLORS.healthy,
  recalibrated: COLORS.healthy,
  inject: '#FB923C',
};

const MIN_TREND_POINTS = 4;

const PHASES = {
  loading: ['Loading data', 'busy'],
  calibrating: ['Calibrating', 'busy'],
  running: ['LIVE · twin running', 'on'],
  paused: ['PAUSED', ''],
  finished: ['Replay finished', ''],
  failed: ['Stopped', 'bad'],
  offline: ['Reconnecting…', 'bad'],
};

export function header(status, connected, selected) {
  let phase = status ? status.phase : 'loading';
  if (!connected) phase = 'offline';
  else if (phase === 'running' && !status.running) phase = 'paused';
  const [label, mode] = PHASES[phase];
  const calibrating = phase === 'calibrating' ? ` · ${Math.min(100, (100 * status.hour) / status.fast_forward_hours).toFixed(0)}%` : '';
  $('live-label').textContent = label + calibrating;
  $('live-dot').className = `live-dot ${mode}`;
  $('sim-time').textContent = status && status.time ? stamp(status.time) : '–';
  const live = connected && status && status.phase === 'running';
  $('play').textContent = status && !status.running ? 'Resume' : 'Pause';
  $('play').disabled = !live;
  $('inject').textContent = `Inject drift into ${selected}`;
  $('inject').disabled = !live;
}

export function summary(status, sensors, network) {
  const count = (cls) => sensors.filter((s) => s.cls === cls).length;
  $('c-readings').textContent = status ? status.readings.toLocaleString('en-US') : '–';
  $('c-healthy').textContent = count('healthy') + count('watch');
  const watch = count('watch');
  $('c-healthy-sub').textContent = watch ? `twin and sensor agree · ${watch} on watch` : 'twin and sensor agree';
  $('c-drift').textContent = count('drift');
  $('c-healed').textContent = count('healing') + count('healed');
  $('c-rmse-twin').textContent = network ? fmt(network.rmse_published, 2) : '–';
  $('c-rmse-raw').textContent = network ? fmt(network.rmse_raw, 2) : '–';
  const clean = network && network.rmse_raw === 0;
  $('c-rmse-window').textContent = !network || !network.window_hours
    ? 'no data yet'
    : `last ${network.window_hours} h${clean ? ' · no drift injected, raw = original' : ''}`;
}

/** The 12 site buttons; built once, then only their state changes. */
export function chips(byName, selected, onPick) {
  const box = $('chips');
  if (!box.children.length) {
    for (const site of SITES) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'chip';
      button.dataset.site = site.name;
      button.innerHTML = `<span class="dot"></span>${esc(site.name)}`;
      button.addEventListener('click', () => onPick(site.name));
      box.append(button);
    }
  }
  for (const button of box.children) {
    const s = byName.get(button.dataset.site);
    const cls = s ? s.cls : 'warmup';
    button.style.setProperty('--c', COLORS[cls]);
    button.setAttribute('aria-pressed', String(button.dataset.site === selected));
    button.setAttribute('aria-label', `${button.dataset.site}: ${LABELS[cls]}`);
  }
}

export function site(sensor, name) {
  const meta = SITE_BY_NAME.get(name);
  $('site-name').textContent = name;
  const injected = sensor && sensor.injected ? ' · drift injected' : '';
  $('site-zone').textContent = `${meta.zone} · PM2.5 site${injected}`;
  const cls = sensor ? sensor.cls : 'warmup';
  const pill = $('site-status');
  pill.textContent = LABELS[cls];
  pill.style.setProperty('--c', COLORS[cls]);
  $('v-raw').textContent = sensor ? fmt(sensor.raw) : '–';
  $('v-exp').textContent = sensor ? fmt(sensor.expected) : '–';
  $('v-cor').textContent = sensor ? fmt(sensor.corrected) : '–';
  const corrected = sensor && (cls === 'healing' || cls === 'healed');
  $('v-corr').textContent = corrected ? `gain ${fmt(sensor.gain, 3)} · offset ${signed(sensor.offset)}` : 'none';
  const score = sensor && sensor.score !== null ? sensor.score : 0;
  $('score-value').textContent = fmt(score, 2);
  const gauge = $('gauge');
  gauge.setAttribute('aria-valuenow', score.toFixed(2));
  gauge.style.setProperty('--c', COLORS[cls]);
  $('gauge-fill').style.width = `${Math.min(100, (score / 2) * 100).toFixed(1)}%`;
}

/** A round axis maximum above the largest value. */
function niceMax(value) {
  const target = Math.max(value * 1.1, 20);
  const step = 10 ** Math.floor(Math.log10(target));
  return Math.ceil(target / (step / 2)) * (step / 2);
}

/** 48-hour chart: raw, expected and corrected, the drift gap shaded, the latest detection marked. */
export function chart(frames, name, events) {
  const svg = $('chart');
  const series = frames.map((f) => ({ time: f.time, s: f.sensors.find((x) => x.site === name) })).filter((p) => p.s);
  if (series.length < 2) {
    svg.innerHTML = '<text x="180" y="104" text-anchor="middle" class="chart-tick">waiting for data</text>';
    return;
  }
  const H = 48;
  const values = series.flatMap((p) => [p.s.raw, p.s.expected, p.s.corrected]).filter((v) => v !== null);
  const ymax = niceMax(Math.max(...values));
  const off = H - series.length;
  const x = (n) => ((n + off) * 356) / (H - 1);
  const y = (v) => 178 - (Math.min(ymax, Math.max(0, v)) / ymax) * 160;
  const path = (key) => {
    let d = '';
    let pen = 'M';
    series.forEach((p, n) => {
      const v = p.s[key];
      if (v === null) { pen = 'M'; return; }
      d += `${pen}${x(n).toFixed(1)} ${y(v).toFixed(1)} `;
      pen = 'L';
    });
    return d.trim();
  };
  const both = series.map((p, n) => ({ n, raw: p.s.raw, exp: p.s.expected })).filter((p) => p.raw !== null && p.exp !== null);
  const gap = both.map((p) => `${x(p.n).toFixed(1)},${y(p.raw).toFixed(1)}`)
    .concat(both.slice().reverse().map((p) => `${x(p.n).toFixed(1)},${y(p.exp).toFixed(1)}`)).join(' ');
  const cor = series.map((p, n) => ({ n, v: p.s.corrected })).filter((p) => p.v !== null);
  const area = cor.length ? `M${cor.map((p) => `${x(p.n).toFixed(1)} ${y(p.v).toFixed(1)}`).join(' L')} L${x(cor[cor.length - 1].n).toFixed(1)} 178 L${x(cor[0].n).toFixed(1)} 178 Z` : '';
  const grid = [0, ymax / 2, ymax].map((v) => `<line x1="0" y1="${y(v).toFixed(1)}" x2="360" y2="${y(v).toFixed(1)}" stroke="#16213C"/>`).join('');
  const ticks = [ymax / 2, ymax].map((v) => `<text x="6" y="${(y(v) - 3).toFixed(1)}" class="chart-tick">${v.toFixed(0)}</text>`).join('');
  const sensor = `${name}:pm25`;
  const first = series[0].time;
  const detect = events.find((e) => e.kind === 'detect' && e.sensor === sensor && e.time >= first);
  let mark = '';
  if (detect) {
    const n = series.findIndex((p) => p.time === detect.time);
    if (n >= 0) {
      const mx = x(n).toFixed(1);
      mark = `<line x1="${mx}" y1="16" x2="${mx}" y2="178" stroke="#F59E0B" stroke-width="1.2" stroke-dasharray="3 3"/><text x="${mx}" y="12" text-anchor="middle" class="chart-mark">drift detected</text>`;
    }
  }
  const last = cor.length ? cor[cor.length - 1] : null;
  svg.innerHTML = `<defs><linearGradient id="corFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#60A5FA" stop-opacity="0.3"/><stop offset="100%" stop-color="#60A5FA" stop-opacity="0"/></linearGradient></defs>
    ${grid}
    <path d="${area}" fill="url(#corFill)"/>
    <polygon points="${gap}" fill="#F59E0B" fill-opacity="0.16"/>
    <path d="${path('expected')}" fill="none" stroke="#2DD4BF" stroke-width="2" stroke-dasharray="5 4"/>
    <path d="${path('raw')}" fill="none" stroke="#F59E0B" stroke-width="2"/>
    <path d="${path('corrected')}" fill="none" stroke="#60A5FA" stroke-width="2.5"/>
    ${mark}
    ${last ? `<circle cx="${x(last.n).toFixed(1)}" cy="${y(last.v).toFixed(1)}" r="4" fill="#60A5FA"/>` : ''}
    ${ticks}
    <text x="6" y="196" class="chart-tick">−${series.length} h</text>
    <text x="354" y="196" text-anchor="end" class="chart-tick">now</text>`;
}

/**
 * The ranked maintenance list. Items are rebuilt only when the ranking changes; otherwise
 * their numbers are updated in place, so a button is never replaced while it is being used.
 */
export function maintenance(items, byName, onRecalibrate) {
  const list = $('maint');
  const shown = items.slice(0, 5);
  if (!shown.length) {
    list.dataset.order = '';
    list.innerHTML = '<li class="empty">No sensor needs a field visit: every correction is small or none is active.</li>';
    return;
  }
  const order = shown.map((i) => i.sensor).join('|');
  if (list.dataset.order !== order) {
    list.dataset.order = order;
    list.innerHTML = shown.map((item) => `<li class="maint-item">
      <div class="maint-rank">${item.rank}</div>
      <div class="maint-body">
        <div class="maint-name">${esc(item.sensor.split(':')[0])} <span class="mono" data-field="error"></span></div>
        <div class="maint-reason" data-field="reason"></div>
        <div class="maint-bar"><div data-field="bar"></div></div>
      </div>
      <button class="btn btn-violet" type="button" data-sensor="${esc(item.sensor)}">Mark recalibrated</button>
    </li>`).join('');
    for (const button of list.querySelectorAll('button[data-sensor]')) {
      button.addEventListener('click', () => {
        button.disabled = true;
        onRecalibrate(button.dataset.sensor);
      });
    }
  }
  const worst = Math.max(...shown.map((i) => Math.abs(i.relative_error || 0)), 0.01);
  shown.forEach((item, n) => {
    const li = list.children[n];
    const s = byName.get(item.sensor.split(':')[0]);
    li.style.setProperty('--c', COLORS[s ? s.cls : 'healed']);
    li.querySelector('[data-field="error"]').textContent = percent(item.relative_error);
    li.querySelector('[data-field="reason"]').textContent = item.reason;
    li.querySelector('[data-field="bar"]').style.width = `${((Math.abs(item.relative_error || 0) / worst) * 100).toFixed(0)}%`;
  });
}

export function eventLog(events, seen) {
  const list = $('events');
  if (!events.length) {
    list.innerHTML = '<li class="empty">No events yet.</li>';
    return;
  }
  list.innerHTML = events.slice(0, 8).map((e) => {
    const who = e.sensor ? `${e.sensor.split(':')[0]}: ` : '';
    const fresh = e.id > seen ? ' event-new' : '';
    return `<li class="${fresh.trim()}" style="--c: ${EVENT_COLORS[e.kind] || COLORS.healed}">
      <span class="event-dot"></span>
      <div><div class="event-text">${esc(who + e.message)}</div><div class="event-time">${stamp(e.time)} · ${esc(e.kind)}</div></div>
    </li>`;
  }).join('');
}

/** Mean absolute error of the published values against the original data, relative to it. */
function measuredError(frames, name) {
  let err = 0;
  let level = 0;
  for (const f of frames) {
    const s = f.sensors.find((x) => x.site === name);
    if (s && s.corrected !== null && s.truth !== null) {
      err += Math.abs(s.corrected - s.truth);
      level += Math.abs(s.truth);
    }
  }
  return level > 0 ? err / level : null;
}

export function whatIf(result, days, name, frames) {
  $('days-value').textContent = `${days} ${days === 1 ? 'day' : 'days'}`;
  $('whatif-sub').textContent = `Error at ${name} if nobody visits it, projected from the trend of its corrections`;
  // The healer refits once a day, so a trend from fewer fits mixes the first offset-only fit
  // with the later gain fit; the projection is shown once there is a few days' history.
  const early = result && result.points_used > 1 && result.points_used < MIN_TREND_POINTS;
  const projected = result && result.projections.length && !early ? result.projections[0].relative_error : null;
  const measured = measuredError(frames, name);
  const scale = Math.max(Math.abs(projected || 0), Math.abs(measured || 0), 0.05);
  $('wi-raw').textContent = early ? 'too early' : projected === null ? '–' : percent(projected, 1);
  $('wi-twin').textContent = measured === null ? '–' : `±${(measured * 100).toFixed(1)}%`;
  $('wi-raw-bar').style.width = `${((Math.abs(projected || 0) / scale) * 100).toFixed(1)}%`;
  $('wi-twin-bar').style.width = `${((Math.abs(measured || 0) / scale) * 100).toFixed(1)}%`;
  if (!result) {
    $('wi-basis').textContent = 'The projection appears once the twin is running.';
  } else if (!result.points_used) {
    $('wi-basis').textContent = `${name} has no active correction, so the twin projects no error growth. Inject a drift to see the projection change.`;
  } else if (early) {
    $('wi-basis').textContent = `So far a ${result.basis}: the correction is refitted once a day, and the projection is shown from ${MIN_TREND_POINTS} corrections on. The twin already publishes corrected values.`;
  } else {
    $('wi-basis').textContent = `Based on ${result.basis}. The twin keeps publishing corrected values meanwhile, so the city can schedule the visit instead of rushing it.`;
  }
}
