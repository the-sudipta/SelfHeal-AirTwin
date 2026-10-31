// Talks to the live twin: REST calls and the Server-Sent Events stream of state updates.

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

const sensorPath = (sensor) => `/api/sensors/${encodeURIComponent(sensor)}`;

export const api = {
  state: () => request('/api/state'),
  history: (hours) => request(`/api/history?hours=${hours}`),
  whatIf: (sensor, days) => request(`/api/what-if/${encodeURIComponent(sensor)}?days=${days}`),
  setRunning: (running) => post('/api/control', { running }),
  inject: (sensor) => post(`${sensorPath(sensor)}/inject`),
  recalibrate: (sensor) => post(`${sensorPath(sensor)}/recalibrate`),
};

/**
 * Follow the twin: calls onUpdate with each state update and onConnection(true|false) when
 * the stream opens or drops. The browser reconnects by itself and resumes after the last event.
 */
export function follow(onUpdate, onConnection) {
  const source = new EventSource('/api/stream');
  source.addEventListener('tick', (message) => onUpdate(JSON.parse(message.data)));
  source.addEventListener('open', () => onConnection(true));
  source.addEventListener('error', () => onConnection(false));
  return () => source.close();
}
