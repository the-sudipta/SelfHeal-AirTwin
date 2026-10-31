// "What is happening now": one step of the loop (WATCH, DETECT, HEAL, FEEDBACK) and one
// sentence about it, chosen from the live state and written with the twin's own numbers.

import { COLORS, fmt, percent, signed } from './sensors.js';

const HEAL_RECENT_HOURS = 24;

const hoursBetween = (a, b) => (new Date(b) - new Date(a)) / 3.6e6;

/**
 * Pick the story for the current state.
 * @returns {{step: string, color: string, text: string, sensor: object|null}}
 */
export function tell({ status, sensors, events, maintenance }) {
  const phase = status ? status.phase : 'loading';
  if (phase === 'loading') {
    return { step: 'START', color: COLORS.healed, sensor: null, text: 'Loading and verifying the Beijing Multi-Site dataset (12 sites, hourly, 2013–2017).' };
  }
  if (phase === 'calibrating') {
    const share = Math.min(100, (100 * status.hour) / status.fast_forward_hours);
    return {
      step: 'CALIBRATE', color: COLORS.healed, sensor: null,
      text: `The twin is learning the city: it replays the first year at full speed to train one expected-value model per site, then 30 days to learn each sensor's normal error (${share.toFixed(0)}% done).`,
    };
  }
  if (phase === 'failed') {
    return { step: 'STOPPED', color: COLORS.drift, sensor: null, text: `The live twin stopped: ${status.error}` };
  }
  const now = status.time;
  const drifting = sensors.filter((s) => s.cls === 'drift').sort((a, b) => b.score - a.score)[0];
  if (drifting) {
    return {
      step: 'DETECT', color: COLORS.drift, sensor: drifting,
      text: `${drifting.site} is drifting. The sensor says ${fmt(drifting.raw, 0)} µg/m³, but the twin expects ${fmt(drifting.expected, 0)} from its neighbours and the weather. The gap has lasted too long, so the twin stops trusting this sensor and estimates a correction.`,
    };
  }
  const healEvent = events.find((e) => (e.kind === 'heal' || e.kind === 'refit') && hoursBetween(e.time, now) <= HEAL_RECENT_HOURS);
  const healing = healEvent && sensors.find((s) => `${s.site}:${s.variable}` === healEvent.sensor && (s.cls === 'healing' || s.cls === 'healed'));
  if (healing) {
    return {
      step: 'HEAL', color: COLORS.healing, sensor: healing,
      text: `The twin is healing ${healing.site}: it learned the correction gain ${fmt(healing.gain, 2)}, offset ${signed(healing.offset)} and now publishes ${fmt(healing.corrected, 0)} µg/m³ instead of the raw ${fmt(healing.raw, 0)}. Corrections fly back to the site as violet diamonds.`,
    };
  }
  const top = maintenance[0];
  const topSensor = top && sensors.find((s) => `${s.site}:${s.variable}` === top.sensor);
  if (topSensor) {
    return {
      step: 'FEEDBACK', color: COLORS.healed, sensor: topSensor,
      text: `${topSensor.site} is corrected online, so the city keeps clean values. The twin ranks it first for a field visit (${percent(top.relative_error)} error). Mark it recalibrated once the sensor has been serviced.`,
    };
  }
  const watch = sensors.filter((s) => s.cls === 'watch').length;
  const tail = watch ? ` ${watch} ${watch === 1 ? 'site is' : 'sites are'} on watch, which usually passes.` : '';
  return {
    step: 'WATCH', color: COLORS.healthy, sensor: null,
    text: `All ${sensors.length} sites agree with the twin. Every hour each site sends its PM2.5 reading up to the Twin Core, which checks it against what the neighbours and the weather say it should be.${tail} Try "Inject drift" to see the twin react.`,
  };
}
