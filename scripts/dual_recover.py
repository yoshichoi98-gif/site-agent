"""
DUAL-FETCH resolver for the stubborn remainder. For each domain:
  1. try the PROJECT fetcher (httpx/curl_cffi/Playwright) — recover_phase1.prepare_one
  2. if that skips (403/blocked/thin), fall back to FIRECRAWL — fresh_classify.prepare
  3. if neither returns real content -> skip. NO classification is produced without real pages
     (no hallucination).
State JSONL is the phase-1 schema, so classify_phase2_batch consumes it.

Usage:
  .venv/bin/python -m scripts.dual_recover --input data/unresolved.txt --state data/dual_state.jsonl --concurrency 6
"""
import argparse, asyncio, json, sys, time, logging
from collections import Counter
from scripts.recover_phase1 import prepare_one as project_prepare   # async, project fetcher (fresh)
import scripts.fresh_classify as fc                                 # firecrawl path

logger = logging.getLogger("dual")

async def dual(domain, sem):
    # 1) project fetcher
    s = await project_prepare(domain, sem)
    if s["status"] == "pending":
        s["detail"] = "method=project"; return s
    # 2) firecrawl fallback (sync -> executor); retry-on-empty handled inside fresh_classify
    loop = asyncio.get_event_loop()
    async with sem:
        try:
            s2 = await loop.run_in_executor(None, lambda: fc.prepare(domain, quiet=True))
        except Exception as e:
            s2 = None
            logger.warning(f"[{domain}] firecrawl fallback error: {e}")
    if s2 and s2["status"] == "pending":
        s2["detail"] = "method=firecrawl"; return s2
    # 3) neither worked -> return the project skip (unresolved, NOT classified)
    s["detail"] = f"project={s['status']}; firecrawl={(s2 or {}).get('status','err')}"
    return s

async def run(domains, state_path, concurrency):
    sem = asyncio.Semaphore(concurrency)
    f = open(state_path, "w", encoding="utf-8")
    ct = Counter(); done = 0; t0 = time.time()
    tasks = [asyncio.create_task(dual(d, sem)) for d in domains]
    for fut in asyncio.as_completed(tasks):
        s = await fut
        f.write(json.dumps(s) + "\n"); f.flush()
        done += 1; ct[s["status"]] += 1
        if done % 10 == 0 or done == len(domains):
            print(f"  {done}/{len(domains)} | {(time.time()-t0)/60:.1f}min | {dict(ct)}", file=sys.stderr)
    f.close()
    pend = ct.get("pending", 0)
    print(f"\nDUAL RECOVER DONE in {(time.time()-t0)/60:.1f}min | {dict(ct)} | {pend} resolved", file=sys.stderr)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--state", default="data/dual_state.jsonl")
    ap.add_argument("--concurrency", type=int, default=6)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stderr)
    doms = [l.strip().replace("https://","").replace("http://","").strip("/").lower()
            for l in open(args.input) if l.strip() and l.strip().lower() != "domain"]
    print(f"DUAL RECOVER: {len(doms)} domains (project -> firecrawl fallback), concurrency {args.concurrency}\n", file=sys.stderr)
    asyncio.run(run(doms, args.state, args.concurrency))

if __name__ == "__main__":
    main()
