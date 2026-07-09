#!/usr/bin/env python3
"""Look up one or more domains in the "Site Agent Data" sheet (orgs + orgs_research tabs)
via the Sheets API using the site-agent service account. No truncation, instant.

Usage: python3 lookup_domain.py azliver.com nrcresearch.com renstar.net
"""
import sys, json, warnings
warnings.filterwarnings("ignore")
import gspread

CRED = "/Users/yoshichoi/site-agent/credentials/google_service_account.json"
SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
TABS = ["orgs", "orgs_research"]

def norm(d):
    return d.strip().lower().lstrip("www.")

def main(domains):
    domains = [norm(d) for d in domains]
    gc = gspread.service_account(filename=CRED)
    sh = gc.open_by_key(SHEET_ID)
    results = {d: [] for d in domains}
    for tab in TABS:
        try:
            ws = sh.worksheet(tab)
        except gspread.WorksheetNotFound:
            continue
        values = ws.get_all_values()
        if not values:
            continue
        header = values[0]
        # de-duplicate header names (orgs tab repeats hq_address__snippet)
        seen = {}
        hdr = []
        for h in header:
            if h in seen:
                seen[h] += 1
                hdr.append(f"{h}__{seen[h]}")
            else:
                seen[h] = 0
                hdr.append(h)
        try:
            dcol = hdr.index("domain")
        except ValueError:
            continue
        for row in values[1:]:
            if dcol >= len(row):
                continue
            dval = norm(str(row[dcol]))
            if dval in domains:
                clean = {hdr[i]: v for i, v in enumerate(row)
                         if i < len(hdr) and str(v).strip() not in ("", "not_found", "None")}
                clean["__tab__"] = tab
                results[dval].append(clean)
    print(json.dumps(results, indent=2, default=str))

if __name__ == "__main__":
    main(sys.argv[1:] or ["azliver.com", "nrcresearch.com", "renstar.net"])
