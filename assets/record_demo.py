"""Record assets/demo.gif: the web twin replaying the recorded experiment run.

Serves web/ with site/data/replay.json (so the page runs in replay mode), opens it in headless
Chromium through Playwright, captures the page at a fixed frame rate and writes an optimised
GIF with Pillow. Every value in the GIF is real replay data.

Run from the repository root inside the Playwright image mcr.microsoft.com/playwright/python
v1.64.0, pinned by its digest
sha256:684df257a1fa0ef3fa288239819984008f560e8f8db5b635ee9e2a50cbcd2e23:

    docker run --rm -v "${PWD}:/w" -w /w mcr.microsoft.com/playwright/python@sha256:<digest> \
      sh -c "pip install playwright==1.64.0 pillow \
             && python assets/record_demo.py --start 585 --site Huairou"

(the published demo.gif was recorded with exactly these options).
"""

from __future__ import annotations

import argparse
import functools
import http.server
import io
import shutil
import tempfile
import threading
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def serve(folder: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    """Serve a folder on a free local port in a background thread."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(folder))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/"


def main() -> None:
    """Record the replay and write the GIF."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=int, default=0, help="first replay hour")
    parser.add_argument("--step", type=int, default=250, help="milliseconds per replay hour")
    parser.add_argument("--seconds", type=float, default=16.0, help="length of the GIF")
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--width", type=int, default=1280, help="browser viewport width")
    parser.add_argument("--height", type=int, default=860, help="browser viewport height")
    parser.add_argument(
        "--scale", type=float, default=0.62, help="GIF size relative to the viewport"
    )
    parser.add_argument("--colors", type=int, default=128)
    parser.add_argument("--site", default="", help="site to select before recording")
    parser.add_argument("--out", type=Path, default=ROOT / "assets" / "demo.gif")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "twin"
        shutil.copytree(ROOT / "web", folder)
        (folder / "data").mkdir()
        shutil.copy(ROOT / "site" / "data" / "replay.json", folder / "data" / "replay.json")
        server, url = serve(folder)
        frames: list[Image.Image] = []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": args.width, "height": args.height})
            page.goto(f"{url}?start={args.start}&step={args.step}")
            page.wait_for_selector("#layer-pins g")
            if args.site:
                page.click(f'.chip[data-site="{args.site}"]')
            page.wait_for_timeout(1500)
            size = (round(args.width * args.scale), round(args.height * args.scale))
            interval = 1.0 / args.fps
            next_shot = time.monotonic()
            for _ in range(round(args.seconds * args.fps)):
                shot = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
                frames.append(shot.resize(size, Image.LANCZOS))
                next_shot += interval
                time.sleep(max(0.0, next_shot - time.monotonic()))
            browser.close()
        server.shutdown()

    palette = frames[len(frames) // 2].quantize(colors=args.colors, method=Image.Quantize.MEDIANCUT)
    gif = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    gif[0].save(
        args.out,
        save_all=True,
        append_images=gif[1:],
        duration=round(1000 / args.fps),
        loop=0,
        optimize=True,
        disposal=1,
    )
    print(f"{args.out}: {len(gif)} frames, {args.out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
