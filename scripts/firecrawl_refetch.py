"""Re-fetch blocked/timeout domains via Firecrawl (strong anti-bot/JS), then run the SAME org
extraction the main pipeline uses (src.extract.extract). Org-only mode skips location enumeration.
Cost-capped, fail-soft, resumable (appends per row; reruns skip already-recovered domains).

Usage:
  python -m scripts.firecrawl_refetch --input data/output_orgs.csv --out data/output_orgs_fc.csv \
      --org-only --concurrency 50 --max-cost 150 [--limit 50]
"""
import os, sys, csv, time, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv; load_dotenv()
from firecrawl import Firecrawl

from src.extract import extract
from src.location_extract import extract_locations
from src.planner import plan_crawl
from src.fetch import _content_quality
from src.pipeline import (RESEARCH_TARGET_SUBCATEGORIES, _profile_to_org_row, locations_to_rows,
                          add_cost, get_run_cost, reset_run_cost)
from src.schema import SiteProfile

RETRY_STATUSES = {"blocked", "timeout"}
MAX_PLANNED = 5
LOC_COLS = ["domain", "location_name", "address_street", "address_city", "address_state",
            "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status"]
fc = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"], timeout=90)

# set from args
_MAX_COST = float("inf")
_ORG_ONLY = False
_WAIT = 2500


def fc_html(url):
    """Firecrawl scrape -> raw HTML; one retry to absorb edge rate-limits at high concurrency."""
    for attempt in (1, 2):
        try:
            r = fc.scrape(url, formats=["rawHtml"], wait_for=_WAIT)
            return getattr(r, "raw_html", None) or getattr(r, "rawHtml", "") or ""
        except Exception:
            if attempt == 1:
                time.sleep(2)
            else:
                return ""
    return ""


def process(domain):
    t0 = time.time()
    if get_run_cost() >= _MAX_COST:
        return (_profile_to_org_row(domain, SiteProfile(), 0, "skipped", "cost_cap_reached"), [])
    html = fc_html(f"https://{domain}")
    if not html:
        return (_profile_to_org_row(domain, SiteProfile(), time.time() - t0, "firecrawl_failed", "firecrawl_no_html"), [])
    additional = {}
    try:
        plan, usage = plan_crawl(html, domain)
        add_cost(usage.input_tokens, usage.output_tokens)
        for p in (plan.pages[:MAX_PLANNED] if plan and plan.pages else []):
            h = fc_html(p.url)
            if h:
                additional[p.url] = h
    except Exception:
        pass
    try:
        profile, usage = extract(domain, html, additional)
        add_cost(usage.input_tokens, usage.output_tokens)
    except Exception as e:
        return (_profile_to_org_row(domain, SiteProfile(), time.time() - t0, "firecrawl", f"extract_error:{type(e).__name__}"), [])
    profile.locations = []
    loc_rows = []
    if not _ORG_ONLY:
        sub = (profile.org_subcategory.value or "").lower()
        if sub in RESEARCH_TARGET_SUBCATEGORIES:
            try:
                loc_result, usage = extract_locations(domain, html, additional)
                profile.locations = loc_result.locations
                profile.locations_capped = loc_result.capped
                profile.locations_capped_reason = loc_result.capped_reason
                add_cost(usage.input_tokens, usage.output_tokens)
            except Exception:
                pass
        loc_rows = locations_to_rows(domain, profile.locations)
    row = _profile_to_org_row(domain, profile, time.time() - t0, "firecrawl", content_quality=_content_quality(html))
    return (row, loc_rows)


def main(a):
    global _MAX_COST, _ORG_ONLY, _WAIT
    _MAX_COST, _ORG_ONLY, _WAIT = a.max_cost, a.org_only, a.wait_for
    reset_run_cost()

    rows = list(csv.DictReader(open(a.input)))
    # output columns = the FULL org schema (from _profile_to_org_row), NOT the input file's columns
    # (deriving from input dropped all extracted org fields when given a minimal input). Fall back to
    # input columns only if the schema probe fails.
    try:
        org_cols = list(_profile_to_org_row("example.com", SiteProfile(), 0.0, "sample").keys())
    except Exception:
        org_cols = list(rows[0].keys())
    targets = [r["domain"] for r in rows if (r.get("fetch_status") or "").strip() in RETRY_STATUSES]
    done_domains = set()
    if os.path.exists(a.out):
        done_domains = {r["domain"] for r in csv.DictReader(open(a.out))}
    todo = [d for d in targets if d not in done_domains]
    if a.limit:
        todo = todo[:a.limit]
    print(f"targets {len(targets)} | already done {len(done_domains)} | to run {len(todo)} | "
          f"org_only={_ORG_ONLY} concurrency={a.concurrency} max_cost=${_MAX_COST}", file=sys.stderr)

    new_file = not os.path.exists(a.out)
    fout = open(a.out, "a", newline="")
    w = csv.DictWriter(fout, fieldnames=org_cols, extrasaction="ignore")
    if new_file:
        w.writeheader()
    loc_out, done = [], 0
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        futs = {ex.submit(process, d): d for d in todo}
        for fut in as_completed(futs):
            try:
                org_row, loc_rows = fut.result()
            except Exception as e:
                d = futs[fut]
                org_row = _profile_to_org_row(d, SiteProfile(), 0, "firecrawl_failed", f"crash:{type(e).__name__}")
                loc_rows = []
            if org_row.get("fetch_status") == "skipped" and org_row.get("error") == "cost_cap_reached":
                continue  # don't persist cost-capped skips — keep them retryable on resume
            w.writerow(org_row); fout.flush()
            loc_out.extend(loc_rows)
            done += 1
            if done % 10 == 0:
                print(f"{done}/{len(todo)}  cost=${get_run_cost():.2f}", file=sys.stderr)
    fout.close()
    if loc_out and not _ORG_ONLY and a.out_locs:
        with open(a.out_locs, "w", newline="") as f:
            lw = csv.DictWriter(f, fieldnames=LOC_COLS, extrasaction="ignore"); lw.writeheader(); lw.writerows(loc_out)

    allrows = list(csv.DictReader(open(a.out)))
    rec = sum(1 for r in allrows if r["fetch_status"] == "firecrawl" and (r.get("canonical_org_name__value") or r.get("org_subcategory__value")))
    fail = sum(1 for r in allrows if r["fetch_status"] == "firecrawl_failed")
    print(f"DONE. {len(allrows)} in {a.out} | recovered(got data): {rec} | failed(no html): {fail} | "
          f"LLM cost ${get_run_cost():.2f}", file=sys.stderr)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="data/output_orgs.csv")
    p.add_argument("--out", default="data/output_orgs_fc.csv")
    p.add_argument("--out-locs", default="data/output_locations_orgs_recovered.csv")
    p.add_argument("--concurrency", type=int, default=50)
    p.add_argument("--max-cost", type=float, default=float("inf"))
    p.add_argument("--wait-for", type=int, default=2500)
    p.add_argument("--org-only", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    main(p.parse_args())
