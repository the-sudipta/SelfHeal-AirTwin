// Entry point: follows the live twin, keeps the latest state and redraws the map and panels.

import { openSource } from './api.js';
import { Camera, projection } from './camera.js';
import * as scene from './scene.js';
import * as panels from './panels.js';
import { tell } from './story.js';
import { classify } from './sensors.js';

const HISTORY_HOURS = 48;
const EVENT_LIMIT = 60;
const WHAT_IF_EVERY = 6; // ticks between what-if refreshes of the selected site
const PICK_RADIUS = 26;

const motion = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const $ = (id) => document.getElementById(id);

const state = {
  status: null,
  frames: [],
  network: null,
  maintenance: [],
  events: [],
  connected: false,
  selected: 'Dongsi',
  days: 14,
  seenEvent: 0,
  whatIf: null,
  ticks: 0,
};

const world = scene.buildWorld();
const map = $('map');
let hits = [];
let pr = null;
let eventsKey = '';
let source = null;

const camera = new Camera(map, () => { drawCity(); drawLive(); controls(); }, pick);

/** Sensors of the latest frame, each with its visible state. */
function sensors() {
  const frame = state.frames[state.frames.length - 1];
  return frame ? frame.sensors.map((s) => ({ ...s, cls: classify(s) })) : [];
}

function isReplay() {
  return Boolean(source && source.mode === 'replay');
}

function notice(text) {
  $('notice').textContent = text;
}

// ---- map --------------------------------------------------------------------------------

function drawCity() {
  pr = projection(camera.view);
  $('layer-ground').innerHTML = scene.ground(world, pr, camera.view, motion);
  $('layer-buildings').innerHTML = scene.buildings(world, pr);
  $('layer-landmarks').innerHTML = scene.landmarks(world, pr);
  $('layer-core').innerHTML = scene.core(world, pr, motion);
}

function drawLive(story = tell(storyInput())) {
  const list = sensors();
  const byName = new Map(list.map((s) => [s.site, s]));
  $('layer-hazes').innerHTML = scene.hazes(world, pr, camera.view, list);
  const p = scene.pins(world, pr, list, state.selected, motion);
  hits = p.hits;
  $('layer-pins').innerHTML = p.svg;
  $('layer-callout').innerHTML = scene.callout(world, pr, story.sensor, story, p.height);
  $('inset').innerHTML = scene.inset(byName, state.selected);
}

function controls() {
  const v = camera.view;
  for (const button of document.querySelectorAll('[data-cam="pan"]')) button.setAttribute('aria-pressed', String(camera.panMode));
  for (const button of document.querySelectorAll('[data-cam="spin"]')) button.setAttribute('aria-pressed', String(camera.spinning));
  map.classList.toggle('pan', camera.panMode);
  $('compass').querySelector('svg').style.transform = `rotate(${pr.compass.toFixed(1)}deg)`;
  const heading = ((v.yaw % 360) + 360) % 360;
  $('view-readout').textContent = `zoom ${v.zoom.toFixed(1)}× · tilt ${v.elev.toFixed(0)}° · heading ${heading.toFixed(0)}°`;
}

function pick(x, y) {
  let best = null;
  let bestDistance = PICK_RADIUS;
  for (const h of hits) {
    const d = Math.hypot(x - h.x, y - h.y);
    if (d < bestDistance) {
      bestDistance = d;
      best = h.site;
    }
  }
  if (best) select(best);
}

// ---- panels -----------------------------------------------------------------------------

function storyInput() {
  return { status: state.status, sensors: sensors(), events: state.events, maintenance: state.maintenance };
}

function render() {
  const list = sensors();
  const byName = new Map(list.map((s) => [s.site, s]));
  const story = tell(storyInput());
  panels.header(state.status, state.connected, state.selected);
  panels.summary(state.status, list, state.network);
  panels.chips(byName, state.selected, select);
  panels.site(byName.get(state.selected), state.selected);
  panels.chart(state.frames, state.selected, state.events);
  const replay = isReplay();
  panels.maintenance(state.maintenance, byName, recalibrate, !replay);
  const eKey = state.events.length ? String(state.events[0].id) : '';
  if (eKey !== eventsKey) {
    eventsKey = eKey;
    panels.eventLog(state.events, state.seenEvent);
    state.seenEvent = state.events.length ? state.events[0].id : 0;
  }
  panels.whatIf(state.whatIf, state.days, state.selected, state.frames, replay);
  const box = $('story');
  box.style.setProperty('--story', story.color);
  $('story-step').textContent = story.step;
  if ($('story-text').textContent !== story.text) $('story-text').textContent = story.text;
  if (pr) drawLive(story);
}

function select(name) {
  state.selected = name;
  state.whatIf = null;
  render();
  refreshWhatIf();
}

// ---- data -------------------------------------------------------------------------------

let whatIfTimer = 0;
function refreshWhatIf(delay = 0) {
  clearTimeout(whatIfTimer);
  whatIfTimer = setTimeout(async () => {
    if (!state.status || state.status.phase === 'loading' || source.mode !== 'live') return;
    const sensor = `${state.selected}:pm25`;
    try {
      const result = await source.whatIf(sensor, state.days);
      if (sensor === `${state.selected}:pm25`) {
        state.whatIf = result;
        panels.whatIf(state.whatIf, state.days, state.selected, state.frames, isReplay());
      }
    } catch {
      // the twin is still calibrating; the next refresh will try again
    }
  }, delay);
}

function mergeEvents(fresh) {
  const newest = state.events.length ? state.events[0].id : 0;
  const added = fresh.filter((e) => e.id > newest);
  state.events = added.concat(state.events).slice(0, EVENT_LIMIT);
}

function apply(update) {
  if (update.reset) {
    state.frames = [];
    state.events = [];
  }
  state.status = update.status;
  state.network = update.network;
  state.maintenance = update.maintenance;
  mergeEvents(update.events);
  const frame = update.frame;
  const last = state.frames[state.frames.length - 1];
  if (frame && (!last || frame.hour > last.hour)) {
    state.frames.push(frame);
    if (state.frames.length > HISTORY_HOURS) state.frames.splice(0, state.frames.length - HISTORY_HOURS);
    state.ticks += 1;
    if (state.ticks % WHAT_IF_EVERY === 0) refreshWhatIf();
  } else if (frame && last && frame.hour < last.hour) {
    state.frames = [frame];
  }
  render();
}

async function resync() {
  try {
    const [snapshot, history] = await Promise.all([source.state(), source.history(HISTORY_HOURS)]);
    state.frames = history.frames;
    state.events = [];
    mergeEvents(snapshot.events);
    apply({ ...snapshot, events: [] });
    refreshWhatIf();
  } catch (error) {
    notice(`Could not read the twin: ${error.message}`);
  }
}

async function command(action, done) {
  try {
    await action();
    notice(done);
    refreshWhatIf();
  } catch (error) {
    notice(`Not done: ${error.message}`);
  }
}

function recalibrate(sensor) {
  command(() => source.recalibrate(sensor), `${sensor.split(':')[0]} marked as recalibrated: its correction is cleared and any injected drift is removed.`);
}

// ---- wiring -----------------------------------------------------------------------------

const cameraActions = {
  zoomIn: () => camera.zoomBy(1.25),
  zoomOut: () => camera.zoomBy(0.8),
  turnLeft: () => camera.turn(45),
  turnRight: () => camera.turn(-45),
  tiltUp: () => camera.tilt(10),
  tiltDown: () => camera.tilt(-10),
  top: () => camera.top(),
  pan: () => camera.togglePan(),
  spin: () => camera.toggleSpin(),
  reset: () => camera.reset(),
};
for (const button of document.querySelectorAll('[data-cam]')) {
  button.addEventListener('click', () => cameraActions[button.dataset.cam]());
}
$('compass').addEventListener('click', () => camera.north());
$('play').addEventListener('click', () => {
  const running = !(state.status && state.status.running);
  command(() => source.setRunning(running), running ? 'Twin resumed.' : 'Twin paused: the stream holds at the current hour.');
});
$('inject').addEventListener('click', () => {
  const name = state.selected;
  command(() => source.inject(`${name}:pm25`), `Drift injected into ${name}: from the next hour its sensor reads too high. Watch the twin detect and heal it.`);
});
$('days').addEventListener('input', (e) => {
  state.days = Number(e.target.value);
  panels.whatIf(state.whatIf, state.days, state.selected, state.frames, isReplay());
  refreshWhatIf(150);
});

drawCity();
controls();
render();
openSource()
  .then((opened) => {
    source = opened;
    document.body.dataset.mode = source.mode;
    source.follow(apply, (connected) => {
      const reconnected = connected && !state.connected;
      state.connected = connected;
      if (reconnected) resync();
      else render();
    });
  })
  .catch((error) => notice(`Could not reach the twin or its recording: ${error.message}`));
