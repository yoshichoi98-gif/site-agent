"""Mirror the staged SAM-missing extraction into the Site Agent Data spreadsheet as two tabs:
  sam_missing_orgs       <- data/output_orgs_sam_missing.csv  (+ final_url joined in after domain)
  sam_missing_locations  <- data/output_locations_sam_missing.csv
Does NOT touch the canonical output_orgs_research.csv / output_locations.csv / locations tab.
Re-runnable: refresh the tabs anytime (e.g. when the run finishes)."""
import csv, re, gspread

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
ORGS_CSV = "data/output_orgs_sam_missing.csv"
LOCS_CSV = "data/output_locations_sam_missing.csv"
FINAL_URL_CSV = "data/sam_missing_final_urls.csv"


def norm(d):
    d = (d or "").strip().lower(); d = re.sub(r"^https?://", "", d); d = re.sub(r"^www\.", "", d)
    return d.split("/")[0].strip()


def write_tab(sh, title, header, body):
    try:
        ws = sh.worksheet(title); ws.clear(); ws.resize(rows=max(len(body) + 1, 2), cols=max(len(header), 1))
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=len(body) + 5, cols=len(header) + 2)
    ws.update([header] + body, value_input_option="RAW")
    return ws


def main():
    fu = {r["domain"]: r.get("final_url", "") for r in csv.DictReader(open(FINAL_URL_CSV))}

    orows = list(csv.reader(open(ORGS_CSV)))
    ohdr, obody = orows[0], orows[1:]
    di = ohdr.index("domain")
    ohdr2 = ohdr[:di + 1] + ["final_url", "domain_mismatch"] + ohdr[di + 1:]
    obody2 = []
    for r in obody:
        d = norm(r[di]); f = fu.get(d, "")
        mism = "" if not f else str(d != f)
        obody2.append(r[:di + 1] + [f, mism] + r[di + 1:])

    lrows = list(csv.reader(open(LOCS_CSV))) if __import__("os").path.exists(LOCS_CSV) else [["domain"]]
    lhdr, lbody = lrows[0], lrows[1:]

    gc = gspread.service_account(filename="credentials/google_service_account.json")
    sh = gc.open_by_key(SHEET_ID)
    ws_o = write_tab(sh, "sam_missing_orgs", ohdr2, obody2)
    ws_l = write_tab(sh, "sam_missing_locations", lhdr, lbody)
    print(f"sam_missing_orgs: {len(obody2)} rows x {len(ohdr2)} cols")
    print(f"sam_missing_locations: {len(lbody)} rows x {len(lhdr)} cols")
    print(f"orgs tab:  https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid={ws_o.id}")
    print(f"locs tab:  https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid={ws_l.id}")


if __name__ == "__main__":
    main()
