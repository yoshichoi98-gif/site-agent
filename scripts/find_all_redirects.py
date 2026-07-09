import re, csv, gspread, requests, collections, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from gspread.utils import rowcol_to_a1
def norm(u):
    u=(u or "").strip().lower(); u=re.sub(r'^https?://','',u)
    if u.startswith("www."): u=u[4:]
    return u.split('/')[0].split('?')[0].rstrip('.')
H={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
def final_domain(dom):
    for scheme in ("https://","http://"):
        try:
            r=requests.get(scheme+dom, headers=H, timeout=20, allow_redirects=True, stream=True)
            fd=norm(r.url); r.close()
            return fd if fd else "(no-url)"
        except Exception:
            continue
    return "(dead)"
gc=gspread.service_account(filename="credentials/google_service_account.json")
SAD=gc.open_by_key("13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4")
ws=SAD.worksheet("orgs_research"); v=ws.get_all_values(); HH=v[0]; C={c:i for i,c in enumerate(HH)}
di=C.get("Domain", C.get("domain"))
doms=[ (r[di] if di<len(r) else "").strip() for r in v[1:] ]
uniq=sorted({norm(d) for d in doms if d})
print(f"resolving {len(uniq)} unique domains", flush=True)
res={}; done=0
with ThreadPoolExecutor(max_workers=50) as ex:
    futs={ex.submit(final_domain,d):d for d in uniq}
    for fut in as_completed(futs):
        res[futs[fut]]=fut.result(); done+=1
        if done%500==0: print(f"  {done}/{len(uniq)}", flush=True)
with open("data/orgs_redirects.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["domain","final_domain"])
    for d in uniq: w.writerow([d,res[d]])
# add Redirects To column
if "Redirects To" not in C:
    if ws.col_count < len(HH)+1: ws.add_cols(len(HH)+1-ws.col_count)
    C["Redirects To"]=len(HH); HH.append("Redirects To")
ci=C["Redirects To"]; col=rowcol_to_a1(1,ci+1).rstrip("1")
ws.update(values=[["Redirects To"]], range_name=f"{col}1", value_input_option="RAW")
ws.format(f"{col}1",{"textFormat":{"bold":True}})
vals=[]
for r in v[1:]:
    d=norm((r[di] if di<len(r) else "").strip())
    fd=res.get(d,"")
    vals.append([fd if (fd and fd!=d) else ""])
for i in range(0,len(vals),5000):
    ws.update(values=vals[i:i+5000], range_name=f"{col}{i+2}:{col}{i+1+len(vals[i:i+5000])}", value_input_option="RAW")
# stats
redir=[(d,res[d]) for d in uniq if res[d] and res[d]!=d and res[d] not in ("(dead)","(no-url)")]
dead=sum(1 for d in uniq if res[d]=="(dead)")
inset=set(uniq)
redir_to_inset=[(s,t) for s,t in redir if norm(t) in inset]
print(f"\nDONE. unique {len(uniq)} | redirect-elsewhere {len(redir)} | of those, target also in orgs_research: {len(redir_to_inset)} | dead {dead}", flush=True)
print("redirects whose target is ALSO an orgs_research domain (consolidation candidates):", flush=True)
for s,t in sorted(redir_to_inset): print(f"   {s:36} -> {t}", flush=True)
