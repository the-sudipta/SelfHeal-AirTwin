// The city drawn in SVG: ground, ring roads, landmarks and buildings (redrawn when the camera
// moves), and the live layer of sites, data flows, hazes and the callout (redrawn every tick).
// Geometry is approximate and for illustration; it carries no measured values.

import { uv, WIDTH, HEIGHT, clamp } from './camera.js';
import { SITES, COLORS, LABELS, esc, fmt, signed } from './sensors.js';

const PALETTE = {
  normal: { top: '#2A3D66', dark: '#15213A', light: '#1C2B4B', edge: '#2E4270' },
  glass: { top: '#3D5F9C', dark: '#17284A', light: '#22386A', edge: '#7FB0F0' },
  palace: { top: '#C2410C', dark: '#7C2D12', light: '#9A3412', edge: '#FBBF24' },
};

/** Small deterministic generator, so the city looks the same on every visit. */
function rng(seed) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const pts = (list) => list.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
const near = (u, v, c, r) => Math.hypot(u - c[0], v - c[1]) < r;

function rectUV(w, e, s, n) {
  const a = uv(w, s);
  const b = uv(e, n);
  return [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]];
}

function ellipseUV(c, ru, rv) {
  const out = [];
  for (let n = 0; n < 24; n++) {
    const t = (n / 24) * 2 * Math.PI;
    out.push([c[0] + ru * Math.cos(t), c[1] + rv * Math.sin(t)]);
  }
  return out;
}

/** World model of central Beijing in km (u east, v north) with building heights in px. */
export function buildWorld() {
  const r = rng(19);
  const palaceC = uv(116.397, 39.918);
  const heaven = uv(116.407, 39.882);
  const olympic = uv(116.39, 40.017);
  const chaoyang = uv(116.478, 39.94);
  const kunming = uv(116.268, 39.995);
  const houhai = uv(116.385, 39.932);
  const yuyuan = uv(116.315, 39.918);
  const nest = uv(116.3905, 39.992);
  const blocked = (u, v) => (Math.abs(u - palaceC[0]) < 0.75 && Math.abs(v - palaceC[1]) < 0.8)
    || near(u, v, heaven, 1.0) || (Math.abs(u - olympic[0]) < 1.1 && Math.abs(v - olympic[1]) < 1.6)
    || near(u, v, chaoyang, 0.9) || near(u, v, kunming, 1.7) || near(u, v, houhai, 0.9)
    || near(u, v, yuyuan, 0.7) || near(u, v, nest, 0.8);
  const hubs = [
    { c: uv(116.461, 39.91), h: 150, r: 2.0, glass: true },
    { c: uv(116.357, 39.916), h: 70, r: 1.4, glass: true },
    { c: uv(116.315, 39.983), h: 55, r: 1.8 },
    { c: uv(116.47, 39.995), h: 60, r: 1.6 },
    { c: uv(116.31, 39.865), h: 45, r: 1.4 },
  ];
  const W = uv(116.205, 39.77);
  const E = uv(116.553, 40.02);
  const buildings = [];
  const step = 1.45;
  for (let u = W[0] + 0.4; u < E[0]; u += step) {
    for (let v = W[1] + 0.4; v < E[1]; v += step) {
      const cu = u + step / 2;
      const cv = v + step / 2;
      if (blocked(cu, cv)) continue;
      const d = Math.hypot(cu, cv);
      if (d > 9 && r() < 0.3) continue;
      let h = d < 4.5 ? 8 + r() * 10 : d < 8 ? 18 + r() * 28 : 12 + r() * 26;
      let glass = false;
      for (const hub of hubs) {
        const dd = Math.hypot(cu - hub.c[0], cv - hub.c[1]);
        if (dd < hub.r) {
          h += hub.h * (1 - dd / hub.r) * (0.6 + r() * 0.6);
          glass = glass || Boolean(hub.glass);
        }
      }
      const f = 0.42 + r() * 0.3;
      const ou = (1 - f) * step * r();
      const ov = (1 - f) * step * r();
      buildings.push({ u0: u + ou, v0: v + ov, u1: u + ou + f * step, v1: v + ov + f * step, h, kind: glass ? 'glass' : 'normal' });
    }
  }
  for (let n = 0; n < 5; n++) {
    const u = palaceC[0] - 0.45 + (n % 2) * 0.5;
    const v = palaceC[1] - 0.6 + n * 0.28;
    buildings.push({ u0: u, v0: v, u1: u + 0.4, v1: v + 0.18, h: 6, kind: 'palace' });
  }
  const line = (list) => list.map((p) => uv(p[0], p[1]));
  const rings = [
    [116.357, 116.434, 39.868, 39.948, 0.75],
    [116.31, 116.461, 39.852, 39.967, 0.6],
    [116.272, 116.49, 39.836, 39.988, 0.5],
    [116.205, 116.553, 39.77, 40.02, 0.4],
  ].map((q) => ({ pts: rectUV(q[0], q[1], q[2], q[3]), o: q[4] }));
  const changan = line([[116.205, 39.907], [116.553, 39.907]]);
  const axis = line([[116.3975, 39.858], [116.3975, 40.01]]);
  return {
    buildings,
    plate: rectUV(116.16, 116.59, 39.745, 40.045),
    rings,
    greens: [
      rectUV(116.4, 116.416, 39.875, 39.889),
      rectUV(116.378, 116.402, 40.002, 40.03),
      rectUV(116.47, 116.487, 39.933, 39.947),
      rectUV(116.255, 116.285, 39.985, 40.008),
    ],
    lakes: [ellipseUV(kunming, 0.8, 1.1), ellipseUV(houhai, 0.35, 0.9), ellipseUV(yuyuan, 0.55, 0.3)],
    palace: rectUV(116.3905, 116.4035, 39.9125, 39.924),
    nest: ellipseUV(nest, 0.35, 0.25),
    changan,
    axis,
    roads: [changan, axis, ...rings.slice(0, 3).map((q) => [...q.pts, q.pts[0]])],
    landmarks: [
      ['Forbidden City', 116.397, 39.918, 26],
      ['CBD · Guomao', 116.461, 39.909, 172],
      ['Olympic Park', 116.39, 40.022, 22],
      ['Summer Palace', 116.268, 40.0, 30],
      ['Temple of Heaven', 116.407, 39.882, 20],
      ['Financial Street', 116.357, 39.916, 92],
      ['Zhongguancun', 116.315, 39.983, 78],
    ].map((m) => ({ name: m[0], q: uv(m[1], m[2]), up: m[3] })),
    core: uv(116.397, 39.918),
    sites: new Map(SITES.filter((s) => s.map).map((s) => [s.name, uv(s.lon, s.lat)])),
  };
}

/** Plate, parks, water, ring roads, traffic and the two historic sites. */
export function ground(world, pr, view, motion) {
  const P = pr.P;
  const poly = (list) => pts(list.map((q) => P(q[0], q[1])));
  const pc = world.plate;
  const sides = pr.faces.map((f) => {
    const p = [P(pc[f.a][0], pc[f.a][1]), P(pc[f.b][0], pc[f.b][1]), P(pc[f.b][0], pc[f.b][1], -14), P(pc[f.a][0], pc[f.a][1], -14)];
    return `<polygon points="${pts(p)}" fill="${f.lit ? '#0C1528' : '#070E1C'}"/>`;
  });
  const seg = (l, attrs) => {
    const a = P(l[0][0], l[0][1]);
    const b = P(l[1][0], l[1][1]);
    return `<line x1="${a[0].toFixed(1)}" y1="${a[1].toFixed(1)}" x2="${b[0].toFixed(1)}" y2="${b[1].toFixed(1)}" ${attrs}/>`;
  };
  const glowRx = 380 * view.zoom;
  const glowRy = glowRx * Math.sin((view.elev * Math.PI) / 180);
  const out = [
    ...sides,
    `<polygon points="${poly(pc)}" fill="#0F1B33" stroke="#24365C" stroke-width="1.5"/>`,
    `<ellipse cx="${pr.centre[0].toFixed(1)}" cy="${pr.centre[1].toFixed(1)}" rx="${glowRx.toFixed(0)}" ry="${glowRy.toFixed(0)}" fill="url(#cityGlow)"/>`,
    ...world.greens.map((g) => `<polygon points="${poly(g)}" fill="#123A35" stroke="#1E5A4E"/>`),
    ...world.lakes.map((l) => `<polygon points="${poly(l)}" fill="#1B4C86" fill-opacity="0.85" stroke="#3B82F6" stroke-opacity="0.5"/>`),
    ...world.rings.map((q) => `<polygon points="${poly(q.pts)}" fill="none" stroke="#F59E0B" stroke-opacity="0.16" stroke-width="7" filter="url(#soft)"/><polygon points="${poly(q.pts)}" fill="none" stroke="#FCD34D" stroke-opacity="${q.o}" stroke-width="1.6"/>`),
    seg(world.changan, 'stroke="#FDE68A" stroke-opacity="0.55" stroke-width="1.6"'),
    seg(world.axis, 'stroke="#FCA5A5" stroke-opacity="0.45" stroke-width="1.2" stroke-dasharray="5 5"'),
  ];
  if (motion) {
    world.roads.forEach((road, n) => {
      const d = 'M' + road.map((q) => P(q[0], q[1]).map((x) => x.toFixed(1)).join(' ')).join(' L');
      for (let m = 0; m < 3; m++) {
        out.push(`<circle r="1.8" fill="${m === 1 ? '#FCA5A5' : '#FDE68A'}"><animateMotion dur="${10 + n * 3}s" begin="${m * (3 + n)}s" repeatCount="indefinite" path="${d}"/></circle>`);
      }
    });
  }
  out.push(`<polygon points="${poly(world.palace)}" fill="#5B1A1A" stroke="#F87171" stroke-opacity="0.8" stroke-width="1.2"/>`);
  out.push(`<polygon points="${poly(world.nest)}" fill="#1E293B" stroke="#CBD5E1" stroke-width="2" stroke-dasharray="2 2"/>`);
  return out.join('');
}

/** Extruded buildings, back to front, with lit and shaded sides. */
export function buildings(world, pr) {
  const P = pr.P;
  return world.buildings
    .map((b) => {
      const cs = [[b.u0, b.v0], [b.u1, b.v0], [b.u1, b.v1], [b.u0, b.v1]];
      const pal = PALETTE[b.kind];
      const side = (f) => pts([P(cs[f.a][0], cs[f.a][1]), P(cs[f.b][0], cs[f.b][1]), P(cs[f.b][0], cs[f.b][1], b.h), P(cs[f.a][0], cs[f.a][1], b.h)]);
      const faces = pr.faces.slice(0, 2).map((f) => `<polygon points="${side(f)}" fill="${f.lit ? pal.light : pal.dark}"/>`).join('');
      const top = `<polygon points="${pts(cs.map((q) => P(q[0], q[1], b.h)))}" fill="${pal.top}" stroke="${pal.edge}" stroke-width="0.6"/>`;
      return { d: pr.depth((b.u0 + b.u1) / 2, (b.v0 + b.v1) / 2), svg: faces + top };
    })
    .sort((a, b) => b.d - a.d)
    .map((b) => b.svg)
    .join('');
}

/** Landmark labels on thin poles. */
export function landmarks(world, pr) {
  return world.landmarks
    .map((m) => {
      const g = pr.P(m.q[0], m.q[1]);
      const top = g[1] - m.up * pr.hz;
      return `<circle cx="${g[0].toFixed(1)}" cy="${g[1].toFixed(1)}" r="2.5" fill="#E6EDF7"/><line x1="${g[0].toFixed(1)}" y1="${g[1].toFixed(1)}" x2="${g[0].toFixed(1)}" y2="${top.toFixed(1)}" stroke="#E6EDF7" stroke-opacity="0.35"/><text x="${g[0].toFixed(1)}" y="${(top - 4).toFixed(1)}" text-anchor="middle" class="map-landmark">${esc(m.name)}</text>`;
    })
    .join('');
}

/** Where the Twin Core floats for this view. */
export function corePosition(world, pr) {
  const g = pr.P(world.core[0], world.core[1]);
  return { gx: g[0], gy: g[1], x: g[0], y: g[1] - (130 + 120 * pr.hz) };
}

/** The Twin Core: the virtual city that predicts, compares, heals and sends feedback. */
export function core(world, pr, motion) {
  const c = corePosition(world, pr);
  const ring = pts(ellipseUV(world.core, 2.2, 2.2).map((q) => pr.P(q[0], q[1])));
  const gem = (r) => pts([[c.x, c.y - r], [c.x + r, c.y], [c.x, c.y + r], [c.x - r, c.y]]);
  const anim = (inner) => (motion ? inner : '');
  return [
    `<line x1="${c.x.toFixed(1)}" y1="${c.y.toFixed(1)}" x2="${c.gx.toFixed(1)}" y2="${c.gy.toFixed(1)}" stroke="url(#beam)" stroke-width="10"/>`,
    `<polygon points="${ring}" fill="none" stroke="#2DD4BF" stroke-width="1.4" stroke-dasharray="6 8">${anim('<animate attributeName="stroke-dashoffset" values="0;-56" dur="6s" repeatCount="indefinite"/>')}</polygon>`,
    `<polygon points="${gem(22)}" fill="#2DD4BF" fill-opacity="0.4" filter="url(#glow)"/>`,
    `<polygon points="${gem(15)}" fill="#0B1220" stroke="#2DD4BF" stroke-width="2"/>`,
    `<circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" r="5" fill="#99F6E4">${anim('<animate attributeName="r" values="4;7;4" dur="4s" repeatCount="indefinite"/>')}</circle>`,
    `<ellipse cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" rx="34" ry="11" fill="none" stroke="#2DD4BF" stroke-opacity="0.6" stroke-width="1.2">${anim('<animate attributeName="rx" values="26;40;26" dur="4s" repeatCount="indefinite"/>')}</ellipse>`,
    `<rect x="${(c.x - 118).toFixed(1)}" y="${(c.y - 62).toFixed(1)}" width="236" height="44" rx="10" fill="#08111F" fill-opacity="0.88" stroke="#2DD4BF" stroke-opacity="0.5"/>`,
    `<text x="${c.x.toFixed(1)}" y="${(c.y - 38).toFixed(1)}" text-anchor="middle" class="map-core-title">TWIN CORE · the virtual city</text>`,
    `<text x="${c.x.toFixed(1)}" y="${(c.y - 22).toFixed(1)}" text-anchor="middle" class="map-core-sub">predicts · compares · heals · sends feedback</text>`,
  ].join('');
}

/** Amber haze under every site the twin no longer trusts. */
export function hazes(world, pr, view, sensors) {
  return sensors
    .filter((s) => world.sites.has(s.site) && (s.cls === 'drift' || s.cls === 'healing'))
    .map((s) => {
      const q = world.sites.get(s.site);
      const g = pr.P(q[0], q[1]);
      const rx = 46 * view.zoom;
      const ry = rx * Math.max(0.3, Math.sin((view.elev * Math.PI) / 180));
      return `<ellipse cx="${g[0].toFixed(1)}" cy="${g[1].toFixed(1)}" rx="${rx.toFixed(0)}" ry="${ry.toFixed(0)}" fill="${COLORS[s.cls]}" fill-opacity="0.35" filter="url(#haze)"/>`;
    })
    .join('');
}

/** Site pins with their published value and the flows to and from the Twin Core. */
export function pins(world, pr, sensors, selected, motion) {
  const c = corePosition(world, pr);
  const height = 18 + 30 * pr.hz;
  const hits = [];
  const svg = sensors
    .filter((s) => world.sites.has(s.site))
    .map((s, n) => {
      const q = world.sites.get(s.site);
      const g = pr.P(q[0], q[1]);
      const ty = g[1] - height;
      hits.push({ site: s.site, x: g[0], y: ty });
      const color = COLORS[s.cls];
      const mx = (g[0] + c.x) / 2;
      const my = Math.min(ty, c.y) - 70;
      const arc = `M${g[0].toFixed(1)} ${ty.toFixed(1)} Q${mx.toFixed(1)} ${my.toFixed(1)} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`;
      const back = `M${c.x.toFixed(1)} ${c.y.toFixed(1)} Q${mx.toFixed(1)} ${my.toFixed(1)} ${g[0].toFixed(1)} ${ty.toFixed(1)}`;
      const label = `${s.site} · ${fmt(s.corrected, 0)}`;
      const lw = label.length * 6.8 + 16;
      const b1 = `${(n * 0.31).toFixed(2)}s`;
      const b2 = `${(n * 0.31 + 2.6).toFixed(2)}s`;
      const corrected = s.cls === 'healing' || s.cls === 'healed';
      const parts = [`<path d="${arc}" fill="none" stroke="${color}" stroke-opacity="0.35" stroke-width="1.2" stroke-dasharray="2 6"/>`];
      if (motion) {
        parts.push(`<circle r="3.2" fill="${color}"><animateMotion dur="5.2s" begin="${b1}" repeatCount="indefinite" path="${arc}"/></circle>`);
        parts.push(`<circle r="3.2" fill="${color}"><animateMotion dur="5.2s" begin="${b2}" repeatCount="indefinite" path="${arc}"/></circle>`);
        if (corrected) {
          parts.push(`<rect x="-4.5" y="-4.5" width="9" height="9" transform="rotate(45)" fill="#C4B5FD"><animateMotion dur="4.4s" begin="${b1}" repeatCount="indefinite" path="${back}"/></rect>`);
        }
        parts.push(`<ellipse cx="${g[0].toFixed(1)}" cy="${g[1].toFixed(1)}" rx="6" ry="3.5" fill="none" stroke="${color}" stroke-width="1.5"><animate attributeName="rx" values="6;26" dur="4.4s" begin="${b1}" repeatCount="indefinite"/><animate attributeName="ry" values="3.5;15" dur="4.4s" begin="${b1}" repeatCount="indefinite"/><animate attributeName="opacity" values="0.9;0" dur="4.4s" begin="${b1}" repeatCount="indefinite"/></ellipse>`);
      } else if (corrected) {
        parts.push(`<rect x="${(mx - 4.5).toFixed(1)}" y="${(my + 30).toFixed(1)}" width="9" height="9" fill="#C4B5FD" transform="rotate(45 ${mx.toFixed(1)} ${(my + 34.5).toFixed(1)})"/>`);
      }
      parts.push(`<line x1="${g[0].toFixed(1)}" y1="${g[1].toFixed(1)}" x2="${g[0].toFixed(1)}" y2="${ty.toFixed(1)}" stroke="${color}" stroke-opacity="0.35" stroke-width="7" filter="url(#soft)"/>`);
      parts.push(`<line x1="${g[0].toFixed(1)}" y1="${g[1].toFixed(1)}" x2="${g[0].toFixed(1)}" y2="${ty.toFixed(1)}" stroke="${color}" stroke-opacity="0.9" stroke-width="2"/>`);
      if (s.site === selected) {
        const spin = motion ? `<animateTransform attributeName="transform" type="rotate" from="0 ${g[0].toFixed(1)} ${ty.toFixed(1)}" to="360 ${g[0].toFixed(1)} ${ty.toFixed(1)}" dur="12s" repeatCount="indefinite"/>` : '';
        parts.push(`<circle cx="${g[0].toFixed(1)}" cy="${ty.toFixed(1)}" r="16" fill="none" stroke="#E6EDF7" stroke-width="1.5" stroke-dasharray="4 3">${spin}</circle>`);
      }
      parts.push(`<circle cx="${g[0].toFixed(1)}" cy="${ty.toFixed(1)}" r="11" fill="${color}" fill-opacity="0.35" filter="url(#glow)"/>`);
      parts.push(`<circle cx="${g[0].toFixed(1)}" cy="${ty.toFixed(1)}" r="7.5" fill="${color}" stroke="#0B1220" stroke-width="2.5"/>`);
      parts.push(`<rect x="${(g[0] - lw / 2).toFixed(1)}" y="${(ty - 38).toFixed(1)}" width="${lw.toFixed(0)}" height="21" rx="7" fill="#08111F" fill-opacity="0.9" stroke="${color}" stroke-opacity="0.65"/>`);
      parts.push(`<text x="${g[0].toFixed(1)}" y="${(ty - 24).toFixed(1)}" text-anchor="middle" class="map-pin">${esc(label)}</text>`);
      return `<g>${parts.join('')}</g>`;
    })
    .join('');
  return { svg, hits, height };
}

/** The card pointing at the site the story is about, with its live numbers. */
export function callout(world, pr, sensor, story, height) {
  if (!sensor || !world.sites.has(sensor.site)) return '';
  const q = world.sites.get(sensor.site);
  const g = pr.P(q[0], q[1]);
  const py = g[1] - height;
  const bx = clamp(g[0] + 34, 8, WIDTH - 204);
  const by = clamp(py - 110, 8, HEIGHT - 94);
  const corrected = sensor.cls === 'healing' || sensor.cls === 'healed';
  const last = corrected
    ? `gain ${fmt(sensor.gain, 2)} · offset ${signed(sensor.offset)}`
    : `gap         ${signed(sensor.raw - sensor.expected)}`;
  const color = story.color;
  return [
    `<line x1="${g[0].toFixed(1)}" y1="${py.toFixed(1)}" x2="${bx.toFixed(1)}" y2="${(by + 43).toFixed(1)}" stroke="${color}" stroke-width="1.2"/>`,
    `<rect x="${bx.toFixed(1)}" y="${by.toFixed(1)}" width="196" height="86" rx="10" fill="#08111F" fill-opacity="0.94" stroke="${color}" stroke-width="1.5"/>`,
    `<text x="${(bx + 12).toFixed(1)}" y="${(by + 20).toFixed(1)}" fill="${color}" class="map-callout-title">${esc(sensor.site)} · ${esc(LABELS[sensor.cls])}</text>`,
    `<text x="${(bx + 12).toFixed(1)}" y="${(by + 40).toFixed(1)}" fill="#FBBF24" class="map-callout-line">sensor says  ${fmt(sensor.raw)}</text>`,
    `<text x="${(bx + 12).toFixed(1)}" y="${(by + 57).toFixed(1)}" fill="#5EEAD4" class="map-callout-line">twin expects ${fmt(sensor.expected)}</text>`,
    `<text x="${(bx + 12).toFixed(1)}" y="${(by + 74).toFixed(1)}" fill="#C4B5FD" class="map-callout-line">${esc(last)}</text>`,
  ].join('');
}

/** Plan map of all 12 sites; the dashed box marks the area of the 3D view. */
export function inset(byName, selected) {
  const X = (lon) => 10 + ((lon - 116.15) / 0.55) * 160;
  const Y = (lat) => 140 - ((lat - 39.85) / 0.5) * 130;
  const box = `<rect x="${X(116.205).toFixed(1)}" y="${Y(40.02).toFixed(1)}" width="${(X(116.553) - X(116.205)).toFixed(1)}" height="${(Y(39.77) - Y(40.02)).toFixed(1)}" rx="4" fill="#2DD4BF" fill-opacity="0.06" stroke="#2DD4BF" stroke-opacity="0.5" stroke-dasharray="3 3"/>`;
  const dots = SITES.map((site) => {
    const s = byName.get(site.name);
    const x = X(site.lon);
    const y = Y(site.lat);
    const right = site.lon < 116.5;
    const color = COLORS[s ? s.cls : 'warmup'];
    const r = site.name === selected ? 5 : 3.5;
    return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r}" fill="${color}" stroke="#08111F"/><text x="${(right ? x + 6 : x - 6).toFixed(1)}" y="${(y + 3).toFixed(1)}" text-anchor="${right ? 'start' : 'end'}" class="inset-label">${esc(site.name)}</text>`;
  });
  return box + dots.join('');
}
