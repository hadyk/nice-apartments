#!/usr/bin/env python3
"""
Build the shareable Nice apartments board.

Reads data/listings.json (produced by scrape.py) and writes:
    site/data/listings.js     dataset for the hosted / folder version
    nice-apartments.html      one self-contained file with embedded photos
    README.md                 how to use, update and share

Usage:
    python3 build.py
    python3 build.py --zip    # also create nice-apartments-share.zip
"""

import argparse
import base64
import copy
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "listings.json"
SITE = ROOT / "site"
OUT_STANDALONE = ROOT / "nice-apartments.html"
ZIP_PATH = ROOT / "nice-apartments-share.zip"


def load_data():
    if not DATA.exists():
        raise SystemExit("data/listings.json is missing — run: python3 scrape.py")
    return json.loads(DATA.read_text(encoding="utf-8"))


def write_site_data(payload):
    target = SITE / "data" / "listings.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    body = "window.LISTINGS = " + json.dumps(payload, ensure_ascii=False) + ";\n"
    target.write_text(body, encoding="utf-8")
    return target


ASSET_REF = re.compile(r'(?P<attr>(?:href|src)=")(?P<name>styles\.css|app\.js|data/listings\.js)(?:\?v=[^"]*)?"')


def stamp_assets():
    """Add ?v=<content hash> to asset links in site/index.html so browsers never
    serve a stale stylesheet or script after a deploy (GitHub Pages caches 10 min)."""
    index = SITE / "index.html"
    html = index.read_text(encoding="utf-8")

    def versioned(match):
        digest = hashlib.sha1((SITE / match["name"]).read_bytes()).hexdigest()[:10]
        return f'{match["attr"]}{match["name"]}?v={digest}"'

    stamped = ASSET_REF.sub(versioned, html)
    if stamped != html:
        index.write_text(stamped, encoding="utf-8")


def thumb_data_uri(photo_path: Path) -> str:
    """Resize one photo to a small JPEG and return a data: URI."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "thumb.jpg"
        subprocess.run(
            ["sips", "-Z", "560", "-s", "format", "jpeg",
             "-s", "formatOptions", "58", str(photo_path), "--out", str(out)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        blob = out.read_bytes()
    return "data:image/jpeg;base64," + base64.b64encode(blob).decode("ascii")


def build_standalone(payload):
    standalone = copy.deepcopy(payload)
    photos_map = {}
    kept = 0
    for listing in standalone["listings"]:
        first = (listing.get("photos") or [None])[0]
        if not first:
            listing["photos"] = []
            continue
        path = SITE / "photos" / first
        if not path.exists():
            listing["photos"] = []
            continue
        photos_map[first] = thumb_data_uri(path)
        listing["photos"] = [first]
        kept += 1

    css = (SITE / "styles.css").read_text(encoding="utf-8")
    js = (SITE / "app.js").read_text(encoding="utf-8")
    html = (SITE / "index.html").read_text(encoding="utf-8")

    # Drop cache-busting suffixes; everything below is inlined.
    html = ASSET_REF.sub(lambda m: f'{m["attr"]}{m["name"]}"', html)

    # Inline the stylesheet.
    html = html.replace('<link rel="stylesheet" href="styles.css">', "<style>\n" + css + "\n</style>")

    # Replace the external scripts with inlined data + app code.
    data_script = (
        "<script>window.LISTINGS = "
        + json.dumps(standalone, ensure_ascii=False).replace("</", "<\\/")
        + ";\nwindow.PHOTOS = "
        + json.dumps(photos_map, ensure_ascii=False).replace("</", "<\\/")
        + ";</script>"
    )
    html = html.replace('<script src="data/listings.js"></script>', data_script)
    html = html.replace('<script src="app.js"></script>', "<script>\n" + js + "\n</script>")

    # The standalone file is opened from disk: make the share button explain itself.
    OUT_STANDALONE.write_text(html, encoding="utf-8")
    return OUT_STANDALONE, kept


def write_readme(payload):
    n = payload.get("total", 0)
    near = sum(1 for l in payload["listings"] if l.get("near_center"))
    sources = {}
    for l in payload["listings"]:
        for s in (l.get("sources") or [l.get("source", "—")]):
            sources[s] = sources.get(s, 0) + 1
    by_source = ", ".join(f"{s}: {n}" for s, n in sorted(sources.items()))
    text = f"""# Nice apartments — centre & Promenade

A shareable snapshot of **{n} rental flats** in Nice, **{near} of them** in the centre or
within walking distance of the Promenade des Anglais ({by_source}). Every listing includes photos, rent,
charges, deposit, surface, rooms, DPE/GES, agency contact and the full description.

Data source: [Bien'ici](https://www.bienici.com) (agencies), [LocService](https://www.locservice.fr) and
[123 Loger](https://www.123loger.com) (owner-direct listings). Snapshot: {payload.get('generated_at', '')}.

**Live page:** https://hadyk.github.io/nice-apartments/

## The two ways to share it

### 1. One file (easiest)
Send **`nice-apartments.html`** by email, AirDrop, WhatsApp or any file transfer.
It opens in any browser, works offline, and already contains the photos.
No server, no install, no internet needed (except the "Open original ad" links).

### 2. Folder / website
The **`site/`** folder is a complete static website. Host it anywhere:

- **GitHub Pages** — push the folder and enable Pages (see below).
- **Netlify Drop** — drag the `site` folder onto https://app.netlify.com/drop
- **Local preview** — `cd site && python3 -m http.server 8000`, then open http://localhost:8000

`nice-apartments-share.zip` (if generated) contains the same folder, ready to send.

## Refresh the listings

```bash
cd ~/nice-apartments
python3 scrape.py          # re-downloads listings + photos
python3 build.py --zip     # rebuilds the site, the one-file version and the zip
open site/index.html
```

Use `python3 scrape.py --refresh` to ignore the local cache.

## What the page can do

- Search by street, district or keyword
- Filter by rent, surface, rooms, furnishing and district
- Toggle **Near centre / Promenade only**
- Toggle **Include rooms & colocations**
- Sort by price, surface or date
- Hide the filters with one tap (collapsed by default on phones and tablets); the filter
  bar slides away while scrolling down and comes back when scrolling up
- Open any card for the full description, charges, deposit, DPE/GES, agency phone,
  a map link and a link to the original ad
- Share button (copies the link, or opens the system share sheet)

## Publish to GitHub Pages

```bash
cd ~/nice-apartments
git init
git add site
git commit -m "Nice apartments snapshot"
gh repo create nice-apartments --public --source=. --push
gh api repos/:owner/nice-apartments/pages -X POST \\
  -f source[branch]=main -f source[path]=/site
```

The link will be `https://<your-username>.github.io/nice-apartments/`.

> Prices and availability change daily. Always confirm with the agency before visiting.
> This is an independent snapshot, not affiliated with Bien'ici.
"""
    (ROOT / "README.md").write_text(text, encoding="utf-8")


def make_zip():
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in SITE.rglob("*"):
            if path.is_file():
                zf.write(path, Path("site") / path.relative_to(SITE))
        zf.write(OUT_STANDALONE, "nice-apartments.html")
        zf.write(ROOT / "README.md", "README.md")
    return ZIP_PATH


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", action="store_true", help="also create nice-apartments-share.zip")
    args = parser.parse_args()

    payload = load_data()
    data_js = write_site_data(payload)
    stamp_assets()
    standalone, kept = build_standalone(payload)
    write_readme(payload)

    size_mb = standalone.stat().st_size / 1024 / 1024
    print(f"[site]       {SITE / 'index.html'}")
    print(f"[data]       {data_js}")
    print(f"[standalone] {standalone}  ({size_mb:.1f} MB, {kept} embedded photos)")
    print(f"[readme]     {ROOT / 'README.md'}")

    if args.zip:
        zp = make_zip()
        print(f"[zip]        {zp}  ({zp.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
