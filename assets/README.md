# `assets`

Visuals for the root README and the project site, in dark and light variants chosen with `<picture>` and `prefers-color-scheme`.

| File | What it does |
|---|---|
| `twin-loop-dark.svg`, `twin-loop-light.svg` | Hero image: sensors → stream → twin → feedback, with the violet feedback path back to the city; slow CSS animations that stop under `prefers-reduced-motion` |
| `architecture-dark.svg`, `architecture-light.svg` | Architecture: datasets, loaders, the two stream backends, the twin engine and its parts, the API, the web twin and the experiments |
| `demo.gif` | The web twin replaying the recorded experiment run, captured from the page at about 12 frames per second |
| `record_demo.py` | Records `demo.gif`: serves `web/` with the replay, captures the page with Playwright and writes the GIF with Pillow |

## How it connects

- GitHub strips scripts and styles from README files, so README motion comes only from the CSS inside these SVG files and from the GIF.
- The Pages workflow copies this folder to the site; the GIF shows real replay data from `site/data/replay.json`, never simulated values.
- Colours follow the web twin: navy ground, teal healthy and twin, amber drift, violet correction, blue healed.
