#!/usr/bin/env python3
"""Sanity checks on data/listings.json. Run after scraping: python3 check.py"""
import json
import sys
from pathlib import Path

data = json.loads((Path(__file__).parent / "data" / "listings.json").read_text(encoding="utf-8"))
L = data["listings"]
problems = []

def pct(n, d):
    return f"{100 * n / d:.0f}%" if d else "—"

print(f"total listings: {len(L)}  (dataset says {data['total']})")
if len(L) != data["total"]:
    problems.append("total mismatch")

by_primary = {}
for l in L:
    by_primary[l["source"]] = by_primary.get(l["source"], 0) + 1
print("by primary source:", by_primary)

for src in sorted(by_primary):
    S = [l for l in L if l["source"] == src]
    print(f"  {src}: photos={pct(sum(bool(l['photos']) for l in S), len(S))} "
          f"desc={pct(sum(bool(l['description']) for l in S), len(S))} "
          f"coords={pct(sum(bool(l['lat']) for l in S), len(S))} "
          f"quartier={pct(sum(l['district'] != 'Nice' for l in S), len(S))} "
          f"near={pct(sum(l['near_center'] for l in S), len(S))}")

merged = [l for l in L if len(l.get("sources", [])) > 1]
print(f"cross-source merged: {len(merged)}")
for l in merged:
    print(f"  {l['price']}€ / {l['surface']}m² / {l['rooms']}p / {l['district']} -> {l['sources']}")

for l in L:
    if not l["url"]:
        problems.append(f"missing url: {l['id']}")
    if l["price"] is None or l["price"] > data["max_price"]:
        problems.append(f"bad price: {l['id']} {l['price']}")
    if not l["title"]:
        problems.append(f"missing title: {l['id']}")
    if l["source"] not in l.get("sources", [l["source"]]):
        problems.append(f"source not in sources: {l['id']}")

# photo files must exist on disk
photos_dir = Path(__file__).parent / "site" / "photos"
missing_files = [p for l in L for p in l["photos"] if not (photos_dir / p).exists()]
if missing_files:
    problems.append(f"{len(missing_files)} photos referenced but missing on disk")

print()
if problems:
    print("PROBLEMS:")
    for p in problems[:20]:
        print(" -", p)
    sys.exit(1)
print("all checks passed")
