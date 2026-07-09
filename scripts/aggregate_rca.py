"""Step 3 of the RCA rollup: take the per-practice recount output and roll ALL locations up under
retinaconsultantsofamerica.com. Practice identity preserved in location_name + a practice_domain column.
Within-RCA dedup by (practice_domain, street, zip). Builds an overlap report vs sam_new_targets /
orgs_research. Writes data/rca_locations_final.csv + pushes the retinaconsultantsofamerica_locations tab."""
import csv, re, importlib.util, gspread

zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
PARENT = "retinaconsultantsofamerica.com"
SRC_URL = "https://www.retinaconsultantsofamerica.com/about-rca/practices"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status",
          "source", "zip_check", "practice_domain"]


def norm(d):
    d = (d or "").strip().lower(); d = re.sub(r"^https?://", "", d); d = re.sub(r"^www\.", "", d)
    return d.split("/")[0].strip()


def main():
    name_by_dom = {norm(r["practice_domain"]): r["practice_name"]
                   for r in csv.DictReader(open("data/rca_practices.csv")) if r["practice_domain"].strip()}

    rec = list(csv.DictReader(open("data/rca_locations.csv")))
    rows, seen = [], set()
    for r in rec:
        pdom = norm(r["domain"])
        pname = name_by_dom.get(pdom, pdom)
        st = (r.get("address_street") or "").strip()
        z = re.sub(r"\D", "", r.get("address_zip", ""))[:5]
        num = (re.match(r"(\d+)", st.lower()) or [""])[0] if re.match(r"\d", st) else ""
        kw = re.findall(r"[a-z]+", st.lower())
        k = (pdom, num, kw[0] if kw else "", z or (r.get("address_city") or "").strip().lower())
        if k in seen:
            continue
        seen.add(k)
        loc = (r.get("location_name") or "").strip()
        rows.append({
            "domain": PARENT,
            "location_name": f"{pname} — {loc}" if loc else pname,
            "address_street": st, "address_city": r.get("address_city", ""),
            "address_state": r.get("address_state", ""), "address_zip": r.get("address_zip", ""),
            "phone": r.get("phone", ""), "source_url": r.get("source_url", ""),
            "snippet": r.get("snippet", ""), "confidence": r.get("confidence", ""),
            "validation_status": r.get("validation_status", ""), "source": "rca_rollup",
            "zip_check": zc.flag(r.get("address_zip", ""), r.get("address_city", ""), r.get("address_state", "")),
            "practice_domain": pdom,
        })

    with open("data/rca_locations_final.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)

    # overlap report vs existing datasets
    snt = {norm(r.get("final_url") or r.get("Domain") or "") for r in csv.DictReader(open("data/sam_new_targets.csv"))}
    org = {norm(r["domain"]) for r in csv.DictReader(open("data/output_orgs_research.csv")) if norm(r["domain"])}
    practice_doms = sorted(set(name_by_dom))
    in_snt = [d for d in practice_doms if d in snt]
    in_org = [d for d in practice_doms if d in org]

    # push tab
    gc = gspread.service_account(filename="credentials/google_service_account.json")
    sh = gc.open_by_key(SHEET_ID)
    body = [[r[c] for c in FIELDS] for r in rows]
    try:
        ws = sh.worksheet("retinaconsultantsofamerica_locations"); ws.clear(); ws.resize(rows=len(body) + 1, cols=len(FIELDS))
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="retinaconsultantsofamerica_locations", rows=len(body) + 5, cols=len(FIELDS) + 2)
    ws.update([FIELDS] + body, value_input_option="RAW")

    import collections
    perp = collections.Counter(r["practice_domain"] for r in rows)
    full = sum(1 for r in rows if r["address_street"].strip())
    print(f"RCA rollup: {len(rows)} locations across {len(perp)} practices | full street: {full} ({100*full//max(len(rows),1)}%)")
    zerop = [d for d in practice_doms if d not in perp]
    print(f"practices with 0 locations extracted ({len(zerop)}): {zerop}")
    print(f"\nOVERLAP — member domains already in sam_new_targets ({len(in_snt)}): {in_snt}")
    print(f"OVERLAP — member domains already in orgs_research ({len(in_org)}): {in_org}")
    print(f"\n-> data/rca_locations_final.csv + tab retinaconsultantsofamerica_locations (gid={ws.id})")


if __name__ == "__main__":
    main()
