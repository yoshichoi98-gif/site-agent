"""Offline validation of the tightened dedupe() against an existing output CSV.

Reads data/output_locations_firecrawl.csv, applies the new dedupe logic, and
prints every merge/drop decision so we can eyeball correctness BEFORE spending
any Firecrawl credits on a re-run. No network, no writes.

Usage:  python scripts/validate_dedupe.py
"""
import csv
import re
import sys
from collections import defaultdict

CSV_PATH = "data/output_locations_firecrawl.csv"

# Common US road-type / directional abbreviations → canonical form, so that
# "St" and "Street" (etc.) collapse to the same first-word signature.
_ROAD_ABBR = {
    "st": "street", "str": "street", "rd": "road", "ave": "avenue", "av": "avenue",
    "blvd": "boulevard", "ln": "lane", "dr": "drive", "rt": "route", "rte": "route",
    "hwy": "highway", "sq": "square", "pkwy": "parkway", "ct": "court", "pl": "place",
    "ter": "terrace", "cir": "circle", "n": "north", "s": "south", "e": "east", "w": "west",
}


def street_signature(street: str) -> tuple[str, str]:
    """(street_number, normalized_first_word). The number keeps distinct addresses
    on the same street apart (473 vs 477 Lakehurst); the first word collapses
    St/Street/Rd/Road spelling variants of the SAME building."""
    s = street.strip().lower()
    if not s:
        return ("", "")
    # Strip a leading building NAME: "Village Square at Howell, 59 Kent Rd" → "59 Kent Rd".
    # Only when the text BEFORE the first comma is a name (has letters, doesn't start
    # with a street number) — otherwise a trailing ", 2nd Floor" / ", Suite 5" would be
    # mistaken for the real street and clobber it.
    if "," in s:
        head, rest = s.split(",", 1)
        if not re.match(r"\s*\d", head) and re.search(r"[a-z]", head) and re.match(r"\s*\d", rest):
            s = rest
    m = re.match(r"\s*(\d+)", s)
    num = m.group(1) if m else ""
    tail = s[m.end():] if m else s
    word = ""
    for tok in re.findall(r"[a-z]+", tail):
        word = _ROAD_ABBR.get(tok, tok)
        break
    return (num, word)


def _city_key(city: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(city).lower())


def dedupe(locs: list[dict], verbose: bool = False) -> list[dict]:
    """Collapse rows that point at the same physical office.

    Two gaps the old (street, city) key missed, now fixed:
      (a) a street-less row (e.g. homepage city/zip only) that duplicates a real
          street-bearing row in the same zip/city is dropped;
      (b) near-dups with different street SPELLINGS collapse via
          (zip, street-number, normalized-first-word).
    """
    zips_with_street, cities_with_street = set(), set()
    for loc in locs:
        if str(loc.get("address_street", "")).strip():
            z = str(loc.get("address_zip", "")).strip()
            c = _city_key(loc.get("address_city", ""))
            if z:
                zips_with_street.add(z)
            if c:
                cities_with_street.add(c)

    seen: dict[tuple, dict] = {}
    out: list[dict] = []
    for loc in locs:
        street = str(loc.get("address_street", "")).strip()
        z = str(loc.get("address_zip", "")).strip()
        c = _city_key(loc.get("address_city", ""))

        if not street:
            if (z and z in zips_with_street) or (c and c in cities_with_street):
                if verbose:
                    print(f"  DROP street-less   {loc.get('address_city')!r} "
                          f"{z}  (covered by a street-bearing row)")
                continue
            key = ("__nostreet__", z, c)
        else:
            num, word = street_signature(street)
            geo = z if z else c
            key = (geo, num, word)

        if key in seen:
            if verbose:
                kept = seen[key]
                print(f"  MERGE near-dup     {street!r}  ({z})")
                print(f"        into kept →   {kept.get('address_street')!r}")
            continue
        seen[key] = loc
        out.append(loc)
    return out


def main():
    rows = list(csv.DictReader(open(CSV_PATH)))
    print(f"Loaded {len(rows)} rows from {CSV_PATH}\n")
    print("=== Decisions ===")
    deduped = dedupe(rows, verbose=True)
    print(f"\n=== Result: {len(rows)} → {len(deduped)} unique ===")

    # Sanity: show any zip that STILL has >1 row, so we can confirm those are
    # genuinely distinct offices (different street numbers), not missed dups.
    by_zip = defaultdict(list)
    for r in deduped:
        by_zip[r.get("address_zip", "").strip()].append(r)
    print("\n=== Zips still holding >1 row (should be genuinely distinct) ===")
    for z, rs in sorted(by_zip.items()):
        if z and len(rs) > 1:
            print(f"zip {z}:")
            for r in rs:
                print(f"    {r.get('address_street')!r} | {r.get('address_city')}")


if __name__ == "__main__":
    sys.exit(main())
