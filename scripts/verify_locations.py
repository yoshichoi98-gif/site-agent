"""Cheap existence check: batch-geocode every unique address via the free US Census geocoder.
Match/Tie = address resolves to a real US location ("exists"); No_Match = Census couldn't resolve
(NOTE: ~20% false-negative rate — no-match is NOT proof the address is fake). Writes a per-row
report to data/location_verification.csv; does not modify the canonical file."""
import csv, io, re, requests
from collections import Counter

PATH = "data/output_locations.csv"
OUT = "data/location_verification.csv"
ENDPOINT = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
CHUNK = 9000


def strip_suite(s):
    return re.split(r"\b(suite|ste|unit|apt|floor|fl|bldg|building|rm|room|dept|#)\b", s or "",
                    flags=re.I)[0].strip().rstrip(",")


def batch(items):
    """items: list of (key, street, city, state, zip) -> dict key->indicator."""
    buf = io.StringIO(); w = csv.writer(buf)
    for k, st, ci, sta, z in items:
        w.writerow([k, st, ci, sta, z])
    resp = requests.post(ENDPOINT, files={"addressFile": ("a.csv", buf.getvalue(), "text/csv")},
                         data={"benchmark": "Public_AR_Current"}, timeout=600)
    resp.raise_for_status()
    res = {}
    for row in csv.reader(io.StringIO(resp.text)):
        if len(row) > 2:
            res[row[0]] = row[2]   # Match / No_Match / Tie
    return res


def main():
    rows = list(csv.DictReader(open(PATH)))
    # unique addresses (street-without-suite + city + state + zip)
    uniq = {}
    for r in rows:
        s = (r.get("address_street") or "").strip()
        if not s:
            continue
        k = (strip_suite(s).lower(), (r.get("address_city") or "").lower(),
             (r.get("address_state") or "").upper(), (r.get("address_zip") or ""))
        uniq.setdefault(k, (strip_suite(s), r.get("address_city", ""), r.get("address_state", ""), r.get("address_zip", "")))
    keys = list(uniq)
    print(f"{len(rows)} rows | {len(keys)} unique addresses to verify")

    status = {}
    items = [(str(i), *uniq[k]) for i, k in enumerate(keys)]
    for start in range(0, len(items), CHUNK):
        chunk = items[start:start + CHUNK]
        res = batch(chunk)
        for sid, ind in res.items():
            status[keys[int(sid)]] = ind
        print(f"  batch {start // CHUNK + 1}: {len(res)} results")

    # write per-row report
    cnt = Counter()
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["domain", "address_street", "address_city", "address_state", "address_zip", "verify"])
        for r in rows:
            s = (r.get("address_street") or "").strip()
            if not s:
                v = "no_street"
            else:
                k = (strip_suite(s).lower(), (r.get("address_city") or "").lower(),
                     (r.get("address_state") or "").upper(), (r.get("address_zip") or ""))
                v = status.get(k, "No_Match")
            cnt[v] += 1
            w.writerow([r["domain"], r.get("address_street", ""), r.get("address_city", ""),
                        r.get("address_state", ""), r.get("address_zip", ""), v])
    total = sum(cnt.values())
    print(f"\n=== verification (per row, {total} rows) ===")
    for k, c in cnt.most_common():
        print(f"  {k:10} {c:6}  ({100*c/total:.1f}%)")
    verified = cnt.get("Match", 0) + cnt.get("Tie", 0)
    print(f"  -> CONFIRMED-real: {verified} ({100*verified/total:.1f}%)  | report: {OUT}")


if __name__ == "__main__":
    main()
