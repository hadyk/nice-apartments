# Nice apartments — centre & Promenade

A shareable snapshot of **430 rental flats** in Nice, **223 of them** in the centre or
within walking distance of the Promenade des Anglais (123 Loger: 182, Bien'ici: 189, LocService: 64). Every listing includes photos, rent,
charges, deposit, surface, rooms, DPE/GES, agency contact and the full description.

Data source: [Bien'ici](https://www.bienici.com) (agencies), [LocService](https://www.locservice.fr) and
[123 Loger](https://www.123loger.com) (owner-direct listings). Snapshot: 2026-11-01T09:57:23+01:00.

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
gh api repos/:owner/nice-apartments/pages -X POST \
  -f source[branch]=main -f source[path]=/site
```

The link will be `https://<your-username>.github.io/nice-apartments/`.

> Prices and availability change daily. Always confirm with the agency before visiting.
> This is an independent snapshot, not affiliated with Bien'ici.
