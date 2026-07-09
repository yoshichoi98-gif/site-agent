"""Targeted USPS CASS (Google Address Validation) for the 3 a1clinical.com rows only.
Surgical: pulls live, matches by domain+street, writes ONLY usps_street..suite_changed (O:T) +
gmaps_verified for those rows. Caches responses to the shared jsonl. No full-tab rewrite."""
import os, re, json, csv, requests, gspread
from dotenv import load_dotenv; load_dotenv("/Users/yoshichoi/site-agent/.env")
from gspread.cell import Cell

KEY = os.environ["GOOGLE_PLACES_API_KEY"]
URL = f"https://addressvalidation.googleapis.com/v1:validateAddress?key={KEY}"
CACHE = "data/address_validation_cache.jsonl"
SHEET = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "a1clinical.com"
DESIG = re.compile(r'\b(suites?|ste|units?|apt|apartment|bldg|building|fl|flr|floor|rm|room|dept|department|space|spc)\b|#', re.I)

def akey(street, city, state, zc):
    return "|".join([street.strip().lower(), city.strip().lower(), state.strip().upper(), zc.strip()[:5]])

def sec_digits(s):
    m = DESIG.search(s or "")
    return set(re.findall(r'\d+', s[m.start():])) if m else set()

def validate(street, city, state, zc):
    body = {"address": {"regionCode": "US", "addressLines": [street], "locality": city,
            "administrativeArea": state, "postalCode": zc}, "enableUspsCass": True}
    r = requests.post(URL, json=body, timeout=30)
    r.raise_for_status()
    return r.json()

def canon(resp):
    res = resp.get("result", {}); usps = res.get("uspsData", {}) or {}
    std = usps.get("standardizedAddress", {}) or {}
    street = std.get("firstAddressLine", "")
    if std.get("secondAddressLine"): street = (street + " " + std["secondAddressLine"]).strip()
    zc = std.get("zipCode", "")
    if std.get("zipCodeExtension"): zc = f"{zc}-{std['zipCodeExtension']}"
    return {"street": street, "city": std.get("city", ""), "state": std.get("state", ""),
            "zip": zc, "dpv": usps.get("dpvConfirmation", "") or "no_usps"}

def main():
    gc = gspread.service_account(filename="credentials/google_service_account.json")
    ws = gc.open_by_key(SHEET).worksheet("locations")
    v = ws.get_all_values(); h = v[0]; C = {c: i for i, c in enumerate(h)}
    targets = [(i + 2, r) for i, r in enumerate(v[1:])
               if (r[C["domain"]] or "").strip().lower() == DOMAIN]
    print(f"matched {len(targets)} {DOMAIN} rows")

    cf = open(CACHE, "a")
    cells = []
    for srow, r in targets:
        s, c, st, z = (r[C["address_street"]].strip(), r[C["address_city"]].strip(),
                       r[C["address_state"]].strip(), r[C["address_zip"]].strip())
        resp = validate(s, c, st, z)
        cf.write(json.dumps({"k": akey(s, c, st, z), "resp": resp}) + "\n"); cf.flush()
        cc = canon(resp)
        sc = "Y" if (sec_digits(s) and sec_digits(s) != sec_digits(cc["street"])) else ""
        vals = {"usps_street": cc["street"], "usps_city": cc["city"], "usps_state": cc["state"],
                "usps_zip": cc["zip"], "usps_dpv": cc["dpv"], "suite_changed": sc,
                "gmaps_verified": "exists"}
        for col, val in vals.items():
            cells.append(Cell(srow, C[col] + 1, val))
        print(f"  row {srow}: {s} -> usps '{cc['street']}, {cc['city']}, {cc['state']} {cc['zip']}' | dpv={cc['dpv']} | suite_changed={sc or '-'}")
    cf.close()

    ws.update_cells(cells, value_input_option="RAW")
    print(f"wrote {len(cells)} cells")

    final = ws.get_all_values()
    with open("data/output_locations.csv", "w", newline="") as f:
        csv.writer(f).writerows(final)
    print("local re-synced")

if __name__ == "__main__":
    main()
