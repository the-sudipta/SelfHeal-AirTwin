# `site`

The project's GitHub Pages site: a landing page with the README's sections, the web twin replaying a recorded experiment run, the results and the downloads.

| File | What it does |
|---|---|
| `index.html` | Sections: hero with the twin loop, problem and contribution, the embedded twin, how it works (architecture and the five V's), results, reproduce and verify, downloads, citation |
| `styles.css` | Same palette and fonts as the web twin, with a light theme, sticky navigation and `prefers-reduced-motion` |
| `js/site.js` | Reveals sections on scroll (`IntersectionObserver`) and builds the results tables and headline numbers from the reference CSVs |
| `data/replay.json` | 30 days of one experiment run (all 12 sensors, events and the maintenance list per hour), written by `airtwin report`; the web twin plays it when no live API is present |

## How it connects

- `.github/workflows/pages.yml` assembles the published site: this folder, `web/` as `twin/` (with the replay as `twin/data/replay.json`), `assets/`, and `results/reference/full/` as `results/`.
- Every number comes from the committed reference tables or the recorded run; the download links point at the assets the Release workflow attaches.
