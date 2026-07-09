"""Validate the research_target_locations tab: USPS CASS (Google Address Validation) + offline zip_check.
Reuses the shared address_validation_cache.jsonl (cache hits are free) and the SAME parsing logic as
address_validation_full.py. Adds columns: usps_street, usps_city, usps_state, usps_zip, usps_dpv,
suite_changed, zip_check. Non-destructive to the verbatim address_* fields. Mirrors CSV."""
import os, json, time, re, requests, gspread, csv, collections
from concurrent.futures import ThreadPoolExecutor, as_completed
from gspread.utils import rowcol_to_a1
from dotenv import load_dotenv; load_dotenv("/Users/yoshichoi/site-agent/.env")
import zipcodes

csv.field_size_limit(10_000_000)
KEY = os.environ["GOOGLE_PLACES_API_KEY"]
URL = f"https://addressvalidation.googleapis.com/v1:validateAddress?key={KEY}"
CACHE = "data/address_validation_cache.jsonl"
SHEET = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
TAB = "research_target_locations"
NEWCOLS = ["usps_street", "usps_city", "usps_state", "usps_zip", "usps_dpv", "suite_changed", "zip_check"]
DESIG = re.compile(r'\b(suites?|ste|units?|apt|apartment|bldg|building|fl|flr|floor|rm|room|dept|department|space|spc)\b|#', re.I)

def akey(s, c, st, z): return "|".join([s.strip().lower(), c.strip().lower(), st.strip().upper(), z.strip()[:5]])
def sec_digits(s):
    m = DESIG.search(s or ""); return set(re.findall(r'\d+', s[m.start():])) if m else set()
def validate(street, city, state, zc):
    body = {"address": {"regionCode": "US", "addressLines": [street], "locality": city,
            "administrativeArea": state, "postalCode": zc}, "enableUspsCass": True}
    for attempt in range(4):
        try: r = requests.post(URL, json=body, timeout=30)
        except Exception: time.sleep(2*(attempt+1)); continue
        if r.status_code == 200: return r.json()
        if r.status_code in (429, 500, 503): time.sleep(2*(attempt+1)); continue
        return {"_error": f"HTTP {r.status_code}", "_body": r.text[:200]}
    return {"_error": "retries_exhausted"}
def canon(resp):
    if not resp or "_error" in resp: return None
    res = resp.get("result", {}); usps = res.get("uspsData", {}) or {}; std = usps.get("standardizedAddress", {}) or {}
    street = std.get("firstAddressLine", "")
    if std.get("secondAddressLine"): street = (street + " " + std["secondAddressLine"]).strip()
    zc = std.get("zipCode", "")
    if std.get("zipCodeExtension"): zc = f"{zc}-{std['zipCodeExtension']}"
    return {"street": street, "city": std.get("city", ""), "state": std.get("state", ""),
            "zip": zc, "dpv": usps.get("dpvConfirmation", "") or "no_usps"}
def _ncity(s):
    w = re.sub(r"\bft\b","fort",re.sub(r"\bst\b","saint",re.sub(r"\bmt\b","mount",(s or "").lower())))
    return re.sub(r"[^a-z0-9]","",w)
def zip_flag(zc, city, state):
    z = re.sub(r"\D","",zc or "")[:5]
    if len(z) != 5: return ""
    recs = zipcodes.matching(z)
    if not recs: return "zip_invalid"
    if (state or "").strip() and state.strip().upper() not in {r["state"] for r in recs}: return "state_mismatch"
    if (city or "").strip():
        allowed = set()
        for r in recs:
            allowed.add(_ncity(r["city"]))
            for c in r.get("acceptable_cities", []): allowed.add(_ncity(c))
        if _ncity(city) not in allowed: return "city_mismatch"
    return ""

# ---- pull tab ----
gc = gspread.service_account(filename="credentials/google_service_account.json")
ws = gc.open_by_key(SHEET).worksheet(TAB)
v = ws.get_all_values(); h = v[0]; C = {c: i for i, c in enumerate(h)}
def g(r, f): return (r[C[f]] if C[f] < len(r) else "").strip()
elig = [r for r in v[1:] if all(g(r, f) for f in ["address_street","address_city","address_state","address_zip"])]
uniq = {}
for r in elig:
    k = akey(g(r,"address_street"), g(r,"address_city"), g(r,"address_state"), g(r,"address_zip"))
    uniq.setdefault(k, (g(r,"address_street"), g(r,"address_city"), g(r,"address_state"), g(r,"address_zip")))

cache = {}
if os.path.exists(CACHE):
    for line in open(CACHE):
        try: o = json.loads(line); cache[o["k"]] = o["resp"]
        except Exception: pass
todo = [k for k in sorted(uniq) if k not in cache]
print(f"eligible {len(elig)} | unique {len(uniq)} | cached {len(uniq)-len(todo)} | to call {len(todo)}", flush=True)

# ---- call ----
cf = open(CACHE, "a"); done = errs = 0
with ThreadPoolExecutor(max_workers=15) as ex:
    futs = {ex.submit(lambda k: (k, validate(*uniq[k])), k): k for k in todo}
    for fut in as_completed(futs):
        k, resp = fut.result()
        if "_error" in (resp or {}):
            errs += 1
            if errs <= 3: print("  err:", resp, flush=True)
            continue
        cf.write(json.dumps({"k": k, "resp": resp}) + "\n"); cf.flush(); cache[k] = resp; done += 1
        if done % 100 == 0: print(f"  ...{done}/{len(todo)}", flush=True)
cf.close()
print(f"called {done} | errors {errs}", flush=True)

cmap = {k: canon(cache[k]) for k in uniq if k in cache and canon(cache[k])}
print(f"canonical resolved: {len(cmap)} unique addresses", flush=True)

# ---- build new columns aligned to a fresh pull ----
v2 = ws.get_all_values(); h2 = v2[0]; C2 = {c: i for i, c in enumerate(h2)}
def g2(r, f): return (r[C2[f]] if C2[f] < len(r) else "").strip()
start = C2["usps_street"] if "usps_street" in C2 else len(h2)
matrix = [NEWCOLS]; filledn = suite_ch = 0
for r in v2[1:]:
    if all(g2(r, f) for f in ["address_street","address_city","address_state","address_zip"]):
        k = akey(g2(r,"address_street"), g2(r,"address_city"), g2(r,"address_state"), g2(r,"address_zip"))
        cc = cmap.get(k)
    else: cc = None
    zchk = zip_flag(g2(r,"address_zip"), g2(r,"address_city"), g2(r,"address_state"))
    if cc:
        sc = "Y" if (sec_digits(g2(r,"address_street")) and sec_digits(g2(r,"address_street")) != sec_digits(cc["street"])) else ""
        if sc: suite_ch += 1
        matrix.append([cc["street"], cc["city"], cc["state"], cc["zip"], cc["dpv"], sc, zchk]); filledn += 1
    else:
        matrix.append(["", "", "", "", "", "", zchk])

need = start + len(NEWCOLS)
if ws.col_count < need: ws.add_cols(need - ws.col_count)
ws.update(values=matrix, range_name=f"{rowcol_to_a1(1,start+1)}:{rowcol_to_a1(len(matrix),start+len(NEWCOLS))}", value_input_option="RAW")
zcol = rowcol_to_a1(1, start+4).rstrip("1")  # usps_zip
ws.format(f"{zcol}1:{zcol}", {"numberFormat": {"type": "TEXT"}})
ws.format(f"{rowcol_to_a1(1,start+1).rstrip('1')}1:{rowcol_to_a1(1,start+len(NEWCOLS)).rstrip('1')}1", {"textFormat": {"bold": True}})

final = ws.get_all_values()
with open("data/research_target_locations_validated.csv", "w", newline="") as f:
    csv.writer(f).writerows(final)
dpvd = collections.Counter(cmap[k]["dpv"] for k in cmap)
zc = collections.Counter(row[-1] for row in matrix[1:])
print(f"\nDONE | usps filled rows: {filledn} | suite_changed: {suite_ch}", flush=True)
print("DPV (unique addr):", dict(dpvd), flush=True)
print("zip_check:", {k or "(ok)": v for k, v in zc.items()}, flush=True)
