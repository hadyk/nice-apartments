#!/usr/bin/env python3
"""
Collect rental listings in Nice (<= MAX_PRICE) from several portals:

    Bien'ici    agency listings (rich detail, exact coordinates)
    LocService  owner-direct listings (charges, deposit, DPE)
    123 Loger   owner-direct listings

Outputs:
    data/listings.json   merged dataset used by build.py
    site/photos/*        one folder of photos per listing

Only the Python standard library is required.
Usage:
    python3 scrape.py                # uses cache when available
    python3 scrape.py --refresh      # re-downloads everything
    python3 scrape.py --max-price 900 --city nice
"""

import argparse
import html
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
DATA = ROOT / "data"
PHOTOS = ROOT / "site" / "photos"

API_SEARCH = "https://www.bienici.com/realEstateAds.json"
API_DETAIL = "https://www.bienici.com/realEstateAd.json"
API_SUGGEST = "https://res.bienici.com/suggest.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
}

NOMINATIM = "https://nominatim.openstreetmap.org/search"

# Promenade des Anglais, approximated as a west -> east polyline (lat, lon).
PROMENADE = [
    (43.6630, 7.2150), (43.6650, 7.2230), (43.6690, 7.2350),
    (43.6750, 7.2470), (43.6820, 7.2560), (43.6880, 7.2620),
    (43.6920, 7.2660), (43.6948, 7.2695), (43.6960, 7.2740),
]
# Place Massena / heart of the city centre.
CENTRE = (43.6990, 7.2720)

# Quartier keyword -> representative coordinates (derived from Bien'ici data).
# "promenade" is special-cased: snaps to the nearest point on the seafront.
QUARTIER_COORDS = {
    "vieux nice": (43.6969, 7.2769),
    "vieux-nice": (43.6969, 7.2769),
    "old town": (43.6969, 7.2769),
    "carre d'or": (43.6968, 7.2612),
    "carré d'or": (43.6968, 7.2612),
    "centre-ville": (43.6988, 7.2716),
    "centre ville": (43.6988, 7.2716),
    "centre historique": (43.6988, 7.2716),
    "massena": (43.6970, 7.2690),
    "masséna": (43.6970, 7.2690),
    "carabacel": (43.7018, 7.2738),
    "thiers": (43.7016, 7.2616),
    "musicien": (43.7016, 7.2616),
    "medecin": (43.7023, 7.2660),
    "médecin": (43.7023, 7.2660),
    "le port": (43.6977, 7.2837),
    "port de nice": (43.6977, 7.2837),
    "lympia": (43.6977, 7.2837),
    "garibaldi": (43.7018, 7.2823),
    "riquier": (43.7038, 7.2889),
    "liberation": (43.7063, 7.2648),
    "libération": (43.7063, 7.2648),
    "saint-roch": (43.7100, 7.2918),
    "acropolis": (43.7063, 7.2843),
    "republique": (43.7063, 7.2843),
    "république": (43.7063, 7.2843),
    "vernier": (43.7084, 7.2590),
    "gambetta": (43.6992, 7.2541),
    "baumettes": (43.6973, 7.2494),
    "californie": (43.6810, 7.2298),
    "carras": (43.6810, 7.2298),
    "fabron": (43.6885, 7.2344),
    "madeleine": (43.6965, 7.2344),
    "sainte-marguerite": (43.6830, 7.2022),
    "cimiez": (43.7128, 7.2721),
    "bas cimiez": (43.7150, 7.2631),
    "mont-boron": (43.6963, 7.2961),
    "arenas": (43.6717, 7.2245),
    "cessole": (43.7111, 7.2553),
    "borriglione": (43.7127, 7.2597),
    "pasteur": (43.7215, 7.2842),
    "valrose": (43.7207, 7.2680),
    "poetes": (43.7210, 7.2585),
    "poètes": (43.7210, 7.2585),
    "le ray": (43.7319, 7.2445),
    "saint-sylvestre": (43.7212, 7.2530),
    "parc imperial": (43.7079, 7.2544),
    "parc impérial": (43.7079, 7.2544),
    "roquebilliere": (43.7165, 7.2848),
    "roquebillière": (43.7165, 7.2848),
    "saint-antoine": (43.7071, 7.2095),
    "saint-philippe": (43.7026, 7.2500),
}

# Districts that count as "centre or next to the Promenade" (Bien'ici names).
CENTRAL_DISTRICTS = {
    "Nice - Centre-ville", "Nice - Vieux Nice", "Nice - Carré d'or",
    "Nice - Carabacel", "Nice - Thiers - Musicien", "Nice - Médecin",
    "Nice - Vernier", "Nice - Le Port", "Nice - Garibaldi",
    "Nice - Acropolis - République", "Nice - Mont-Boron",
    "Nice - Baumettes", "Nice - Californie - Carras",
    "Nice - Sainte-Marguerite", "Nice - Fabron", "Nice - Gambetta",
    "Nice - Saint-Lambert - Bas-Cimiez",
    "Nice - Promenade des Anglais - Rue de France",
}
CENTRAL_WORDS = [
    "promenade", "centre-ville", "centre ville", "vieux nice", "vieux-nice",
    "carré d'or", "carre d'or", "masséna", "massena", "garibaldi",
    "acropolis", "république", "republique", "le port", "port de nice",
    "thiers", "musicien", "carabacel", "vernier", "baumettes",
    "californie", "carras", "fabron", "sainte-marguerite", "mont-boron",
]
ROOM_WORDS = re.compile(r"\b(chambre|colocation|coloc|co-location|room)\b", re.I)
STREET_RE = re.compile(
    r"\b(rue|avenue|boulevard|bd|chemin|place|cours|impasse|quai|square|all[eé]e)\s+"
    r"((?:(?:des|du|de|la|le|les|de la|de l'|l'|d')\s+)*"
    r"[A-ZÉÈÀÂÎÔÛ][\wÉÈÊÀÇÎÔÛ'’-]+(?:\s+[A-ZÉÈÀÂÎÔÛ][\wÉÈÊÀÇÎÔÛ'’-]+)*)", re.I)


def log(msg):
    print(msg, flush=True)


# ------------------------------------------------------------------ HTTP
def fetch_bytes(url, cache_path, refresh=False, retries=3, headers=None):
    if cache_path and cache_path.exists() and cache_path.stat().st_size > 500 and not refresh:
        return cache_path.read_bytes()
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": HEADERS["User-Agent"]})
            with urllib.request.urlopen(req, timeout=45) as resp:
                blob = resp.read()
            if cache_path:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(blob)
            return blob
        except Exception as exc:
            last = exc
            time.sleep(1.2 * (attempt + 1))
    log(f"  [http] failed {url}: {last}")
    return None


def fetch_json(url, cache_path, refresh=False, retries=3, headers=None):
    blob = fetch_bytes(url, cache_path, refresh, retries, headers or HEADERS)
    if blob is None:
        return None
    try:
        return json.loads(blob.decode("utf-8"))
    except Exception as exc:
        log(f"  [json] bad payload {url}: {exc}")
        return None


def fetch_html(url, cache_path, refresh=False):
    blob = fetch_bytes(url, cache_path, refresh, headers={
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    })
    if blob is None:
        return None
    return blob.decode("utf-8", errors="replace")


# ------------------------------------------------------------------ photos
def save_photo(url, name, refresh=False):
    """Download a photo and normalise it to a site/photos/<name>.jpg."""
    target = PHOTOS / (name + ".jpg")
    if target.exists() and not refresh:
        return target.name
    raw = fetch_bytes(url, None, refresh)
    if raw is None:
        return None
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "img"
        src.write_bytes(raw)
        target.parent.mkdir(parents=True, exist_ok=True)
        res = subprocess.run(
            ["sips", "-Z", "1000", "-s", "format", "jpeg",
             "-s", "formatOptions", "72", str(src), "--out", str(target)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode != 0 or not target.exists() or target.stat().st_size < 500:
            return None
    return target.name


# ------------------------------------------------------------------ geo
def haversine(a, b):
    r = 6371.0
    la1, lo1 = map(math.radians, a)
    la2, lo2 = map(math.radians, b)
    d = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(d))


def distance_to_segment(p, a, b):
    lat0 = math.radians((a[0] + b[0]) / 2)
    def xy(q):
        return ((q[1] - a[1]) * math.cos(lat0) * 111.32, (q[0] - a[0]) * 110.57)
    px, py = xy(p)
    ax, ay = xy(a)
    bx, by = xy(b)
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def promenade_distance(point):
    return min(distance_to_segment(point, PROMENADE[i], PROMENADE[i + 1])
               for i in range(len(PROMENADE) - 1))


def nearest_promenade_point(point):
    best, best_d = None, 1e9
    for i in range(len(PROMENADE) - 1):
        # dense sample along each segment
        for t in range(9):
            p = i + t / 8
            seg_a, seg_b = PROMENADE[i], PROMENADE[i + 1]
            q = (seg_a[0] + (seg_b[0] - seg_a[0]) * (t / 8),
                 seg_a[1] + (seg_b[1] - seg_a[1]) * (t / 8))
            d = haversine(point, q)
            if d < best_d:
                best_d, best = d, q
    return best


def geocode(query):
    """Nominatim lookup with local cache and throttling."""
    key = re.sub(r"[^a-z0-9]+", "_", query.lower())[:80]
    cache_path = CACHE / "geocode" / f"{key}.json"
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
            return None
        except Exception:
            pass
    url = NOMINATIM + "?" + urllib.parse.urlencode({
        "q": query, "format": "json", "limit": 1, "countrycodes": "fr",
    })
    data = fetch_json(url, cache_path, headers={
        "User-Agent": "nice-apartments-snapshot/1.0 (personal; contact via GitHub hadyk)",
        "Accept": "application/json",
    })
    time.sleep(1.1)  # Nominatim fair-use
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"])


def find_quartier(text):
    lowered = text.lower()
    for name in QUARTIER_COORDS:
        if name in lowered:
            return name
    return None


def resolve_location(title, description):
    """Coordinates for listings that only carry text. Returns (lat, lon, note)."""
    text = f"{title} {description}"
    quartier = find_quartier(text)
    if quartier:
        lat, lon = QUARTIER_COORDS[quartier]
        note = f"quartier: {quartier}"
        if "promenade" in quartier or quartier in ("carre d'or", "carré d'or", "vieux nice", "centre-ville", "centre ville"):
            return (lat, lon, note)
        return (lat, lon, note)
    m = STREET_RE.search(text)
    if m:
        street = f"{m.group(0).strip()}, Nice, France"
        coords = geocode(street)
        if coords:
            return coords[0], coords[1], f"geocoded: {m.group(0).strip()}"
    return None, None, None


# ------------------------------------------------------------------ text
def clean_text(raw):
    if not raw:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("\u00a0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    out, blank = [], False
    for ln in lines:
        if not ln:
            if not blank and out:
                out.append("")
            blank = True
        else:
            out.append(ln)
            blank = False
    return "\n".join(out).strip()


# ------------------------------------------------------------------ record
def base_record(source, **kw):
    rec = {
        "id": None, "title": "", "price": None, "rent_without_charges": None,
        "charges": None, "deposit": None, "surface": None, "rooms": None,
        "bedrooms": None, "furnished": False, "new_property": False,
        "property_type": "flat", "city": "Nice", "postal_code": "",
        "district": "Nice", "description": "", "photos": [],
        "dpe": None, "ges": None, "dpe_value": None, "ges_value": None,
        "agency": None, "phone": None, "published": "", "updated": "",
        "url": "", "price_per_m2": None, "is_room": False, "is_coloc": False,
        "lat": None, "lon": None, "precision": "unknown",
        "distance_promenade_km": None, "distance_centre_km": None,
        "near_center": False, "loc_note": None,
        "source": source,
    }
    rec.update(kw)
    return rec


def finalize_record(rec, title=None, description=None, district=None):
    """Compute derived fields (distances, flags) once the raw data is in."""
    title = title if title is not None else rec["title"]
    description = description if description is not None else rec["description"]
    text = f"{title} {description}".lower()
    if rec["price"] and rec["surface"]:
        rec["price_per_m2"] = round(rec["price"] / rec["surface"], 1)
    rec["is_room"] = bool(ROOM_WORDS.search(f"{title} {description}")) and (rec["surface"] or 0) < 30
    rec["is_coloc"] = bool(re.search(r"coloc|co-location", f"{title} {description}", re.I))
    rec["title"] = title or "Appartement à Nice"
    rec["description"] = description

    if rec["lat"] is not None and rec["lon"] is not None:
        dp = promenade_distance((rec["lat"], rec["lon"]))
        dc = haversine((rec["lat"], rec["lon"]), CENTRE)
        central_word = any(w in text for w in CENTRAL_WORDS)
        central_district = (district or rec["district"]) in CENTRAL_DISTRICTS
        rec["near_center"] = bool(min(dp, dc) <= 1.5 or central_word or central_district)
        rec["distance_promenade_km"] = round(dp, 2)
        rec["distance_centre_km"] = round(dc, 2)
    else:
        rec["near_center"] = False
        rec["distance_promenade_km"] = None
        rec["distance_centre_km"] = None
    return rec


# ------------------------------------------------------------------ Bien'ici
def resolve_city_zone(city):
    q = urllib.parse.quote(city)
    data = fetch_json(f"{API_SUGGEST}?q={q}", CACHE / f"suggest_{q}.json")
    if not data:
        raise RuntimeError(f"No zone found for {city!r}")
    best = data[0]
    zones = best.get("zoneIds") or []
    log(f"[zone] {best.get('name')} -> {zones}")
    return zones


def fetch_bienici_ads(zone_ids, max_price, refresh=False):
    listings, page, total = [], 1, None
    while True:
        filters = {
            "size": 24, "from": (page - 1) * 24, "page": page,
            "filterType": "rent", "propertyType": ["flat"],
            "zoneIdsByTypes": {"zoneIds": zone_ids},
            "onTheMarket": [True], "maxPrice": max_price,
            "sortBy": "price", "sortOrder": "asc",
        }
        params = {"filters": json.dumps(filters, separators=(",", ":")),
                  "extensionType": "extendedIfNoResult", "leadingCount": "2"}
        url = API_SEARCH + "?" + urllib.parse.urlencode(params)
        payload = fetch_json(url, CACHE / f"search_{page}.json", refresh)
        if not payload:
            break
        ads = payload.get("realEstateAds", [])
        total = payload.get("total", total or 0)
        listings.extend(ads)
        log(f"[bienici] page {page}: +{len(ads)} (total {total})")
        if not ads or len(listings) >= total:
            break
        page += 1
        time.sleep(0.35)
    seen = {}
    for ad in listings:
        seen.setdefault(ad["id"], ad)
    return list(seen.values())


def scrape_bienici(max_price, refresh=False, max_photos=3):
    ads = fetch_bienici_ads(resolve_city_zone("Nice"), max_price, refresh)
    log(f"[bienici] {len(ads)} unique listings <= {max_price} EUR")
    records = []
    for i, ad in enumerate(ads, start=1):
        detail = fetch_json(f"{API_DETAIL}?id={urllib.parse.quote(ad['id'])}",
                            CACHE / "details" / f"{ad['id']}.json", refresh) or {}
        merged = dict(ad)
        merged.update({k: v for k, v in detail.items() if v not in (None, "", [])})
        contact = merged.get("contactRelativeData") or {}
        pos = (merged.get("blurInfo") or {}).get("position") or {}
        lat, lon = pos.get("lat"), pos.get("lon")
        precision = (merged.get("blurInfo") or {}).get("type", "unknown")
        photos = []
        for idx, photo in enumerate((merged.get("photos") or [])[:max_photos], start=1):
            url = photo.get("url") or photo.get("url_photo")
            if not url:
                continue
            name = save_photo(url, f"bi_{re.sub(r'[^A-Za-z0-9_-]', '_', merged['id'])}_{idx}", refresh)
            if name:
                photos.append(name)
            time.sleep(0.05)
        if precision == "cityOrArrondissement":
            lat = lon = None
        pub = merged.get("publicationDate") or ""
        mod = merged.get("modificationDate") or ""
        rec = base_record(
            "Bien'ici",
            id=merged["id"],
            price=merged.get("price"),
            rent_without_charges=merged.get("rentWithoutCharges"),
            charges=merged.get("charges"),
            deposit=merged.get("safetyDeposit"),
            surface=merged.get("surfaceArea"),
            rooms=merged.get("roomsQuantity"),
            bedrooms=merged.get("bedroomsQuantity"),
            furnished=bool(merged.get("isFurnished")),
            new_property=bool(merged.get("newProperty")),
            postal_code=merged.get("postalCode", ""),
            district=(merged.get("district") or {}).get("name") or "Nice",
            dpe=merged.get("energyClassification"),
            ges=merged.get("greenhouseGazClassification"),
            dpe_value=merged.get("energyValue"),
            ges_value=merged.get("greenhouseGazValue"),
            agency=contact.get("agencyNameToDisplay") or contact.get("contactNameToDisplay"),
            phone=contact.get("phoneToDisplay"),
            published="" if pub.startswith("1970") else pub[:10],
            updated="" if mod.startswith("1970") else mod[:10],
            url=f"https://www.bienici.com/annonce/{merged['id']}",
            lat=None if lat is None else round(lat, 6),
            lon=None if lon is None else round(lon, 6),
            precision=precision,
            photos=photos,
        )
        rec = finalize_record(rec, title=clean_text(merged.get("title")) or merged.get("generatedTitle"),
                              description=clean_text(merged.get("description")))
        records.append(rec)
        log(f"  [{i}/{len(ads)}] {rec['price']} EUR - {rec['title'][:55]}")
    return records


# ------------------------------------------------------------------ LocService
LOC_SERVICE_LIST = "https://www.locservice.fr/alpes-maritimes-06/location-particulier-nice{}.html"

LS_TYPES_OK = re.compile(r"/location-(appartement|studio|chambre|colocation|t[1-5]|f[1-5])-nice/")

def scrape_locservice(max_price, refresh=False, max_photos=3, max_pages=20):
    records = []
    seen_ids = set()
    page_no = 1
    while page_no <= max_pages:
        suffix = "" if page_no == 1 else f"-p{page_no}"
        url = LOC_SERVICE_LIST.format(suffix)
        html_text = fetch_html(url, CACHE / "locservice" / f"list_p{page_no}.html", refresh)
        if not html_text:
            break
        page_ids = []
        for m in re.finditer(
                r'<li class="accommodation-ad"[^>]*data-accommodation-id="(\d+)"(.*?)</article>',
                html_text, re.S):
            ad_id, blob = m.group(1), m.group(2)
            if ad_id in seen_ids:
                continue
            link = re.search(r'href="(https://www\.locservice\.fr/alpes-maritimes-06/[^"]+)"', blob)
            if not link or not LS_TYPES_OK.search(link.group(1)):
                continue
            price = re.search(r"(\d[\d\s\u202f\u00a0]*)\s*€\s*/\s*mois", blob)
            surface = re.search(r"(\d+(?:[.,]\d+)?)\s*m²", blob)
            if not price:
                continue
            rec_price = int(re.sub(r"[^\d]", "", price.group(1)))
            if rec_price > max_price:
                continue
            page_ids.append((ad_id, link.group(1), rec_price,
                             float(surface.group(1).replace(",", ".")) if surface else None))
            seen_ids.add(ad_id)
        log(f"[locservice] page {page_no}: {len(page_ids)} flats <= {max_price} EUR")
        if not page_ids:
            break
        for ad_id, ad_url, price, surface in page_ids:
            rec = locservice_detail(ad_id, ad_url, price, surface, refresh, max_photos)
            if rec:
                records.append(rec)
        page_no += 1
        time.sleep(0.4)
    return records


def locservice_detail(ad_id, ad_url, price, surface, refresh, max_photos):
    detail_html = fetch_html(ad_url, CACHE / "locservice" / f"ad_{ad_id}.html", refresh)
    title = description = ""
    dpe = ges = charges = deposit = None
    photos = []
    prop_type = "flat"
    if detail_html:
        t = re.search(r"<title>([^<]*)</title>", detail_html)
        if t:
            # "Location studio meublé à Nice - 780 € - 23 m²" -> "Studio meublé à Nice"
            title = clean_text(t.group(1)).split(" - ")[0]
            title = re.sub(r"^Location\s+", "", title).strip()
            title = title[:1].upper() + title[1:] if title else title
        m = re.search(r"Loyer\s*\(charges comprises\)\s*([\d\s\u00a0]+)\s*€", detail_html)
        if m:
            try:
                price = int(re.sub(r"[^\d]", "", m.group(1))) or price
            except ValueError:
                pass
        m = re.search(r"Charges locatives\s*([\d\s\u00a0]+)\s*€", detail_html)
        if m:
            charges = int(re.sub(r"[^\d]", "", m.group(1)))
        m = re.search(r"dépôt de garantie\s*([\d\s\u00a0]+)\s*€", detail_html, re.I)
        if m:
            deposit = int(re.sub(r"[^\d]", "", m.group(1)))
        m = re.search(r"\(GES\)\s*\?*\s*\?*\s*([A-G])\b", detail_html)
        if m:
            ges = m.group(1)
        m = re.search(r"\(DPE\)\s*\?*\s*\?*\s*([A-G])\b", detail_html)
        if m:
            dpe = m.group(1)
        desc_blocks = re.findall(r"<p[^>]*>(.*?)</p>", detail_html, re.S)
        desc_candidates = [clean_text(b) for b in desc_blocks]
        desc_candidates = [d for d in desc_candidates if d and len(d) > 60]
        description = "\n\n".join(desc_candidates[:8])
        for img in re.findall(r'src="(https://img\.locservice\.fr/[^"]+)"', detail_html):
            if len(photos) >= max_photos:
                break
            name = save_photo(img, f"ls_{ad_id}_{len(photos) + 1}", refresh)
            if name:
                photos.append(name)
    if not title:
        title = f"Appartement à Nice ({price} €)"
    low = title.lower()
    if "studio" in low:
        prop_type, rooms = "studio", 1
    else:
        m = re.search(r"\bT([1-5])\b", title)
        rooms = int(m.group(1)) if m else None
    if not surface:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*m²", title + " " + description)
        surface = float(m.group(1).replace(",", ".")) if m else None
    furnished = bool(re.search(r"meubl", title + " " + description, re.I))
    lat = lon = None
    note = None
    if not description and not photos and not detail_html:
        note = "detail unavailable"
    else:
        lat, lon, note = resolve_location(title, description)
    rec = base_record(
        "LocService",
        id=f"locs-{ad_id}",
        price=price,
        charges=charges,
        deposit=deposit,
        surface=surface,
        rooms=rooms,
        bedrooms=None if rooms in (None, 1) else rooms - 1,
        furnished=furnished,
        property_type=prop_type,
        postal_code="06000",
        district="Nice",
        dpe=dpe,
        ges=ges,
        agency="Particulier (LocService)",
        url=ad_url,
        lat=lat,
        lon=lon,
        precision="geocode" if lat else "unknown",
        photos=photos,
        loc_note=note,
    )
    quartier = find_quartier(f"{title} {description}")
    if quartier:
        rec["district"] = f"Nice - {quartier.title()}"
    rec = finalize_record(rec, title=title, description=description)
    log(f"  [locservice] {price} EUR - {title[:60]} ({note})")
    return rec


# ------------------------------------------------------------------ 123 Loger
L123_LIST = "https://www.123loger.com/location/nice-06000/appartement/?page={}"


def scrape_123loger(max_price, refresh=False, max_photos=3, max_pages=20):
    records = []
    seen = set()
    for page in range(1, max_pages + 1):
        html_text = fetch_html(L123_LIST.format(page), CACHE / "123loger" / f"list_{page}.html", refresh)
        if not html_text:
            break
        cards = re.findall(
            r'href="(https://www\.123loger\.com/location/nice-06000/appartement/[0-9a-f]+/)"',
            html_text)
        new_cards = [c for c in dict.fromkeys(cards) if c not in seen]
        if not new_cards:
            log(f"[123loger] page {page}: no new ads — stopping")
            break
        log(f"[123loger] page {page}: {len(new_cards)} ads")
        for card_url in new_cards:
            seen.add(card_url)
            rec = loger123_detail(card_url, html_text, max_price, refresh, max_photos)
            if rec:
                records.append(rec)
            time.sleep(0.2)
    return records


def loger123_detail(card_url, list_html, max_price, refresh, max_photos):
    slug = card_url.rstrip("/").split("/")[-1]
    blob = ""
    i = list_html.find(card_url)
    if i > 0:
        blob = list_html[i:i + 6000]
    price_m = re.search(r"([\d\s\u00a0]+)\s*€\s*/\s*mois", blob)
    price = int(re.sub(r"[^\d]", "", price_m.group(1))) if price_m else None
    surf_m = re.search(r"(\d+)\s*m2", blob)
    surface = float(surf_m.group(1)) if surf_m else None
    rooms_m = re.search(r"(\d+)\s*pi[eé]ce", blob)
    rooms = int(rooms_m.group(1)) if rooms_m else None
    if price is None or price > max_price:
        return None

    detail_html = fetch_html(card_url, CACHE / "123loger" / f"ad_{slug}.html", refresh)
    title, description = "", ""
    photos = []
    list_title = re.search(r'class="ellipsis"\s*>\s*([^<]+)', blob)
    if list_title:
        title = clean_text(list_title.group(1))
    if detail_html:
        if not title:
            t = re.search(r"<title>([^<]*)</title>", detail_html)
            title = clean_text(t.group(1)).split("|")[0].strip() if t else ""
            title = re.sub(r"\s*\d+\s*€.*$", "", title).strip()
            title = re.sub(r"\s*\(\d[\d\s]+00\)\s*$", "", title).strip()
        imgs = re.findall(
            r'src="(https://www\.123loger\.com/location/uploads/properties/images/'
            r'[0-9a-f]+/[0-9a-f]+\.webp)"', detail_html)
        for img in dict.fromkeys(imgs):
            if len(photos) >= max_photos:
                break
            name = save_photo(img, f"l123_{slug}_{len(photos) + 1}", refresh)
            if name:
                photos.append(name)
        d = re.search(r'<p class="nl2br[^"]*"[^>]*>(.*?)</p>', detail_html, re.S)
        description = clean_text(d.group(1)) if d else ""
        if not description:
            blocks = [clean_text(b) for b in re.findall(r"<p[^>]*>(.*?)</p>", detail_html, re.S)]
            blocks = [b for b in blocks if b and len(b) > 60]
            description = "\n\n".join(blocks[:6])
    if not title:
        title = f"Appartement à Nice ({price} €)"
    deposit = charges = dpe = ges = None
    if detail_html:
        m = re.search(r"[Dd]épôt(?: de garantie)?\s*:?\s*([\d\s\u00a0]+)\s*€", detail_html)
        if m:
            deposit = int(re.sub(r"[^\d]", "", m.group(1)))
        m = re.search(r"[Cc]harges\s*(?:comprises|locatives)?\s*:?\s*([\d\s\u00a0]+)\s*€", detail_html)
        if m:
            charges = int(re.sub(r"[^\d]", "", m.group(1)))
        m = re.search(r"\bDPE\s*:?\s*\??\s*([A-G])\b", detail_html)
        if m:
            dpe = m.group(1)
        m = re.search(r"\bGES\s*:?\s*\??\s*([A-G])\b", detail_html)
        if m:
            ges = m.group(1)
    low = title.lower()
    prop_type = "studio" if "studio" in low else "flat"
    furnished = bool(re.search(r"meubl", title + " " + description, re.I))
    lat, lon, note = (None, None, None)
    if description:
        lat, lon, note = resolve_location(title, description)
    rec = base_record(
        "123 Loger",
        id=f"l123-{slug}",
        price=price,
        charges=charges,
        deposit=deposit,
        surface=surface,
        rooms=rooms,
        bedrooms=None if rooms in (None, 1) else rooms - 1,
        furnished=furnished,
        property_type=prop_type,
        postal_code="06000",
        district="Nice",
        dpe=dpe,
        ges=ges,
        agency="Particulier (123 Loger)",
        url=card_url,
        lat=lat,
        lon=lon,
        precision="geocode" if lat else "unknown",
        photos=photos,
        loc_note=note,
    )
    quartier = find_quartier(f"{title} {description}")
    if quartier:
        rec["district"] = f"Nice - {quartier.title()}"
    rec = finalize_record(rec, title=title, description=description)
    log(f"  [123loger] {price} EUR - {title[:60]} ({note})")
    return rec


# ------------------------------------------------------------------ dedupe
def short_quartier(rec):
    d = (rec.get("district") or "").replace("Nice - ", "").strip().lower()
    return d if d and d != "nice" else None


def same_flat(a, b):
    """Conservative: only exact price+surface+rooms AND a consistent quartier.
    Over-merging hides real options, so we prefer false negatives here."""
    if a["price"] is None or b["price"] is None:
        return False
    if abs(a["price"] - b["price"]) > 0.01:
        return False
    sa, sb = a["surface"], b["surface"]
    if not sa or not sb or abs(sa - sb) > 0.01:
        return False
    if a["rooms"] is None or b["rooms"] is None or a["rooms"] != b["rooms"]:
        return False
    qa, qb = short_quartier(a), short_quartier(b)
    if qa and qb and qa != qb:
        return False
    # one says "chambre", the other doesn't -> different offerings
    if a.get("is_room") != b.get("is_room") or a.get("is_coloc") != b.get("is_coloc"):
        return False
    return True


def dedupe(records):
    out = []
    for r in records:
        target = None
        for o in out:
            if o["source"] != r["source"] and same_flat(o, r):
                target = o
                break
        if target is None:
            r["sources"] = [r["source"]]
            out.append(r)
            continue
        # merge: keep the record with the best data, union the sources
        keep, drop = (target, r) if score(target) >= score(r) else (r, target)
        keep["sources"] = sorted(set(target["sources"] + [r["source"]]))
        for field in ("photos", "description", "dpe", "ges", "charges", "deposit",
                      "phone", "agency", "rooms", "surface", "lat", "lon",
                      "distance_promenade_km", "distance_centre_km", "loc_note", "precision",
                      "near_center", "title", "url", "district"):
            if field == "near_center":
                keep[field] = bool(keep.get(field) or drop.get(field))
            elif not keep.get(field) and drop.get(field):
                keep[field] = drop[field]
        if keep is r:
            out[out.index(target)] = keep
    return out


def score(rec):
    return (len(rec.get("photos") or []) * 2
            + (4 if rec.get("lat") else 0)
            + (2 if rec.get("description") else 0)
            + (1 if rec.get("dpe") else 0)
            + (1 if rec.get("phone") else 0)
            + (1 if rec.get("charges") else 0))


# ------------------------------------------------------------------ main
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="Nice")
    parser.add_argument("--max-price", type=int, default=900)
    parser.add_argument("--max-photos", type=int, default=3)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--sources", default="bienici,locservice,123loger",
                        help="comma-separated: bienici,locservice,123loger")
    args = parser.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    PHOTOS.mkdir(parents=True, exist_ok=True)
    wanted = [s.strip().lower() for s in args.sources.split(",") if s.strip()]

    records = []
    if "bienici" in wanted:
        records += scrape_bienici(args.max_price, args.refresh, args.max_photos)
    if "locservice" in wanted:
        records += scrape_locservice(args.max_price, args.refresh, args.max_photos)
    if "123loger" in wanted:
        records += scrape_123loger(args.max_price, args.refresh, args.max_photos)

    records = dedupe(records)
    records.sort(key=lambda r: (not r["near_center"], r["price"] or 9999, -(r["surface"] or 0)))

    payload = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "sources": ["Bien'ici", "LocService", "123 Loger"],
        "source_url": "https://www.bienici.com/recherche/location/nice-06000/appartement",
        "city": args.city,
        "max_price": args.max_price,
        "total": len(records),
        "listings": records,
    }
    out = DATA / "listings.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    by_source = {}
    for r in records:
        for s in r["sources"]:
            by_source[s] = by_source.get(s, 0) + 1
    log(f"[done] wrote {out}: {len(records)} listings {by_source}, "
        f"{sum(1 for r in records if r['near_center'])} near centre/promenade, "
        f"{sum(1 for r in records if r['lat'])} with coordinates")


if __name__ == "__main__":
    main()