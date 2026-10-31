// Where the twin's data comes from. Both sources hand main.js the same state updates:
// - live: the running twin (`airtwin serve`), over REST and Server-Sent Events;
// - replay: a recorded experiment run (`data/replay.json`), played in the browser when no
//   API is available, e.g. on the project's GitHub Pages site.

const REPLAY_URL = 'data/replay.json';
const REPLAY_STEP_MS = 400; // one recorded hour per step; ?step=<ms> and ?start=<hour> override

async function request(path, options = {}) {
  const response = await fetch(path, { headers: { Accept: 'application/json' }, ...options });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

function post(path, body) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

const sensorPath = (sensor) => `api/sensors/${encodeURIComponent(sensor)}`;

/** The running twin. */
function liveSource() {
  return {
    mode: 'live',
    state: () => request('api/state'),
    history: (hours) => request(`api/history?hours=${hours}`),
    whatIf: (sensor, days) => request(`api/what-if/${encodeURIComponent(sensor)}?days=${days}`),
    setRunning: (running) => post('api/control', { running }),
    inject: (sensor) => post(`${sensorPath(sensor)}/inject`),
    recalibrate: (sensor) => post(`${sensorPath(sensor)}/recalibrate`),
    /** Calls onUpdate with each update and onConnection(true|false) as the stream opens or drops. */
    follow(onUpdate, onConnection) {
      const stream = new EventSource('api/stream');
      stream.addEventListener('tick', (message) => onUpdate(JSON.parse(message.data)));
      stream.addEventListener('open', () => onConnection(true));
      stream.addEventListener('error', () => onConnection(false));
    },
  };
}

/** A recorded run, played hour by hour and looped; commands that change the twin need the live twin. */
function replaySource(replay) {
  const frames = replay.frames;
  const events = replay.events
    .filter((e) => e.kind !== 'watch')
    .map((e, i) => ({ id: i + 1, ...e }));
  // readings streamed up to each recorded hour
  const counts = [];
  frames.reduce((total, f) => {
    counts.push(total + f.sensors.filter((s) => s.raw !== null).length);
    return counts[counts.length - 1];
  }, 0);
  const params = new URLSearchParams(window.location.search);
  const stepMs = Math.max(50, Number(params.get('step')) || REPLAY_STEP_MS);
  let index = Math.min(frames.length - 1, Math.max(0, Number(params.get('start')) || 0));
  let running = true;
  let onUpdate = () => {};
  const live = () => Promise.reject(new Error('this needs the live twin: run docker compose up'));

  function update(reset) {
    const frame = frames[index];
    return {
      reset,
      status: {
        phase: 'running',
        mode: 'replay',
        running,
        hour: index,
        time: frame.time,
        readings: counts[index],
        fast_forward_hours: 1,
        replay_hours: frames.length,
        drifts: replay.drifts,
      },
      frame,
      network: frame.network,
      maintenance: frame.maintenance,
      events: events.filter((e) => e.time <= frame.time).reverse(),
    };
  }

  function step() {
    if (!running) return;
    index += 1;
    const reset = index >= frames.length;
    if (reset) index = 0;
    onUpdate(update(reset));
  }

  return {
    mode: 'replay',
    state: async () => update(false),
    history: async () => ({ frames: frames.slice(0, index + 1) }),
    whatIf: live,
    inject: live,
    recalibrate: live,
    async setRunning(value) {
      running = value;
      onUpdate({ ...update(false), events: [] });
    },
    follow(callback, onConnection) {
      onUpdate = callback;
      onConnection(true);
      setInterval(step, stepMs);
    },
  };
}

/** The live twin when its API answers, otherwise the recorded replay. */
export async function openSource() {
  try {
    const health = await request('api/health');
    if (health.status === 'ok') return liveSource();
  } catch {
    // no API here: play the recording
  }
  return replaySource(await request(REPLAY_URL));
}
