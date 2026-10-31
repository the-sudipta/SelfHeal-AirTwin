// The 12 Beijing monitoring sites and how a sensor's twin state is shown.
// Positions are approximate (for drawing the map only); every value comes from the API.

export const SITES = [
  { name: 'Dongsi', zone: 'Dongcheng, inside the 2nd Ring', lat: 39.929, lon: 116.417, map: true },
  { name: 'Tiantan', zone: 'Temple of Heaven', lat: 39.886, lon: 116.407, map: true },
  { name: 'Guanyuan', zone: 'Xicheng, 2nd Ring', lat: 39.929, lon: 116.339, map: true },
  { name: 'Wanshouxigong', zone: 'Xicheng, south-west', lat: 39.878, lon: 116.352, map: true },
  { name: 'Aotizhongxin', zone: 'Olympic Centre', lat: 39.982, lon: 116.397, map: true },
  { name: 'Nongzhanguan', zone: 'Chaoyang, 3rd Ring', lat: 39.937, lon: 116.461, map: true },
  { name: 'Wanliu', zone: 'Haidian, north-west', lat: 39.987, lon: 116.287, map: true },
  { name: 'Gucheng', zone: 'Shijingshan, west', lat: 39.914, lon: 116.184, map: true },
  { name: 'Changping', zone: 'Changping, northern suburb', lat: 40.217, lon: 116.23, map: false },
  { name: 'Dingling', zone: 'Ming Tombs, far north', lat: 40.292, lon: 116.22, map: false },
  { name: 'Shunyi', zone: 'Shunyi, north-eastern suburb', lat: 40.127, lon: 116.655, map: false },
  { name: 'Huairou', zone: 'Huairou, far north-east', lat: 40.328, lon: 116.628, map: false },
];

export const SITE_BY_NAME = new Map(SITES.map((s) => [s.name, s]));

// One colour per visible state; the same tokens are defined in styles.css.
export const COLORS = {
  warmup: '#7F90AE',
  healthy: '#2DD4BF',
  watch: '#FCD34D',
  drift: '#F59E0B',
  healing: '#A78BFA',
  healed: '#60A5FA',
};

export const LABELS = {
  warmup: 'Learning baseline',
  healthy: 'Healthy',
  watch: 'On watch',
  drift: 'Drift detected',
  healing: 'Self-healing',
  healed: 'Healed · online',
};

/** True when the twin applies a correction to this sensor. */
export function isCorrected(sensor) {
  return (sensor.gain !== null && Math.abs(sensor.gain - 1) > 1e-9)
    || (sensor.offset !== null && Math.abs(sensor.offset) > 1e-9);
}

/**
 * The state shown for one sensor, from the twin's status and its correction:
 * a confirmed drift without a correction is "drift"; a correction that the detector does not
 * yet see as healthy is "healing"; a correction that keeps the sensor healthy is "healed".
 */
export function classify(sensor) {
  if (!sensor || sensor.status === 'warmup') return 'warmup';
  const corrected = isCorrected(sensor);
  if (sensor.status === 'drifting') return corrected ? 'healing' : 'drift';
  if (corrected) return sensor.status === 'healed' ? 'healed' : 'healing';
  return sensor.status === 'watch' ? 'watch' : 'healthy';
}

/** "site:variable" of a sensor object. */
export function sensorId(sensor) {
  return `${sensor.site}:${sensor.variable}`;
}

/** A number with a fixed number of decimals, or an en dash when missing. */
export function fmt(value, digits = 1) {
  return value === null || value === undefined || Number.isNaN(value) ? '–' : value.toFixed(digits);
}

/** Signed number, e.g. +3.2 or −1.0. */
export function signed(value, digits = 1) {
  if (value === null || value === undefined) return '–';
  return (value >= 0 ? '+' : '−') + Math.abs(value).toFixed(digits);
}

/** Signed percentage of a relative value, e.g. +40% for 0.4. */
export function percent(value, digits = 0) {
  if (value === null || value === undefined) return '–';
  return signed(value * 100, digits) + '%';
}

/** "2014-04-05 01:00" from an ISO timestamp. */
export function stamp(iso) {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '–';
}

/** Escape text for use inside HTML or SVG markup. */
export function esc(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}
