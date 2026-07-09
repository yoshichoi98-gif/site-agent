"""Export every table in the 'Batch Runs' Airtable base into tabs of a Google Sheet.
Pulls all records via the Airtable REST API (paginated, server-side), flattens field values, and writes
one tab per table. Reads AIRTABLE_PAT from .env."""
import os, sys, time, requests, gspread
from dotenv import load_dotenv
load_dotenv("/Users/yoshichoi/site-agent/.env")
PAT=os.environ["AIRTABLE_PAT"]
BASE="appSs0fmxPOhYYNT5"
SHEET="1GU1_jqFm33Q4-fPxeL-0QvqsUyZm4l5xSKEc8zyTD_4"
H={"Authorization":f"Bearer {PAT}"}

def flatten(val):
    if val is None: return ""
    if isinstance(val, bool): return "TRUE" if val else ""
    if isinstance(val, list):
        parts=[]
        for x in val:
            if isinstance(x, dict): parts.append(x.get("url") or x.get("name") or x.get("email") or str(x))
            else: parts.append(str(x))
        return ", ".join(parts)
    if isinstance(val, dict): return val.get("name") or val.get("url") or str(val)
    return str(val)

# 1. schema: ordered field names per table
tables=requests.get(f"https://api.airtable.com/v0/meta/bases/{BASE}/tables", headers=H, timeout=30).json()["tables"]
print(f"tables: {len(tables)}", flush=True)

gc=gspread.service_account(filename="credentials/google_service_account.json")
ss=gc.open_by_key(SHEET)
existing={w.title:w for w in ss.worksheets()}

for tb in tables:
    name=tb["name"]; tid=tb["id"]
    fields=[f["name"] for f in tb["fields"]]
    # 2. pull all records (paginate)
    recs=[]; offset=None
    while True:
        params={"pageSize":100}
        if offset: params["offset"]=offset
        r=requests.get(f"https://api.airtable.com/v0/{BASE}/{tid}", headers=H, params=params, timeout=60)
        if r.status_code==429: time.sleep(2); continue
        j=r.json(); recs.extend(j.get("records",[])); offset=j.get("offset")
        if not offset: break
    print(f"  {name}: {len(recs)} records x {len(fields)} fields", flush=True)
    # 3. build matrix
    header=["airtable_record_id"]+fields
    rows=[header]
    for rec in recs:
        f=rec.get("fields",{})
        rows.append([rec["id"]]+[flatten(f.get(fn)) for fn in fields])
    # 4. write to a tab
    title=name[:99]
    if title in existing:
        ws=existing[title]; ws.clear()
    else:
        ws=ss.add_worksheet(title=title, rows=len(rows)+10, cols=len(header))
    ws.resize(rows=len(rows), cols=len(header))
    # chunked update to stay under request size limits
    from gspread.utils import rowcol_to_a1
    CH=4000
    for i in range(0, len(rows), CH):
        chunk=rows[i:i+CH]
        rng=f"A{i+1}:{rowcol_to_a1(i+len(chunk), len(header))}"
        ws.update(values=chunk, range_name=rng, value_input_option="RAW")
        time.sleep(0.5)
    ws.freeze(rows=1)
    print(f"    -> wrote tab '{title}' ({len(rows)-1} data rows)", flush=True)

# delete default empty Sheet1 if it's not one of our tables
tnames={tb["name"][:99] for tb in tables}
for w in ss.worksheets():
    if w.title=="Sheet1" and "Sheet1" not in tnames:
        ss.del_worksheet(w); print("deleted default Sheet1", flush=True); break
print("DONE ->", ss.url, flush=True)
