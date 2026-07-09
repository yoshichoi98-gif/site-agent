"""
Parse manually-scraped Firecrawl markdown folders (~/Downloads/Manual/<uuid>/<domain>_<path>.md)
and classify each domain (business_type / specialties / research_involvement) with the same schema.
Domain is the filename token before the first '_'. Folders with the same domain are merged.
Writes data/manual_classified.csv + a business_classification_manual tab.
"""
import os, re, glob, csv, sys
from collections import defaultdict, Counter
import gspread
from gspread.utils import rowcol_to_a1
from scripts.fresh_classify import (Classification, _ask, build_classify_prompt, mine_specialties,
                                     norm, MAX_CHARS_PER_PAGE, PRICE_IN, PRICE_OUT, ROW_COLS, _row)

MANUAL = "/Users/yoshichoi/Downloads/Manual"
SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
CRED = "credentials/google_service_account.json"
PRIORITY = ["about","research","clinical","trial","stud","sponsor","provider","physician","service","specialt","team"]

def domain_of(fname): return os.path.basename(fname).split("_")[0]
def rank(path):
    p = os.path.basename(path).lower()
    for i, kw in enumerate(PRIORITY):
        if kw in p: return i
    return 50  # homepage-ish / unknown

def read_md(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    m = re.search(r'url:\s*"?([^"\n]+)', txt[:400])
    url = m.group(1).strip() if m else "https://" + os.path.basename(path)[:-3].replace("_", "/")
    return url, txt

def main():
    files_by_dom = defaultdict(list)
    for md in glob.glob(os.path.join(MANUAL, "*", "*.md")):
        files_by_dom[norm(domain_of(md))].append(md)
    print(f"{len(files_by_dom)} unique domains from manual folders\n", file=sys.stderr)

    rows = []; cost_tot = 0
    for dom, mds in sorted(files_by_dom.items()):
        mds = sorted(mds, key=rank)[:10]
        pages = {}; urls = []
        for md in mds:
            url, txt = read_md(md); urls.append(url); pages[url] = txt[:MAX_CHARS_PER_PAGE]
        url_specs = mine_specialties(urls + [os.path.basename(m) for m in mds])
        prompt = build_classify_prompt(dom, url_specs, "\n".join(urls), pages)
        try:
            res, i, o = _ask(Classification, prompt)
        except Exception as e:
            print(f"  {dom}: ERROR {e}", file=sys.stderr)
            rows.append(_row(dom, "error", detail=str(e)[:150])); continue
        cost = i*PRICE_IN + o*PRICE_OUT; cost_tot += cost
        rows.append(_row(dom, "ok", business_type=res.business_type,
            business_type_confidence=res.business_type_confidence,
            business_type_snippet=res.business_type_snippet,
            specialties="; ".join(res.specialties),
            research_involvement=res.research_involvement,
            research_involvement_confidence=res.research_involvement_confidence,
            research_involvement_snippet=res.research_involvement_snippet,
            need_more_info=str(res.need_more_info), url_specialties="; ".join(url_specs),
            pages_used=len(pages), llm_in_tok=i, llm_out_tok=o, llm_cost_usd=round(cost,4),
            firecrawl_credits=0))
        print(f"  {dom:34s} {res.business_type:24s} res={res.research_involvement:9s} spec={res.specialties}", file=sys.stderr)

    with open("data/manual_classified.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ROW_COLS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    gc = gspread.service_account(filename=CRED); sh = gc.open_by_key(SHEET_ID)
    if "business_classification_manual" in [x.title for x in sh.worksheets()]:
        sh.del_worksheet(sh.worksheet("business_classification_manual"))
    ws = sh.add_worksheet(title="business_classification_manual", rows=len(rows)+10, cols=len(ROW_COLS))
    ws.update(values=[ROW_COLS]+[[str(r.get(c,"")) for c in ROW_COLS] for r in rows], range_name="A1", value_input_option="USER_ENTERED")
    ws.format(f"A1:{rowcol_to_a1(1,len(ROW_COLS))}", {"textFormat":{"bold":True}})
    print(f"\nDONE: {len(rows)} domains -> business_classification_manual | ${cost_tot:.2f} LLM", file=sys.stderr)
    print("business_type:", dict(Counter(r['business_type'] for r in rows if r['status']=='ok')), file=sys.stderr)

if __name__ == "__main__":
    main()
