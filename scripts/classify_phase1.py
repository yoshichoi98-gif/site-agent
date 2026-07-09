"""
PHASE 1 (live, concurrent): gate -> map -> select -> scrape for each domain, and write the
assembled classify prompt (or a skip record) to a JSONL state file. No classify call here —
that happens in phase 2 via the Batch API (50% off).

Usage:
  .venv/bin/python -m scripts.classify_phase1 --input <domains.txt> --state data/phase1_state.jsonl --workers 20
"""
import argparse, json, sys, threading, time, logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from scripts.fresh_classify import prepare

def clean(d):
    return d.strip().replace("https://","").replace("http://","").strip("/").lower()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--state", default="data/phase1_state.jsonl")
    ap.add_argument("--workers", type=int, default=20)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stderr)

    raw = [clean(l) for l in open(args.input) if l.strip()]
    seen=set(); domains=[]
    for d in raw:
        if d and d != "domain" and "." in d and " " not in d and d not in seen:
            seen.add(d); domains.append(d)
    print(f"PHASE 1: {len(domains)} domains, {args.workers} workers\n", file=sys.stderr)

    f = open(args.state, "w", encoding="utf-8")
    lock = threading.Lock(); done=0; t0=time.time()
    from collections import Counter
    status_ct = Counter()

    def work(d):
        try:
            return prepare(d, quiet=True)
        except Exception as e:
            return {"domain":d,"status":"error","detail":str(e)[:200],"credits":0,
                    "sel_in":0,"sel_out":0,"url_specialties":[],"prompt":None,"pages_used":0}

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs={ex.submit(work,d):d for d in domains}
        for fut in as_completed(futs):
            s=fut.result()
            with lock:
                f.write(json.dumps(s)+"\n"); f.flush()
                done+=1; status_ct[s["status"]]+=1
                el=time.time()-t0; rate=done/max(el,0.001)
                print(f"  {done}/{len(domains)} | {s['status']:16s} | {s['domain']} | "
                      f"{el/60:.1f}min ETA {(len(domains)-done)/rate/60:.1f}min", file=sys.stderr)
    f.close()

    pend=status_ct.get("pending",0)
    # phase-1 LLM cost = the live 'select' calls only (small); classify happens in phase 2
    print(f"\nPHASE 1 DONE in {(time.time()-t0)/60:.1f}min", file=sys.stderr)
    print(f"  status: {dict(status_ct)}", file=sys.stderr)
    print(f"  {pend} domains ready to classify -> run phase 2 batch", file=sys.stderr)

if __name__ == "__main__":
    main()
