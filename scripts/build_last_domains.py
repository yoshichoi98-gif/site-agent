"""Build a 'last domains' tab in the Batch Runs export sheet: the 3,976 domains from 'Unique Final
Domains', each enriched with all columns from the Batch Runs table where it's the Final Domain
(priority FINAL FINAL DONE > Master Table > Set Aside > Fix Needed) prefixed at_, plus all orgs columns
from Site Agent (prefixed orgs_), plus a locations_row_count."""
import re, gspread
def norm(u):
    u=(u or "").strip().lower()
    if not u: return ""
    u=re.sub(r'^https?://','',u)
    if u.startswith("www."): u=u[4:]
    return u.split('/')[0].split('?')[0].strip().rstrip('.')
gc=gspread.service_account(filename="credentials/google_service_account.json")
CLONE=gc.open_by_key("1GU1_jqFm33Q4-fPxeL-0QvqsUyZm4l5xSKEc8zyTD_4")
SAD=gc.open_by_key("13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4")

target=[v for v in CLONE.worksheet("Unique Final Domains").col_values(1)[1:] if v.strip()]
target=set(target); print(f"target domains: {len(target)}", flush=True)

# airtable side: best at_ row per domain, by table priority
PRIORITY=["FINAL FINAL DONE","Master Table","Set Aside","Fix Needed"]
at_data={}; at_cols=[]  # at_cols = union of field names in priority order
for t in PRIORITY:
    ws=CLONE.worksheet(t); v=ws.get_all_values(); hdr=v[0]
    for c in hdr:
        if c not in at_cols: at_cols.append(c)
    if "Final Domain" not in hdr: continue
    fdi=hdr.index("Final Domain")
    for r in v[1:]:
        d=norm(r[fdi]) if len(r)>fdi else ""
        if d in target and d not in at_data:   # first (highest priority) wins
            at_data[d]={"__table__":t, **{hdr[i]:(r[i] if i<len(r) else "") for i in range(len(hdr))}}
    print(f"  scanned {t}: matched so far {len(at_data)}/{len(target)}", flush=True)

# site agent side: orgs row only
ov=SAD.worksheet("orgs").get_all_values(); oh=ov[0]; odi=oh.index("domain")
orgs={}
for r in ov[1:]:
    d=norm(r[odi])
    if d in target and d not in orgs: orgs[d]={oh[i]:(r[i] if i<len(r) else "") for i in range(len(oh))}
print(f"  in orgs: {len(orgs)}", flush=True)

# assemble columns
header=["final_domain","at_source_table"]+["at_"+c for c in at_cols]+["in_orgs"]+["orgs_"+c for c in oh]
out=[header]
for d in sorted(target):
    a=at_data.get(d,{}); o=orgs.get(d)
    row=[d, a.get("__table__","")]+[a.get(c,"") for c in at_cols]+["TRUE" if o else ""]+([o.get(c,"") for c in oh] if o else [""]*len(oh))
    out.append(row)

title="last domains"
try: w=CLONE.worksheet(title); w.clear()
except gspread.WorksheetNotFound: w=CLONE.add_worksheet(title=title, rows=len(out)+10, cols=len(header))
w.resize(rows=len(out), cols=len(header))
from gspread.utils import rowcol_to_a1
import time
CH=3000
for i in range(0,len(out),CH):
    chunk=out[i:i+CH]
    w.update(values=chunk, range_name=f"A{i+1}:{rowcol_to_a1(i+len(chunk),len(header))}", value_input_option="RAW"); time.sleep(0.4)
w.freeze(rows=1)
print(f"DONE -> tab '{title}': {len(out)-1} domains x {len(header)} cols", flush=True)
