"""Fill missing address_zip in output_locations.csv via the free US Census geocoder
(street+city+state -> ZIP). Only touches rows that are missing zip AND have street+city+state.
Writes output_locations_zipfilled.csv and prints a fill report. Does not overwrite in place."""
import csv, json, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

PATH = "data/output_locations.csv"
OUT = "data/output_locations_zipfilled.csv"


def blank(r, c): return not (r.get(c) or "").strip()


def lookup_zip(street, city, state):
    q = urllib.parse.urlencode({"street": street, "city": city, "state": state,
                                "benchmark": "Public_AR_Current", "format": "json"})
    url = "https://geocoding.geo.census.gov/geocoder/locations/address?" + q
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            d = json.load(resp)
        m = d.get("result", {}).get("addressMatches", [])
        if m:
            z = m[0].get("addressComponents", {}).get("zip", "").strip()
            return z or None
    except Exception:
        return None
    return None


def main():
    rows = list(csv.DictReader(open(PATH)))
    fields = list(rows[0].keys())
    targets = [(i, r) for i, r in enumerate(rows)
               if blank(r, "address_zip") and not blank(r, "address_street")
               and not blank(r, "address_city") and not blank(r, "address_state")]
    print(f"{len(rows)} rows | {len(targets)} geocodable (missing zip, have street+city+state)")

    filled = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(lookup_zip, r["address_street"], r["address_city"], r["address_state"]): i
                for i, r in targets}
        for fut in as_completed(futs):
            i = futs[fut]
            z = fut.result()
            if z:
                rows[i]["address_zip"] = z
                filled += 1

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    still = sum(1 for r in rows if blank(r, "address_zip"))
    print(f"filled {filled} zips ({filled}/{len(targets)} of geocodable) -> {OUT}")
    print(f"rows still missing zip after fill: {still} (was {len([1 for r in rows if 1])and sum(1 for r in csv.DictReader(open(PATH)) if blank(r,'address_zip'))})")


if __name__ == "__main__":
    main()
