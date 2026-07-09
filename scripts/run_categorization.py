"""
Run the fresh classifier LIVE over a domain list with a thread pool, write results
incrementally to CSV, then push to a NEW tab in the Site Agent Data sheet.

Usage:
  .venv/bin/python -m scripts.run_categorization --input <domains.txt> --tab business_classification --workers 20
"""
import argparse, csv, logging, sys, threading, time, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import gspread
from gspread.utils import rowcol_to_a1

from scripts.fresh_classify import classify_domain, ROW_COLS

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
CRED = "credentials/google_service_account.json"

def clean(d):
    return d.strip().replace("https://","").replace("http://","").strip("/").lower()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="data/categorization_out.csv")
    ap.add_argument("--tab", default="business_classification")
    ap.add_argument("--workers", type=int, default=20)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stderr)

    raw = [clean(l) for l in open(args.input) if l.strip()]
    # drop header / non-domains, dedup preserving order
    seen=set(); domains=[]
    for d in raw:
        if d and d != "domain" and "." in d and " " not in d and d not in seen:
            seen.add(d); domains.append(d)
    print(f"Running {len(domains)} domains | {args.workers} workers\n", file=sys.stderr)

    f = open(args.out, "w", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=ROW_COLS, extrasaction="ignore"); w.writeheader()
    lock = threading.Lock()
    results = {}
    done = 0; t0 = time.time()

    def work(d):
        try:
            return classify_domain(d)
        except Exception as e:
            print(f"[{d}] ERROR: {e}", file=sys.stderr)
            row = {c: "" for c in ROW_COLS}; row["domain"]=d; row["status"]="error"; row["detail"]=str(e)[:200]
            return row

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, d): d for d in domains}
        for fut in as_completed(futs):
            d = futs[fut]
            row = fut.result()
            with lock:
                results[d] = row
                w.writerow(row); f.flush()
                done += 1
                el = time.time()-t0; rate = done/max(el,0.001)
                print(f"  >>> {done}/{len(domains)} | {row['status']:16s} | {d} | "
                      f"{el/60:.1f}min, ETA {(len(domains)-done)/rate/60:.1f}min", file=sys.stderr)
    f.close()

    # ---- push to a fresh tab, in original input order ----
    ordered = [results[d] for d in domains if d in results]
    gc = gspread.service_account(filename=CRED)
    sh = gc.open_by_key(SHEET_ID)
    if args.tab in [x.title for x in sh.worksheets()]:
        sh.del_worksheet(sh.worksheet(args.tab))
    ws = sh.add_worksheet(title=args.tab, rows=len(ordered)+10, cols=len(ROW_COLS))
    data = [ROW_COLS] + [[str(r.get(c,"")) for c in ROW_COLS] for r in ordered]
    ws.update(values=data, range_name="A1", value_input_option="USER_ENTERED")
    ws.format(f"A1:{rowcol_to_a1(1, len(ROW_COLS))}", {"textFormat": {"bold": True}})

    from collections import Counter
    by_status = Counter(r["status"] for r in ordered)
    by_bt = Counter(r["business_type"] for r in ordered if r["status"]=="ok")
    credits = sum(int(r["firecrawl_credits"] or 0) for r in ordered)
    cost = sum(float(r["llm_cost_usd"] or 0) for r in ordered)
    print(f"\nDONE in {(time.time()-t0)/60:.1f}min -> tab {args.tab!r}", file=sys.stderr)
    print(f"  status: {dict(by_status)}", file=sys.stderr)
    print(f"  business_type (ok): {dict(by_bt)}", file=sys.stderr)
    print(f"  TOTAL: ~{credits} firecrawl credits, ${cost:.2f} LLM", file=sys.stderr)

if __name__ == "__main__":
    main()
