// The 3D camera over the city: heading (yaw), tilt (elev), zoom and pan, and the controls
// (drag, Shift-drag or Move mode, wheel, keyboard, buttons) that change them.

const LON0 = 116.397;
const LAT0 = 39.912;
const KM_PER_LON = 85.3;
const KM_PER_LAT = 111.2;
const CU = -1.8; // world point (km) the camera turns around
const CV = -1.3;
const SCALE = 18.37; // screen px per km at zoom 1
const E0 = 35.26; // reference tilt for building heights
export const WIDTH = 960;
export const HEIGHT = 640;
const CX = 491;
const CY = 336;

export const DEFAULT_VIEW = { yaw: 45, elev: 35.26, zoom: 1, panX: 0, panY: 0 };
const ZOOM = [0.6, 3.2];
const TILT = [15, 88];

export const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** Longitude/latitude to world kilometres east (u) and north (v) of the city centre. */
export function uv(lon, lat) {
  return [(lon - LON0) * KM_PER_LON, (lat - LAT0) * KM_PER_LAT];
}

/**
 * Projection for one view: P(u, v, z) gives screen px for a world point at height z (px);
 * depth orders buildings back to front; faces lists the two box sides facing the camera.
 */
export function projection(view) {
  const th = (view.yaw * Math.PI) / 180;
  const e = (view.elev * Math.PI) / 180;
  const c = Math.cos(th);
  const s = Math.sin(th);
  const se = Math.sin(e);
  const k = SCALE * view.zoom;
  const hz = (Math.cos(e) / Math.cos((E0 * Math.PI) / 180)) * view.zoom;
  const P = (u, v, z = 0) => {
    const du = u - CU;
    const dv = v - CV;
    const x = du * c + dv * s;
    const y = -du * s + dv * c;
    return [CX + view.panX + k * x, CY + view.panY - k * y * se - z * hz];
  };
  const depth = (u, v) => -(u - CU) * s + (v - CV) * c;
  const faces = [
    { n: [0, -1], a: 0, b: 1 },
    { n: [1, 0], a: 1, b: 2 },
    { n: [0, 1], a: 2, b: 3 },
    { n: [-1, 0], a: 3, b: 0 },
  ]
    .filter((f) => -f.n[0] * s + f.n[1] * c < 0)
    .map((f) => ({ a: f.a, b: f.b, lit: f.n[0] * c + f.n[1] * s >= 0 }));
  const centre = P(CU, CV);
  const north = P(CU, CV + 1);
  const compass = (Math.atan2(north[0] - centre[0], centre[1] - north[1]) * 180) / Math.PI;
  return { P, depth, faces, hz, k, compass, centre };
}

/** Owns the view and turns user input on the map into view changes. */
export class Camera {
  constructor(svg, onChange, onPick) {
    this.svg = svg;
    this.onChange = onChange;
    this.onPick = onPick;
    this.view = { ...DEFAULT_VIEW };
    this.panMode = false;
    this.spinning = false;
    this.drag = null;
    this.frame = 0;
    this.spinTimer = 0;
    svg.addEventListener('pointerdown', (e) => this.down(e));
    svg.addEventListener('pointermove', (e) => this.move(e));
    svg.addEventListener('pointerup', (e) => this.up(e));
    svg.addEventListener('pointercancel', () => { this.drag = null; });
    svg.addEventListener('wheel', (e) => {
      e.preventDefault();
      this.set({ zoom: clamp(this.view.zoom * Math.exp(-e.deltaY * 0.0015), ...ZOOM) });
    }, { passive: false });
    svg.addEventListener('keydown', (e) => this.key(e));
  }

  /** Change the view; listeners are told once per animation frame. */
  set(patch) {
    this.view = { ...this.view, ...patch };
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.onChange(this.view);
    });
  }

  zoomBy(factor) { this.set({ zoom: clamp(this.view.zoom * factor, ...ZOOM) }); }
  turn(deg) { this.stopSpin(); this.set({ yaw: this.view.yaw + deg }); }
  tilt(deg) { this.stopSpin(); this.set({ elev: clamp(this.view.elev + deg, ...TILT) }); }
  top() { this.stopSpin(); this.set({ elev: TILT[1] }); }
  north() { this.stopSpin(); this.set({ yaw: 0 }); }
  reset() { this.stopSpin(); this.set({ ...DEFAULT_VIEW }); }

  togglePan() {
    this.panMode = !this.panMode;
    this.onChange(this.view);
  }

  toggleSpin() {
    if (this.spinning) this.stopSpin();
    else {
      this.spinning = true;
      this.spinTimer = setInterval(() => this.set({ yaw: this.view.yaw + 0.4 }), 50);
      this.onChange(this.view);
    }
  }

  stopSpin() {
    if (!this.spinning) return;
    clearInterval(this.spinTimer);
    this.spinning = false;
    this.onChange(this.view);
  }

  /** Screen px per viewBox unit of the rendered map. */
  scale() {
    return WIDTH / this.svg.getBoundingClientRect().width;
  }

  down(e) {
    if (e.button !== undefined && e.button !== 0) return;
    this.stopSpin();
    this.svg.setPointerCapture(e.pointerId);
    const mode = e.shiftKey || this.panMode ? 'pan' : 'turn';
    this.drag = { x: e.clientX, y: e.clientY, moved: 0, mode, start: { ...this.view } };
  }

  move(e) {
    const d = this.drag;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    d.moved = Math.max(d.moved, Math.hypot(dx, dy));
    if (d.mode === 'pan') {
      const s = this.scale();
      this.set({ panX: clamp(d.start.panX + dx * s, -700, 700), panY: clamp(d.start.panY + dy * s, -500, 500) });
    } else {
      this.set({ yaw: d.start.yaw - dx * 0.35, elev: clamp(d.start.elev + dy * 0.25, ...TILT) });
    }
  }

  up(e) {
    const d = this.drag;
    this.drag = null;
    if (!d || d.moved > 5) return;
    const rect = this.svg.getBoundingClientRect();
    const s = this.scale();
    this.onPick((e.clientX - rect.left) * s, (e.clientY - rect.top) * s);
  }

  key(e) {
    const actions = {
      ArrowLeft: () => this.turn(15),
      ArrowRight: () => this.turn(-15),
      ArrowUp: () => this.tilt(5),
      ArrowDown: () => this.tilt(-5),
      '+': () => this.zoomBy(1.25),
      '=': () => this.zoomBy(1.25),
      '-': () => this.zoomBy(0.8),
      n: () => this.north(),
      t: () => this.top(),
      r: () => this.reset(),
    };
    const action = actions[e.key];
    if (action) {
      e.preventDefault();
      action();
    }
  }
}
