"""
PHASE 2 (Batch API, 50% off): read phase-1 state, submit all classify prompts as ONE batch,
poll to completion, parse results, merge with the skip records, write to a sheet tab + CSV.

Usage:
  .venv/bin/python -m scripts.classify_phase2_batch --state data/phase1_state.jsonl --tab business_classification_research --out data/orgs_research_classified.csv
"""
import argparse, csv, json, sys, time
from collections import Counter
from dotenv import load_dotenv; load_dotenv("/Users/yoshichoi/site-agent/.env")
import anthropic, gspread
from gspread.utils import rowcol_to_a1
from scripts.fresh_classify import CLASSIFY_SCHEMA, ROW_COLS, PRICE_IN, PRICE_OUT, MODEL

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
CRED = "credentials/google_service_account.json"

def _row(domain, status, **kw):
    r={c:"" for c in ROW_COLS}; r["domain"]=domain; r["status"]=status; r.update(kw); return r

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--state", default="data/phase1_state.jsonl")
    ap.add_argument("--tab", default="business_classification_research")
    ap.add_argument("--out", default="data/orgs_research_classified.csv")
    args=ap.parse_args()

    states=[json.loads(l) for l in open(args.state) if l.strip()]
    order=[s["domain"] for s in states]
    pend=[s for s in states if s["status"]=="pending" and s.get("prompt")]
    skips={s["domain"]: s for s in states if s["status"]!="pending"}
    print(f"{len(states)} states | {len(pend)} to classify | {len(skips)} skipped", file=sys.stderr)

    client=anthropic.Anthropic()
    # build batch requests (plain dicts; structured output via output_config.format)
    cid2state={}
    reqs=[]
    for i,s in enumerate(pend):
        cid=f"d{i}"; cid2state[cid]=s
        reqs.append({"custom_id":cid, "params":{
            "model":MODEL, "max_tokens":1024,
            "messages":[{"role":"user","content":s["prompt"]}],
            "output_config":{"format":{"type":"json_schema","schema":CLASSIFY_SCHEMA}},
        }})
    batch=client.messages.batches.create(requests=reqs)
    print(f"submitted batch {batch.id} ({len(reqs)} requests) — polling...", file=sys.stderr)

    t0=time.time()
    while True:
        b=client.messages.batches.retrieve(batch.id)
        if b.processing_status=="ended": break
        rc=b.request_counts
        print(f"  {b.processing_status} | proc={rc.processing} done={rc.succeeded} err={rc.errored} "
              f"| {(time.time()-t0)/60:.1f}min", file=sys.stderr)
        time.sleep(45)

    # collect results by custom_id
    got={}; cin=cout=0; berr=0
    for res in client.messages.batches.results(batch.id):
        if res.result.type=="succeeded":
            msg=res.result.message
            text=next((blk.text for blk in msg.content if blk.type=="text"), "")
            try: data=json.loads(text)
            except Exception: data=None
            got[res.custom_id]=(data, msg.usage)
            cin+=msg.usage.input_tokens; cout+=msg.usage.output_tokens
        else:
            berr+=1; got[res.custom_id]=(None,None)

    # build rows
    by_domain={}
    for cid,s in cid2state.items():
        data,usage=got.get(cid,(None,None))
        d=s["domain"]
        # select-call cost was live (full price); classify tokens are batch (50% off)
        sel=(s["sel_in"]*PRICE_IN + s["sel_out"]*PRICE_OUT)
        if data:
            cls=(usage.input_tokens*PRICE_IN + usage.output_tokens*PRICE_OUT)*0.5 if usage else 0
            by_domain[d]=_row(d,"ok",
                business_type=data.get("business_type",""),
                business_type_confidence=data.get("business_type_confidence",""),
                business_type_snippet=data.get("business_type_snippet",""),
                specialties="; ".join(data.get("specialties",[])),
                research_involvement=data.get("research_involvement",""),
                research_involvement_confidence=data.get("research_involvement_confidence",""),
                research_involvement_snippet=data.get("research_involvement_snippet",""),
                need_more_info=str(data.get("need_more_info","")),
                url_specialties="; ".join(s.get("url_specialties",[])),
                pages_used=s.get("pages_used",0),
                llm_in_tok=(usage.input_tokens if usage else 0), llm_out_tok=(usage.output_tokens if usage else 0),
                llm_cost_usd=round(sel+cls,4), firecrawl_credits=s["credits"])
        else:
            by_domain[d]=_row(d,"batch_error", url_specialties="; ".join(s.get("url_specialties",[])),
                              firecrawl_credits=s["credits"])
    for d,s in skips.items():
        by_domain[d]=_row(d,s["status"],detail=s.get("detail",""),firecrawl_credits=s.get("credits",0))

    ordered=[by_domain[d] for d in order if d in by_domain]
    with open(args.out,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=ROW_COLS,extrasaction="ignore"); w.writeheader(); w.writerows(ordered)

    # push to sheet
    gc=gspread.service_account(filename=CRED); sh=gc.open_by_key(SHEET_ID)
    if args.tab in [x.title for x in sh.worksheets()]: sh.del_worksheet(sh.worksheet(args.tab))
    ws=sh.add_worksheet(title=args.tab, rows=len(ordered)+10, cols=len(ROW_COLS))
    data=[ROW_COLS]+[[str(r.get(c,"")) for c in ROW_COLS] for r in ordered]
    ws.update(values=data, range_name="A1", value_input_option="USER_ENTERED")
    ws.format(f"A1:{rowcol_to_a1(1,len(ROW_COLS))}", {"textFormat":{"bold":True}})

    st=Counter(r["status"] for r in ordered); bt=Counter(r["business_type"] for r in ordered if r["status"]=="ok")
    cost=sum(float(r["llm_cost_usd"] or 0) for r in ordered)
    print(f"\nPHASE 2 DONE -> tab {args.tab!r}", file=sys.stderr)
    print(f"  batch: {len(got)-berr} ok, {berr} errored", file=sys.stderr)
    print(f"  status: {dict(st)}", file=sys.stderr)
    print(f"  business_type (ok): {dict(bt)}", file=sys.stderr)
    print(f"  LLM cost (select live + classify batched@50%): ${cost:.2f}", file=sys.stderr)

if __name__=="__main__":
    main()
