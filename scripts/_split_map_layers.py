"""Split the 18,476 good-to-go map rows into 10 balanced layers (<=2,000 each) keeping every domain
whole (no domain split across layers). Greedy LPT bin-packing. Writes 10 local CSVs, then creates a
NEW Google Sheet (separate from Site Agent Data) with 10 tabs and shares it with the user."""
import csv, collections, gspread
csv.field_size_limit(10_000_000)
USER_EMAIL="yoshi@alleviatehealth.care"
NLAYERS=10
rows=list(csv.DictReader(open("data/locations_map_good_to_go.csv")))
FIELDS=list(rows[0].keys())

# group by domain, sort domains by size desc
bydom=collections.defaultdict(list)
for r in rows: bydom[r["domain"].strip().lower()].append(r)
doms=sorted(bydom.items(), key=lambda kv:-len(kv[1]))
print(f"rows {len(rows)} | domains {len(doms)} | largest domain {len(doms[0][1])} ({doms[0][0]})")

# LPT: assign each domain to the currently-smallest layer
layers=[[] for _ in range(NLAYERS)]; sizes=[0]*NLAYERS
for dom,drows in doms:
    i=min(range(NLAYERS), key=lambda j:sizes[j])
    layers[i].extend(drows); sizes[i]+=len(drows)
print("layer sizes:", sizes, "| max", max(sizes), "| all <=2000:", max(sizes)<=2000)

# write local CSVs
for i,lr in enumerate(layers,1):
    with open(f"data/map_layer_{i:02d}.csv","w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(lr)
print("wrote 10 local CSVs data/map_layer_01..10.csv")

# create NEW spreadsheet (separate file) + share
gc=gspread.service_account(filename="credentials/google_service_account.json")
try:
    ss=gc.create("Site Agent — Map Layers (good_to_go)")
    for i,lr in enumerate(layers,1):
        title=f"layer_{i:02d}"
        ws=ss.add_worksheet(title=title, rows=len(lr)+1, cols=len(FIELDS))
        ws.update(values=[FIELDS]+[[r.get(c,"") for c in FIELDS] for r in lr], range_name="A1", value_input_option="RAW")
        ws.format("B1:B",{"numberFormat":{"type":"TEXT"}})  # full_address text-safe
    ss.del_worksheet(ss.worksheet("Sheet1"))
    ss.share(USER_EMAIL, perm_type="user", role="writer", notify=False)
    print("NEW SHEET URL:", ss.url)
except Exception as e:
    print("SHEET CREATE FAILED:", repr(e)[:300])
    print(">> Local CSVs are ready; service account likely lacks Drive storage to own a new file.")
