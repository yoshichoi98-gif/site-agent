"""Full Google Address Validation (USPS CASS) over canonical `locations`.
- Eligible rows: street+city+state+zip all filled.
- Dedup: 1 API call per unique address; result propagated to all rows sharing it.
- Cap: MAX_NEW_CALLS new (billable) calls this run to stay inside the free credit; rest deferred
  (resumable — re-run later continues from the raw-response cache, never re-bills a hit).
- Adds NEW columns to `locations` (non-destructive; verbatim address_* untouched):
  canonical_street, canonical_city, canonical_state, canonical_zip, canonical_dpv, suite_changed.
- Writes ONLY the new columns (O:T) aligned to a fresh pull; mirrors CSV.
"""
import os, json, time, re, requests, gspread, csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv; load_dotenv("/Users/yoshichoi/site-agent/.env")

KEY = os.environ["GOOGLE_PLACES_API_KEY"]
URL = f"https://addressvalidation.googleapis.com/v1:validateAddress?key={KEY}"
CACHE = "data/address_validation_cache.jsonl"
SHEET = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
MAX_NEW_CALLS = 16900          # ~$287 + the $1.70 sample already spent  (free credit = $290)
NEWCOLS = ["usps_street", "usps_city", "usps_state", "usps_zip", "usps_dpv", "suite_changed"]
DESIG = re.compile(r'\b(suites?|ste|units?|apt|apartment|bldg|building|fl|flr|floor|rm|room|dept|department|space|spc)\b|#', re.I)

def akey(street, city, state, zc):
    return "|".join([street.strip().lower(), city.strip().lower(), state.strip().upper(), zc.strip()[:5]])

def sec_digits(s):
    m = DESIG.search(s or "")
    return set(re.findall(r'\d+', s[m.start():])) if m else set()

def load_cache():
    c = {}
    if os.path.exists(CACHE):
        for line in open(CACHE):
            try:
                o = json.loads(line); c[o["k"]] = o["resp"]
            except Exception: pass
    return c

def validate(street, city, state, zc):
    body = {"address": {"regionCode": "US", "addressLines": [street], "locality": city,
            "administrativeArea": state, "postalCode": zc}, "enableUspsCass": True}
    for attempt in range(4):
        try:
            r = requests.post(URL, json=body, timeout=30)
        except Exception:
            time.sleep(2*(attempt+1)); continue
        if r.status_code == 200: return r.json()
        if r.status_code in (429, 500, 503): time.sleep(2*(attempt+1)); continue
        return {"_error": f"HTTP {r.status_code}", "_body": r.text[:200]}
    return {"_error": "retries_exhausted"}

def canon(resp):
    if not resp or "_error" in resp: return None
    res = resp.get("result", {}); usps = res.get("uspsData", {}) or {}
    std = usps.get("standardizedAddress", {}) or {}
    street = std.get("firstAddressLine", "")
    if std.get("secondAddressLine"): street = (street + " " + std["secondAddressLine"]).strip()
    zc = std.get("zipCode", "")
    if std.get("zipCodeExtension"): zc = f"{zc}-{std['zipCodeExtension']}"
    return {"street": street, "city": std.get("city", ""), "state": std.get("state", ""),
            "zip": zc, "dpv": usps.get("dpvConfirmation", "") or "no_usps"}

# ---- pull, eligible, unique ----
gc = gspread.service_account(filename="credentials/google_service_account.json")
sh = gc.open_by_key(SHEET)
v = sh.worksheet("locations").get_all_values(); h = v[0]; C = {c: i for i, c in enumerate(h)}
def filled(r, f): return bool((r[C[f]] or "").strip())
elig = [r for r in v[1:] if all(filled(r, f) for f in ["address_street", "address_city", "address_state"])]
uniq = {}  # key -> (street,city,state,zip)
for r in elig:
    k = akey(r[C["address_street"]], r[C["address_city"]], r[C["address_state"]], r[C["address_zip"]])
    if k not in uniq:
        uniq[k] = (r[C["address_street"]].strip(), r[C["address_city"]].strip(), r[C["address_state"]].strip(), r[C["address_zip"]].strip())

cache = load_cache()
todo = [k for k in sorted(uniq) if k not in cache]
batch = todo[:MAX_NEW_CALLS]
print(f"eligible rows {len(elig)} | unique {len(uniq)} | cached {len(uniq)-len(todo)} | to call now {len(batch)} | deferred {len(todo)-len(batch)}", flush=True)

# ---- call (threaded, incremental cache write) ----
cf = open(CACHE, "a")
done = errs = 0
def work(k):
    s, c, st, z = uniq[k]
    return k, validate(s, c, st, z)
with ThreadPoolExecutor(max_workers=15) as ex:
    for fut in as_completed([ex.submit(work, k) for k in batch]):
        k, resp = fut.result()
        if "_error" in (resp or {}):
            errs += 1
            if errs <= 3: print("  err:", resp, flush=True)
            continue  # don't cache errors
        cf.write(json.dumps({"k": k, "resp": resp}) + "\n"); cf.flush()
        cache[k] = resp
        done += 1
        if done % 1000 == 0: print(f"  ...{done}/{len(batch)} called  (~${done*0.017:,.0f})", flush=True)
cf.close()
print(f"called {done} | errors {errs}", flush=True)

# ---- build canonical map ----
cmap = {k: canon(cache[k]) for k in uniq if k in cache and canon(cache[k])}
print(f"canonical resolved for {len(cmap)} unique addresses", flush=True)

# ---- write new columns to a FRESH pull (only O:T), mirror CSV ----
ws = sh.worksheet("locations")
v2 = ws.get_all_values(); h2 = v2[0]; C2 = {c: i for i, c in enumerate(h2)}
# write INTO existing usps_* columns if present, else append at the end
start = C2["usps_street"] if "usps_street" in C2 else len(h2)
def filled2(r, f): return bool((r[C2[f]] or "").strip())
matrix = [NEWCOLS]
filledn = suite_ch = 0
for r in v2[1:]:
    if all(filled2(r, f) for f in ["address_street", "address_city", "address_state"]):
        k = akey(r[C2["address_street"]], r[C2["address_city"]], r[C2["address_state"]], r[C2["address_zip"]])
        cc = cmap.get(k)
    else:
        cc = None
    if cc:
        sc = "Y" if (sec_digits(r[C2["address_street"]]) and sec_digits(r[C2["address_street"]]) != sec_digits(cc["street"])) else ""
        if sc: suite_ch += 1
        matrix.append([cc["street"], cc["city"], cc["state"], cc["zip"], cc["dpv"], sc]); filledn += 1
    else:
        matrix.append(["", "", "", "", "", ""])

from gspread.utils import rowcol_to_a1
need_cols = start + len(NEWCOLS)
if ws.col_count < need_cols:
    ws.add_cols(need_cols - ws.col_count)   # grow grid so O:T exists
rng = f"{rowcol_to_a1(1, start+1)}:{rowcol_to_a1(len(matrix), start+len(NEWCOLS))}"
ws.update(values=matrix, range_name=rng, value_input_option="RAW")
ws.format(f"{rowcol_to_a1(1, start+4).rstrip('1')}1:{rowcol_to_a1(1, start+4).rstrip('1')}", {"numberFormat": {"type": "TEXT"}})  # canonical_zip text

final = ws.get_all_values()
with open("data/output_locations.csv", "w", newline="") as f:
    csv.writer(f).writerows(final)
print(f"\nDONE | rows with canonical filled: {filledn} | suite_changed flagged: {suite_ch} | new cols at {rowcol_to_a1(1,start+1).rstrip('1')}..{rowcol_to_a1(1,start+len(NEWCOLS)).rstrip('1')}", flush=True)
import collections
dpvd = collections.Counter(cmap[k]["dpv"] for k in cmap)
print("DPV breakdown (unique addresses):", dict(dpvd), flush=True)
print(f"deferred to next run (free in July): {len(todo)-len(batch)} unique", flush=True)
