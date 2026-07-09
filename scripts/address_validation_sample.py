"""Random-100 sample of Google Address Validation API (USPS CASS) on canonical `locations`.
Read-only on `locations`: writes a comparison report to a NEW tab 'address_validation_sample' + CSV.
Caches raw JSON to data/address_validation_cache.jsonl (keyed by input address) so a later full run reuses.
Env: GOOGLE_PLACES_API_KEY (same key verify_google.py uses)."""
import os, json, random, time, requests, gspread, csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from gspread.utils import rowcol_to_a1
from dotenv import load_dotenv; load_dotenv("/Users/yoshichoi/site-agent/.env")

KEY = os.environ["GOOGLE_PLACES_API_KEY"]
URL = f"https://addressvalidation.googleapis.com/v1:validateAddress?key={KEY}"
CACHE = "data/address_validation_cache.jsonl"
SHEET = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"

def ckey(street, city, state, zc): return "|".join([street.strip().lower(), city.strip().lower(), state.strip().upper(), zc.strip()])

def load_cache():
    c = {}
    if os.path.exists(CACHE):
        for line in open(CACHE):
            try:
                o = json.loads(line); c[o["k"]] = o["resp"]
            except Exception: pass
    return c

def validate(street, city, state, zc):
    body = {"address": {"regionCode": "US", "addressLines": [street],
            "locality": city, "administrativeArea": state, "postalCode": zc},
            "enableUspsCass": True}
    for attempt in range(4):
        try:
            r = requests.post(URL, json=body, timeout=30)
        except Exception:
            time.sleep(2*(attempt+1)); continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 503):
            time.sleep(2*(attempt+1)); continue
        return {"_error": f"HTTP {r.status_code}", "_body": r.text[:300]}
    return {"_error": "retries_exhausted"}

def parse(resp):
    if not resp or "_error" in (resp or {}):
        return {"google_formatted": "", "usps_street": "", "usps_csz": "", "corrected_zip": "",
                "dpv": resp.get("_error", "error") if resp else "no_response"}
    res = resp.get("result", {})
    gf = res.get("address", {}).get("formattedAddress", "")
    usps = res.get("uspsData", {}) or {}
    std = usps.get("standardizedAddress", {}) or {}
    usps_street = std.get("firstAddressLine", "")
    usps_csz = std.get("cityStateZipAddressLine", "")
    czip = std.get("zipCode", "")
    if std.get("zipCodeExtension"): czip = f"{czip}-{std['zipCodeExtension']}"
    verdict = res.get("verdict", {}) or {}
    dpv = usps.get("dpvConfirmation", "")
    flags = []
    if dpv: flags.append(f"DPV={dpv}")
    if verdict.get("hasInferredComponents"): flags.append("inferred")
    if verdict.get("hasUnconfirmedComponents"): flags.append("unconfirmed")
    if verdict.get("addressComplete"): flags.append("complete")
    return {"google_formatted": gf, "usps_street": usps_street, "usps_csz": usps_csz,
            "corrected_zip": czip, "dpv": " ".join(flags)}

# pull live locations, sample
gc = gspread.service_account(filename="credentials/google_service_account.json")
sh = gc.open_by_key(SHEET)
v = sh.worksheet("locations").get_all_values(); h = v[0]; C = {c: i for i, c in enumerate(h)}
withstreet = [r for r in v[1:] if (r[C["address_street"]] or "").strip()]
random.seed(100)
sample = random.sample(withstreet, 100)
print(f"street rows: {len(withstreet)} | sampling 100", flush=True)

cache = load_cache()
cf = open(CACHE, "a")
def work(row):
    street, city, state, zc = (row[C["address_street"]].strip(), row[C["address_city"]].strip(),
                               row[C["address_state"]].strip(), row[C["address_zip"]].strip())
    k = ckey(street, city, state, zc)
    if k in cache:
        return row, cache[k]
    resp = validate(street, city, state, zc)
    return row, resp

results = []
errs = 0
with ThreadPoolExecutor(max_workers=10) as ex:
    for fut in as_completed([ex.submit(work, r) for r in sample]):
        row, resp = fut.result()
        results.append((row, resp))
        if "_error" in (resp or {}): errs += 1

# write cache for new responses
seen_k = set(cache)
for row, resp in results:
    if "_error" in (resp or {}):
        continue  # never cache errors (would poison re-runs)
    k = ckey(row[C["address_street"]].strip(), row[C["address_city"]].strip(), row[C["address_state"]].strip(), row[C["address_zip"]].strip())
    if k not in seen_k:
        cf.write(json.dumps({"k": k, "resp": resp}) + "\n"); seen_k.add(k)
cf.close()

if errs:
    print(f"!! {errs}/100 returned API errors — sample of error: ", flush=True)
    for row, resp in results:
        if "_error" in (resp or {}):
            print("   ", resp, flush=True); break

COLS = ["domain","location_name","orig_street","orig_city","orig_state","orig_zip",
        "google_formatted","usps_street","usps_city_state_zip","corrected_zip","dpv_verdict","street_changed","zip_changed"]
out = []
sc = zc_ch = 0
for row, resp in results:
    p = parse(resp)
    o_street = row[C["address_street"]].strip(); o_zip = row[C["address_zip"]].strip()
    street_changed = "Y" if p["usps_street"] and p["usps_street"].strip().lower() != o_street.lower() else ""
    zip_changed = "Y" if p["corrected_zip"] and p["corrected_zip"][:5] != o_zip[:5] else ""
    if street_changed: sc += 1
    if zip_changed: zc_ch += 1
    out.append([row[C["domain"]], row[C["location_name"]], o_street, row[C["address_city"]],
                row[C["address_state"]], o_zip, p["google_formatted"], p["usps_street"],
                p["usps_csz"], p["corrected_zip"], p["dpv"], street_changed, zip_changed])

# new report tab + CSV
title = "address_validation_sample"
try:
    ws = sh.worksheet(title); ws.clear()
except gspread.WorksheetNotFound:
    ws = sh.add_worksheet(title=title, rows=len(out)+10, cols=len(COLS))
ws.resize(rows=len(out)+1, cols=len(COLS))
ws.update(values=[COLS]+out, range_name="A1", value_input_option="RAW")
for col in ("F", "J"):  # orig_zip, corrected_zip -> text
    ws.format(f"{col}1:{col}", {"numberFormat": {"type": "TEXT"}})
with open("data/address_validation_sample.csv", "w", newline="") as f:
    csv.writer(f).writerow(COLS); csv.writer(f).writerows(out)

dpv_conf = sum(1 for r in out if "DPV=CONFIRMED" in r[10])
print(f"\nDONE -> tab '{title}' + data/address_validation_sample.csv ({len(out)} rows)", flush=True)
print(f"street changed: {sc} | zip changed/filled: {zc_ch} | DPV CONFIRMED: {dpv_conf} | API errors: {errs}", flush=True)
print("\nsample of changes:", flush=True)
shown = 0
for r in out:
    if r[11] == "Y" and shown < 12:
        print(f"  {r[2][:34]:34} -> {r[7][:34]:34} | {r[10]}", flush=True); shown += 1
