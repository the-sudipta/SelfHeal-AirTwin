# `web`

The web twin: an interactive 3D Beijing that shows the twin's real output, live from `airtwin serve` at `http://localhost:8080`, or replaying a recorded experiment run on the project site. Plain HTML, CSS and ES modules; no build step, no external downloads.

| File | What it does |
|---|---|
| `index.html` | Page layout: header with live status and commands, summary cards, the 3D map with its toolbar, story bar, compass and plan inset, the selected-site panel, the maintenance list, the event log and the what-if slider |
| `styles.css` | Colour tokens (navy ground, teal healthy, amber drift, violet correction, blue healed), layout, focus styles, phone layout and `prefers-reduced-motion` |
| `favicon.svg` | Tab icon |
| `js/main.js` | Entry point: follows the event stream, keeps the latest state and 48 hours of frames, redraws map and panels, sends commands |
| `js/api.js` | The two data sources with one interface: the live twin (REST and Server-Sent Events) and, when no API answers, the recorded replay in `data/replay.json`, played hour by hour (`?start=<hour>` and `?step=<ms>` set where and how fast) |
| `js/camera.js` | Projection of the city (heading, tilt, zoom, pan) and the drag, wheel, keyboard and button controls |
| `js/scene.js` | The city in SVG: ring roads, landmarks, buildings, the Twin Core, site pins with data flows, hazes over untrusted sensors, the callout and the plan inset |
| `js/sensors.js` | The 12 sites with approximate positions, the status colours and labels, and number formatting |
| `js/story.js` | Picks the step of the loop (WATCH, DETECT, HEAL, FEEDBACK) and writes its sentence from the live numbers |
| `js/panels.js` | Summary cards, site chips, values, the 48-hour chart, drift score, maintenance list, event log and what-if |

## How it connects

- Every number comes from `/api` (see `src/airtwin/api/`) or from the recorded run written by `airtwin reproduce`; nothing on the page is simulated. In replay mode, injecting drift, marking recalibrated and the what-if need the live twin. Map geometry and site positions are approximate and only place the sites.
- Injected drifts are requested by the visitor, labelled as injected, and the original reading is kept to measure the error.
- All controls are buttons reachable by keyboard; with the map focused, arrow keys turn and tilt, `+` / `-` zoom, `N` faces north, `T` gives the top view and `R` resets.
