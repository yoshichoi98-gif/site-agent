import csv, json, urllib.parse, urllib.request

rows = list(csv.DictReader(open("data/output_locations.csv")))
def b(r, c): return not (r.get(c) or "").strip()
samp = [r for r in rows if b(r, "address_zip") and not b(r, "address_street")
        and not b(r, "address_city") and not b(r, "address_state")][:8]

for r in samp:
    q = urllib.parse.urlencode({"street": r["address_street"], "city": r["address_city"],
                                "state": r["address_state"], "benchmark": "Public_AR_Current",
                                "format": "json"})
    url = "https://geocoding.geo.census.gov/geocoder/locations/address?" + q
    try:
        with urllib.request.urlopen(url, timeout=25) as resp:
            d = json.load(resp)
        m = d.get("result", {}).get("addressMatches", [])
        if m:
            zipc = m[0].get("addressComponents", {}).get("zip", "")
            print(f"  {r['address_street']}, {r['address_city']} {r['address_state']}  ->  ZIP {zipc}")
        else:
            print(f"  {r['address_street']}, {r['address_city']} {r['address_state']}  ->  NO MATCH")
    except Exception as e:
        print("  ERR", str(e)[:90])
