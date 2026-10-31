// Project page: reveal sections on scroll and build the results tables from the reference CSVs.

const TABLES = 'results/tables/';
const METHODS = [
  ['raw', 'Raw'],
  ['one_time', 'One-time calibration'],
  ['rolling', 'Rolling recalibration'],
  ['kalman', 'Kalman gain tracking'],
  ['selfheal', 'SelfHeal-AirTwin'],
];
const KINDS = ['step', 'linear', 'exponential'];

function reveal() {
  const sections = document.querySelectorAll('.reveal');
  if (!('IntersectionObserver' in window)) {
    sections.forEach((s) => s.classList.add('shown'));
    return;
  }
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        entry.target.classList.add('shown');
        observer.unobserve(entry.target);
      }
    }
  }, { rootMargin: '0px 0px -10% 0px' });
  sections.forEach((s) => observer.observe(s));
}

/** Parse a simple CSV (no quoted fields) into objects; numeric fields become numbers. */
async function csv(name) {
  const response = await fetch(TABLES + name);
  if (!response.ok) throw new Error(`${name}: ${response.status}`);
  const [head, ...rows] = (await response.text()).trim().split(/\r?\n/);
  const keys = head.split(',');
  return rows.map((row) => Object.fromEntries(row.split(',').map((v, i) => [keys[i], v !== '' && !Number.isNaN(Number(v)) ? Number(v) : v])));
}

const fixed = (v, d = 1) => v.toFixed(d);

function table(headers, rows) {
  const head = headers.map((h) => `<th scope="col">${h}</th>`).join('');
  const body = rows.map((cells) => `<tr>${cells.map((c, i) => (i === 0
    ? `<th scope="row">${c.text}</th>`
    : `<td class="num${c.best ? ' best' : ''}">${c.text}</td>`)).join('')}</tr>`).join('');
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function markBest(cells, values) {
  const best = Math.min(...values);
  return cells.map((c, i) => ({ ...c, best: values[i] === best }));
}

async function results() {
  const [methods, detection, uci] = await Promise.all([
    csv('beijing_methods.csv'), csv('beijing_detection.csv'), csv('uci_methods.csv'),
  ]);

  const rmse = (kind, method) => methods.find((r) => r.kind === kind && r.method === method && r.sensors === 'all');
  document.getElementById('t-methods').innerHTML = table(
    ['Drift', ...METHODS.map((m) => m[1])],
    KINDS.map((kind) => {
      const rows = METHODS.map(([key]) => rmse(kind, key));
      const cells = rows.map((r) => ({ text: `${fixed(r.rmse_mean)} [${fixed(r.rmse_ci_low)}, ${fixed(r.rmse_ci_high)}]` }));
      return [{ text: kind }, ...markBest(cells, rows.map((r) => r.rmse_mean))];
    }),
  );

  const det = (kind) => detection.find((r) => r.kind === kind);
  document.getElementById('t-detection').innerHTML = table(
    ['Drift', 'Recall', 'Precision', 'F1', 'False alarms / 1,000 h', 'Median delay (h)'],
    KINDS.map((kind) => {
      const r = det(kind);
      return [kind, fixed(r.recall_mean, 2), fixed(r.precision_mean, 2), fixed(r.f1_mean, 2), fixed(r.false_alarms_per_1000h_mean, 2), fixed(r.median_delay_h_mean, 0)].map((text) => ({ text }));
    }),
  );

  const sensors = [...new Set(uci.map((r) => r.sensor))];
  document.getElementById('t-uci').innerHTML = table(
    ['Sensor', ...METHODS.map((m) => m[1])],
    sensors.map((sensor) => {
      const rows = METHODS.map(([key]) => uci.find((r) => r.sensor === sensor && r.method === key));
      const cells = rows.map((r) => ({ text: r.rmse >= 10 ? fixed(r.rmse, 1) : fixed(r.rmse, 2) }));
      return [{ text: `${sensor} → ${rows[0].reference}` }, ...markBest(cells, rows.map((r) => r.rmse))];
    }),
  );

  const recall = Math.min(...KINDS.map((k) => det(k).recall_mean));
  const alarms = KINDS.map((k) => det(k).false_alarms_per_1000h_mean);
  const best = KINDS.every((k) => METHODS.every(([key]) => rmse(k, key).rmse_mean >= rmse(k, 'selfheal').rmse_mean));
  const step = rmse('step', 'selfheal').rmse_mean;
  const stepRaw = rmse('step', 'raw').rmse_mean;
  document.getElementById('headline').innerHTML = [
    [`${(recall * 100).toFixed(0)} %`, 'of injected drifts detected, every drift type'],
    [`${fixed(det('step').median_delay_h_mean, 0)} h`, 'median delay for a step drift'],
    [`${fixed(Math.min(...alarms), 2)}–${fixed(Math.max(...alarms), 2)}`, 'false alarms per 1,000 sensor-hours'],
    [`${fixed(step)} vs ${fixed(stepRaw)}`, `µg/m³ RMSE over all sensors, twin vs raw (step)${best ? '; lowest of all methods for every drift type' : ''}`],
  ].map(([value, label]) => `<div class="stat"><b>${value}</b><span>${label}</span></div>`).join('');
}

reveal();
results().catch((error) => {
  for (const id of ['t-methods', 't-detection', 't-uci']) {
    document.getElementById(id).innerHTML = `<p class="muted">Could not load the result tables (${error.message}).</p>`;
  }
});
