#!/usr/bin/env python3
"""
Collect rental listings in Nice (<= MAX_PRICE) from Bien'ici's public JSON API.

Outputs:
    data/listings.json   full dataset used by build.py
    site/photos/*.jpg    one folder of photos per listing

Only the Python standard library is required.
Usage:
    python3 scrape.py                # uses cache when available
    python3 scrape.py --refresh      # re-downloads everything
    python3 scrape.py --max-price 900 --city nice
"""

import argparse
import base64
import hashlib
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

# Promenade des Anglais, approximated as a west -> east polyline (lat, lon).
PROMENADE = [
    (43.6630, 7.2150), (43.6650, 7.2230), (43.6690, 7.2350),
    (43.6750, 7.2470), (43.6820, 7.2560), (43.6880, 7.2620),
    (43.6920, 7.2660), (43.6948, 7.2695), (43.6960, 7.2740),
]
# Place Massena / heart of the city centre.
CENTRE = (43.6990, 7.2720)

# Districts that count as "centre or next to the Promenade".
CENTRAL_DISTRICTS = {
    "Nice - Centre-ville", "Nice - Vieux Nice", "Nice - Carré d'or",
    "Nice - Carabacel", "Nice - Thiers - Musicien", "Nice - Médecin",
    "Nice - Vernier", "Nice - Le Port", "Nice - Garibaldi",
    "Nice - Acropolis - République", "Nice - Mont-Boron",
    "Nice - Baumettes", "Nice - Californie - Carras",
    "Nice - Sainte-Marguerite", "Nice - Fabron", "Nice - Gambetta",
    "Nice - Saint-Lambert - Bas-Cimiez",
}
CENTRAL_WORDS = [
    "promenade", "centre-ville", "centre ville", "vieux nice", "vieux-nice",
    "carré d'or", "carre d'or", "masséna", "massena", "garibaldi",
    "acropolis", "république", "republique", "le port", "port de nice",
    "thiers", "musicien", "carabacel", "vernier", "baumettes",
    "californie", "carras", "fabron", "sainte-marguerite", "mont-boron",
]
ROOM_WORDS = re.compile(r"\b(chambre|colocation|coloc|co-location|room)\b", re.I)


def log(msg):
    print(msg, flush=True)


def get_json(url, cache_path, refresh=False, retries=3):
    if cache_path.exists() and not refresh:
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
            return payload
        except Exception as exc:  # network hiccup, rate limit...
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Could not fetch {url}: {last}")


def get_bytes(url, cache_path, refresh=False, retries=3):
    if cache_path.exists() and cache_path.stat().st_size > 500 and not refresh:
        return cache_path.read_bytes()
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
            with urllib.request.urlopen(req, timeout=45) as resp:
                blob = resp.read()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(blob)
            return blob
        except Exception as exc:
            last = exc
            time.sleep(1.0 * (attempt + 1))
    log(f"  [photo] skipped ({last})")
    return None


def resolve_city_zone(city):
    """Turn a city name into Bien'ici zone ids."""
    q = urllib.parse.quote(city)
    cache = CACHE / f"suggest_{q}.json"
    data = get_json(f"{API_SUGGEST}?q={q}", cache)
    if not data:
        raise RuntimeError(f"No zone found for {city!r}")
    best = data[0]
    zones = best.get("zoneIds") or []
    log(f"[zone] {best.get('name')} -> {zones}")
    return zones


def fetch_search(zone_ids, max_price, refresh=False):
    listings = []
    page = 1
    total = None
    while True:
        filters = {
            "size": 24,
            "from": (page - 1) * 24,
            "page": page,
            "filterType": "rent",
            "propertyType": ["flat"],
            "zoneIdsByTypes": {"zoneIds": zone_ids},
            "onTheMarket": [True],
            "maxPrice": max_price,
            "sortBy": "price",
            "sortOrder": "asc",
        }
        params = {
            "filters": json.dumps(filters, separators=(",", ":")),
            "extensionType": "extendedIfNoResult",
            "leadingCount": "2",
        }
        url = API_SEARCH + "?" + urllib.parse.urlencode(params)
        payload = get_json(url, CACHE / f"search_{page}.json", refresh)
        ads = payload.get("realEstateAds", [])
        total = payload.get("total", total or 0)
        listings.extend(ads)
        log(f"[search] page {page}: +{len(ads)} (total {total})")
        if not ads or len(listings) >= total:
            break
        page += 1
        time.sleep(0.35)
    # de-duplicate by id, keep the cheapest version if duplicated
    seen = {}
    for ad in listings:
        seen.setdefault(ad["id"], ad)
    return list(seen.values())


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
        return ((q[1] - a[1]) * math.cos(lat0) * 111.32,
                (q[0] - a[0]) * 110.57)
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


def location_info(ad, description):
    blur = ad.get("blurInfo") or {}
    pos = blur.get("position") or {}
    lat, lon = pos.get("lat"), pos.get("lon")
    precision = blur.get("type", "unknown")
    district = (ad.get("district") or {}).get("name") or "Nice"
    text = f"{ad.get('title', '')} {description}".lower()

    if lat is None or lon is None:
        return {
            "lat": None, "lon": None, "precision": precision,
            "distance_promenade_km": None, "distance_centre_km": None,
            "near_center": any(w in text for w in CENTRAL_WORDS) or district in CENTRAL_DISTRICTS,
        }

    dp = promenade_distance((lat, lon))
    dc = haversine((lat, lon), CENTRE)
    if precision == "cityOrArrondissement":
        # Position is the city centroid, not the flat: distances are meaningless.
        near = district in CENTRAL_DISTRICTS or any(w in text for w in CENTRAL_WORDS)
        dp_out = dc_out = None
    else:
        near = min(dp, dc) <= 1.5 or district in CENTRAL_DISTRICTS
        dp_out, dc_out = round(dp, 2), round(dc, 2)
    return {
        "lat": round(lat, 6), "lon": round(lon, 6), "precision": precision,
        "distance_promenade_km": dp_out, "distance_centre_km": dc_out,
        "near_center": bool(near),
    }


def enrich(ad, refresh=False):
    detail_cache = CACHE / "details" / f"{ad['id']}.json"
    try:
        detail = get_json(f"{API_DETAIL}?id={urllib.parse.quote(ad['id'])}",
                          detail_cache, refresh)
    except Exception as exc:
        log(f"  [detail] {ad['id']}: {exc}")
        detail = {}
    merged = dict(ad)
    merged.update({k: v for k, v in detail.items() if v not in (None, "", [])})
    return merged


def download_photos(ad, limit, refresh=False):
    photos = ad.get("photos") or []
    saved = []
    for idx, photo in enumerate(photos[:limit], start=1):
        url = photo.get("url") or photo.get("url_photo")
        if not url:
            continue
        ext = ".jpg"
        name = f"{re.sub(r'[^A-Za-z0-9_-]', '_', ad['id'])}_{idx}{ext}"
        target = PHOTOS / name
        blob = get_bytes(url, target, refresh)
        if blob:
            saved.append(name)
        time.sleep(0.05)
    return saved


def build_record(ad, photos):
    description = clean_text(ad.get("description"))
    loc = location_info(ad, description)
    price = ad.get("price")
    surface = ad.get("surfaceArea")
    title = clean_text(ad.get("title")) or (ad.get("generatedTitle") or "Appartement")
    district = (ad.get("district") or {}).get("name") or "Nice"
    contact = ad.get("contactRelativeData") or {}
    text = f"{title} {description}"
    is_room = bool(ROOM_WORDS.search(text)) and (surface or 0) < 30
    return {
        "id": ad["id"],
        "title": title,
        "price": price,
        "rent_without_charges": ad.get("rentWithoutCharges"),
        "charges": ad.get("charges"),
        "deposit": ad.get("safetyDeposit"),
        "surface": surface,
        "rooms": ad.get("roomsQuantity"),
        "bedrooms": ad.get("bedroomsQuantity"),
        "furnished": bool(ad.get("isFurnished")),
        "new_property": bool(ad.get("newProperty")),
        "property_type": ad.get("propertyType", "flat"),
        "city": ad.get("city", "Nice"),
        "postal_code": ad.get("postalCode", ""),
        "district": district,
        "description": description,
        "photos": photos,
        "dpe": ad.get("energyClassification"),
        "ges": ad.get("greenhouseGazClassification"),
        "dpe_value": ad.get("energyValue"),
        "ges_value": ad.get("greenhouseGazValue"),
        "agency": contact.get("agencyNameToDisplay") or contact.get("contactNameToDisplay"),
        "phone": contact.get("phoneToDisplay"),
        "published": (ad.get("publicationDate") or "")[:10] if not (ad.get("publicationDate") or "").startswith("1970") else "",
        "updated": (ad.get("modificationDate") or "")[:10] if not (ad.get("modificationDate") or "").startswith("1970") else "",
        "url": f"https://www.bienici.com/annonce/{ad['id']}",
        "price_per_m2": round(price / surface, 1) if price and surface else None,
        "is_room": is_room,
        "is_coloc": bool(re.search(r"coloc|co-location", text, re.I)),
        **loc,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="Nice")
    parser.add_argument("--max-price", type=int, default=900)
    parser.add_argument("--max-photos", type=int, default=3)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    PHOTOS.mkdir(parents=True, exist_ok=True)

    zones = resolve_city_zone(args.city)
    ads = fetch_search(zones, args.max_price, args.refresh)
    log(f"[search] {len(ads)} unique listings <= {args.max_price} EUR")

    records = []
    for i, ad in enumerate(ads, start=1):
        log(f"[{i}/{len(ads)}] {ad.get('price')} EUR - {(ad.get('title') or '')[:60]}")
        full = enrich(ad, args.refresh)
        photos = download_photos(full, args.max_photos, args.refresh)
        records.append(build_record(full, photos))
        time.sleep(0.15)

    records.sort(key=lambda r: (
        not r["near_center"], r["price"] or 9999, -(r["surface"] or 0)
    ))

    payload = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": "Bien'ici",
        "source_url": f"https://www.bienici.com/recherche/location/{args.city.lower()}-06000/appartement?prix-max={args.max_price}",
        "city": args.city,
        "max_price": args.max_price,
        "total": len(records),
        "listings": records,
    }
    out = DATA / "listings.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[done] wrote {out} ({len(records)} listings, "
        f"{sum(1 for r in records if r['near_center'])} near centre/promenade)")


if __name__ == "__main__":
    main()
