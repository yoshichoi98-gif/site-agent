"""Union the sitemap-recount locations with the basic-pass locations for the new targets, per domain.
Dedupes by (street-number + first street word + zip) for street rows, (city+state) for city-only rows;
keeps the most complete row (full street > city-only > confidence). Drops city-only rows when a
street row exists for the same city (avoids a partial dup of a real address).

Inputs:
  data/sam_new_targets_locations.csv   (basic pass, 13-col, domain=final_url, source=pipeline)
  data/snt_recount_all.csv             (sitemap recount, 11-col, domain=final_url)
Outputs:
  data/sam_new_targets_locations_final.csv  + refreshes the sam_new_targets_locations tab
"""
import csv, re, importlib.util, gspread

zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
BASIC = "data/sam_new_targets_locations.csv"
RECOUNT = "data/snt_recount_all.csv"
OUT = "data/sam_new_targets_locations_final.csv"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]
_CONF = {"high": 3, "medium": 2, "low": 1, "": 0}


def norm(d):
    d = (d or "").strip().lower(); d = re.sub(r"^https?://", "", d); d = re.sub(r"^www\.", "", d)
    return d.split("/")[0].strip()


def key(r):
    s = (r["address_street"] or "").strip().lower()
    if s:
        num = (re.match(r"(\d+)", s) or [""])[0] if re.match(r"(\d+)", s) else ""
        words = re.findall(r"[a-z]+", s)
        z = re.sub(r"\D", "", r.get("address_zip", ""))[:5]
        return ("S", num, words[0] if words else "", z or (r["address_city"] or "").strip().lower())
    return ("C", (r["address_city"] or "").strip().lower(), (r["address_state"] or "").strip().lower())


def better(a, b):
    # prefer street present, then longer street, then higher confidence
    sa, sb = bool(a["address_street"].strip()), bool(b["address_street"].strip())
    if sa != sb: return a if sa else b
    if len(a["address_street"]) != len(b["address_street"]):
        return a if len(a["address_street"]) > len(b["address_street"]) else b
    return a if _CONF.get(a["confidence"], 0) >= _CONF.get(b["confidence"], 0) else b


def load_basic():
    return list(csv.DictReader(open(BASIC)))


def load_recount():
    out = []
    for r in csv.DictReader(open(RECOUNT)):
        out.append({
            "domain": r["domain"], "location_name": r.get("location_name", ""),
            "address_street": r.get("address_street", ""), "address_city": r.get("address_city", ""),
            "address_state": r.get("address_state", ""), "address_zip": r.get("address_zip", ""),
            "phone": r.get("phone", ""), "source_url": r.get("source_url", ""),
            "snippet": r.get("snippet", ""), "confidence": r.get("confidence", ""),
            "validation_status": r.get("validation_status", ""), "source": "sitemap",
            "zip_check": zc.flag(r.get("address_zip", ""), r.get("address_city", ""), r.get("address_state", "")),
        })
    return out


def main():
    rows = load_basic() + load_recount()
    by_dom = {}
    for r in rows:
        by_dom.setdefault(norm(r["domain"]), []).append(r)

    final = []
    for dom, drows in by_dom.items():
        best = {}
        for r in drows:
            k = key(r)
            best[k] = better(best[k], r) if k in best else r
        street_cities = {k[3] if False else (r["address_city"] or "").strip().lower()
                         for k, r in best.items() if k[0] == "S"}
        for k, r in best.items():
            if k[0] == "C" and k[1] in street_cities:
                continue  # city-only dup of a real street address — drop
            final.append(r)

    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore"); w.writeheader(); w.writerows(final)

    gc = gspread.service_account(filename="credentials/google_service_account.json")
    sh = gc.open_by_key(SHEET_ID)
    body = [[r.get(c, "") for c in FIELDS] for r in final]
    try:
        ws = sh.worksheet("sam_new_targets_locations"); ws.clear(); ws.resize(rows=len(body) + 1, cols=len(FIELDS))
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="sam_new_targets_locations", rows=len(body) + 5, cols=len(FIELDS) + 2)
    ws.update([FIELDS] + body, value_input_option="RAW")

    nb, nr = len(load_basic()), len(load_recount())
    src = {}
    for r in final: src[r["source"]] = src.get(r["source"], 0) + 1
    full = sum(1 for r in final if r["address_street"].strip())
    print(f"basic rows: {nb} | recount rows: {nr} | UNION (deduped): {len(final)}")
    print(f"  by source: {src} | full street: {full} ({100*full//max(len(final),1)}%) | domains: {len(by_dom)}")
    print(f"-> {OUT} + tab sam_new_targets_locations")


if __name__ == "__main__":
    main()
