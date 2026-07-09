"""
PROTOTYPE — fully fresh business classifier (no cache), with a fail-fast liveness gate.

Per domain:
  0. GATE (cheap, fail-fast — runs BEFORE any credits/LLM):
       a. free httpx probe: DNS-dead / connection-refused / 404 / parked  -> SKIP (0 credits)
       b. Firecrawl homepage scrape (1 credit): 403 / challenge / empty / parked -> SKIP (no map, no LLM)
     Only a confirmed-live homepage with real content proceeds.
  1. Firecrawl map() -> URL inventory
  2. mine specialties from URL paths (free)
  3. LLM #1: pick <=5 informative pages
  4. Firecrawl scrape() those (clean markdown)
  5. LLM #2: classify + confidence + escalation hook
  6. escalate once if low confidence

Run:
  .venv/bin/python -m scripts.fresh_classify 3aresearch.com --verbose
"""
import os, re, sys, time, random, argparse, logging
from urllib.parse import urlparse
from typing import Literal

from dotenv import load_dotenv; load_dotenv("/Users/yoshichoi/site-agent/.env")
import httpx, anthropic, instructor
from pydantic import BaseModel, Field
from firecrawl import Firecrawl

from src.config import ANTHROPIC_API_KEY
MODEL = "claude-sonnet-5"   # classifier-only override (pipeline still uses src.config.MODEL)

logger = logging.getLogger("fresh_classify")
app = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"])
# max_retries high so the Anthropic SDK rides out 429s when many domains run concurrently
client = instructor.from_anthropic(anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=8))

def _fc_retry(fn, *a, tries=6, **kw):
    """Retry a Firecrawl call on rate-limit / transient errors with exponential backoff + jitter."""
    for i in range(tries):
        try:
            return fn(*a, **kw)
        except Exception as e:
            msg = str(e).lower()
            transient = any(s in msg for s in ("rate", "429", "timeout", "timed out", "502", "503", "504", "overloaded"))
            if i == tries - 1 or not transient:
                raise
            time.sleep(min(2 ** i + random.random(), 30))

MAX_CHARS_PER_PAGE = 12000
PRICE_IN, PRICE_OUT = 2.0/1e6, 10.0/1e6   # Sonnet 5 INTRODUCTORY ($2/$10 through 2026-08-31; then $3/$15)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
PROBE_TIMEOUT = 8

PARKED_RE = re.compile(r"hugedomains|sedoparking|sedo\.com/|parkingcrew|this domain (name )?is for sale|"
                       r"domain is for sale|buy this domain|the domain .{0,40} is for sale|"
                       r"godaddy.{0,40}for sale|account suspended|domain for sale", re.I)
# Definitive block/WAF pages — treated as blocked at ANY length:
HARD_BLOCK_RE = re.compile(r"your access to this (site|service) has been limited|wordfence|"
                           r"http response code 503|error 503|503 service temporarily|web server is down|"
                           r"cf-browser-verification|incapsula incident|request unsuccessful\. incapsula", re.I)
# Challenge-page phrases — only meaningful on a SHORT page. On a full site these appear incidentally
# (e.g. a cookie-policy line 'this cookie is set by the google reCAPTCHA service'), so length-gate them.
SOFT_BLOCK_RE = re.compile(r"just a moment\.\.\.|checking your browser before|attention required!|"
                           r"enable javascript and cookies to continue|please verify you are (a )?human|"
                           r"verify you are (a )?human|complete the captcha|are you a human\?|"
                           r"this process is automatic\. your browser will redirect", re.I)
def is_block_page(md: str) -> bool:
    low = md[:6000].lower()
    if HARD_BLOCK_RE.search(low): return True
    if len(md) < 2500 and SOFT_BLOCK_RE.search(low): return True   # short + challenge words = real wall
    return False
# Suspended / expired / dead-but-200 pages — these return real HTTP 200 with a placeholder page:
SUSPENDED_RE = re.compile(r"(this )?(site|account|domain|website) has been (suspended|archived|disabled|deactivated)|"
                          r"account suspended|this domain has expired|domain (name )?has expired|"
                          r"site (temporarily )?unavailable|under (construction|maintenance)|"
                          r"coming soon|page can.?t be found|website is no longer available", re.I)

# ---------- GATE ----------
_DNS_DEAD = re.compile(r"nodename nor servname|name or service not known|getaddrinfo|"
                       r"name does not resolve|no address associated|temporary failure in name resolution", re.I)

def probe(domain: str):
    """Free httpx probe. Skips for free ONLY on definitive DNS-dead / 404 / clear parked.
    Everything else (SSL errors, connection-refused, 403, timeouts, JS shells) -> 'ambiguous',
    deferred to the Firecrawl homepage gate (Firecrawl ignores cert errors, renders JS, rotates IPs).
    Returns: dead / not_found / parked / ok / ambiguous."""
    url = f"https://{domain}"
    try:
        r = httpx.get(url, timeout=PROBE_TIMEOUT, follow_redirects=True, headers=UA)
    except Exception as e:
        msg = str(e)
        if _DNS_DEAD.search(msg):
            return "dead", f"dns: {msg[:70]}"          # domain doesn't resolve — truly gone
        # SSL cert mismatch, connection refused, timeout, etc. — site may well be live; let Firecrawl decide
        return "ambiguous", f"{type(e).__name__}: {msg[:70]}"
    sc = r.status_code
    body = (r.text or "")[:6000].lower()
    if sc in (404, 410):
        return "not_found", sc
    if PARKED_RE.search(body):
        return "parked", sc
    if sc == 200 and len(r.text) > 500 and not is_block_page(r.text or ""):
        return "ok", sc
    if sc in (401, 403, 429) or is_block_page(r.text or ""):
        return "ambiguous", f"http_{sc}"        # bot-walled — Firecrawl may crack it
    return "ambiguous", f"http_{sc}"

# Opt-in stealth mode (FC_STEALTH=1): stealth proxy + JS wait + ignore cert errors, for retrying
# bot-walled/JS-render-miss sites. Costs more Firecrawl credits per scrape — used only on retries.
STEALTH = os.getenv("FC_STEALTH") == "1"
_SCRAPE_KW = {"formats": ["markdown"]}
if STEALTH:
    _SCRAPE_KW = {"formats": ["markdown"], "proxy": "stealth", "wait_for": 3500,
                  "skip_tls_verification": True, "timeout": 45000}

def scrape(url: str):
    """Return (markdown, status_code). statusCode<0 = error/exception.
    Retries on an EMPTY-but-successful response — Firecrawl is flaky and often returns nothing
    on one call then real content on the next (not an exception, so _fc_retry won't catch it)."""
    md, sc = "", -1
    for attempt in range(3):
        try:
            doc = _fc_retry(app.scrape, url, **_SCRAPE_KW)
            md = getattr(doc, "markdown", None) or (doc.get("markdown") if isinstance(doc, dict) else "") or ""
            meta = getattr(doc, "metadata", None) or (doc.get("metadata") if isinstance(doc, dict) else None) or {}
            sc = (meta.get("statusCode") if isinstance(meta, dict) else getattr(meta, "statusCode", None)) or 200
        except Exception as e:
            logger.warning(f"  scrape error {url}: {str(e)[:100]}")
            return "", -1
        if md.strip():
            return md, sc
        time.sleep(2 + attempt * 2)   # flaky empty → give it another shot
    return md, sc

def homepage_gate(base: str):
    """Firecrawl homepage scrape used as the live-content gate. Returns (verdict, md)."""
    md, sc = scrape(base)
    low = md[:6000].lower()
    if sc == -1 or not md or len(md) < 200:
        return "blocked", md          # firecrawl couldn't get real content
    if isinstance(sc, int) and (sc in (401, 403, 404, 410) or sc >= 500):
        return "blocked", md
    if is_block_page(md):
        return "blocked", md          # WAF / bot-wall / 503 served as a page (length-aware)
    if PARKED_RE.search(low):
        return "parked", md
    if SUSPENDED_RE.search(low):
        return "suspended", md        # 200 OK but a suspended/expired/placeholder page
    # short + no real signal = likely a stub/error page even if it slipped the patterns above
    if len(md) < 350:
        return "thin", md
    return "ok", md

# ---------- specialty mining ----------
SPMAP = {"cardiolog":"Cardiology","dermatolog":"Dermatology","neurolog":"Neurology","gastro":"Gastroenterology",
         "endocrin":"Endocrinology","rheumatolog":"Rheumatology","oncolog":"Oncology","hematolog":"Hematology",
         "nephrolog":"Nephrology","pulmonolog":"Pulmonology","urolog":"Urology","ophthalmolog":"Ophthalmology",
         "psychiatr":"Psychiatry","allerg":"Allergy/Immunology","infectious":"Infectious Disease",
         "orthop":"Orthopedics","fertilit":"OB-GYN/Fertility","pain":"Pain Management","podiatr":"Podiatry"}
def mine_specialties(urls):
    found = set()
    for u in urls:
        p = urlparse(u).path.lower()
        for k, v in SPMAP.items():
            if k in p: found.add(v)
    return sorted(found)

def norm(u):
    """Normalize for dedup: drop scheme, leading www, trailing slash."""
    return re.sub(r"^https?://(www\.)?", "", u).rstrip("/").lower()

# ---------- schemas ----------
Confidence = Literal["high","medium","low","not_found"]
BusinessType = Literal["hospital_health_system","clinic_medical_practice","clinical_research_site",
    "site_management_org","cro","clinical_trial_vendor","biotech_pharma_device",
    "government_community","nonprofit_foundation","other"]
Involve = Literal["primary","secondary","none","unclear"]

class PagePicks(BaseModel):
    urls: list[str] = Field(description="<=5 URLs most likely to reveal what the org is, whether it does research, and its specialties")

class Classification(BaseModel):
    business_type: BusinessType
    business_type_confidence: Confidence
    business_type_snippet: str = Field("", max_length=300)
    specialties: list[str] = []
    research_involvement: Involve
    research_involvement_confidence: Confidence
    research_involvement_snippet: str = Field("", max_length=300)
    need_more_info: bool
    pages_wanted: list[str] = Field(default_factory=list)

def _ask(model_resp, prompt):
    r, comp = client.chat.completions.create_with_completion(
        model=MODEL, max_tokens=1024, messages=[{"role":"user","content":prompt}], response_model=model_resp)
    return r, comp.usage.input_tokens, comp.usage.output_tokens

ROW_COLS = ["domain","status","business_type","business_type_confidence","business_type_snippet",
            "specialties","research_involvement","research_involvement_confidence","research_involvement_snippet",
            "need_more_info","url_specialties","pages_used","llm_in_tok","llm_out_tok","llm_cost_usd",
            "firecrawl_credits","detail"]
def _row(domain, status, **kw):
    r={c:"" for c in ROW_COLS}; r["domain"]=domain; r["status"]=status; r.update(kw); return r

_BT_LIST = ("hospital_health_system | clinic_medical_practice | clinical_research_site | "
            "site_management_org | cro | clinical_trial_vendor | biotech_pharma_device | "
            "government_community | nonprofit_foundation | other")
_BT_DEFS = (
    "business_type — what the org fundamentally IS (pick ONE):\n"
    "  hospital_health_system — inpatient hospital or system of them (incl. academic medical centers)\n"
    "  clinic_medical_practice — outpatient CARE practice (specialty or multispecialty); care is the product\n"
    "  clinical_research_site — an org that RUNS clinical trials at its OWN site(s). This is the DEFAULT for a "
    "dedicated research organization, whether it has 1 location or 50 (scale is captured elsewhere, not here)\n"
    "  site_management_org — ONLY if its product is managing/operating research sites FOR sponsors or other "
    "independent sites (a site-management SERVICE). Do NOT use this merely because an org has multiple locations "
    "or says it 'manages' its own research — that is clinical_research_site\n"
    "  cro — executes/manages trials end-to-end on behalf of sponsors\n"
    "  clinical_trial_vendor — sells SERVICES, CONSULTING, or TECHNOLOGY to the trials industry (patient "
    "recruitment, feasibility, regulatory/IRB consulting, CRA/monitoring staffing, EDC/CTMS/eConsent software, "
    "trial-matching or analytics/AI platforms) but does NOT itself run trials or treat patients\n"
    "  biotech_pharma_device — develops the drug/biologic/device being studied (the sponsor/product)\n"
    "  government_community — FQHC, community health center, VA/government health\n"
    "  nonprofit_foundation — disease foundation, advocacy group, nonprofit research consortium\n"
    "  other — not a healthcare/trials org, or impossible to tell\n")

def build_classify_prompt(domain, url_specs, inv, pages):
    block = "\n\n---\n\n".join(f"PAGE: {u}\n{md}" for u, md in pages.items())
    return (
        f"Classify the org at {domain} from these freshly-scraped pages.\n"
        f"Specialties detected from its URL structure (hints; merge with what you read): {url_specs}\n\n"
        f"{_BT_DEFS}"
        f"research_involvement: primary (research IS the core business) | secondary (real trials alongside a care "
        f"business) | none | unclear\n"
        f"specialties: individual canonical tags. Set need_more_info=true only if you truly can't decide.\n\n"
        f"INVENTORY:\n{inv}\n\nPAGES:\n{block}")

# JSON schema for the Batch API's structured output (instructor isn't used in the batch path)
CLASSIFY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "business_type": {"type": "string", "enum": [s.strip() for s in _BT_LIST.split("|")]},
        "business_type_confidence": {"type": "string", "enum": ["high","medium","low","not_found"]},
        "business_type_snippet": {"type": "string"},
        "specialties": {"type": "array", "items": {"type": "string"}},
        "research_involvement": {"type": "string", "enum": ["primary","secondary","none","unclear"]},
        "research_involvement_confidence": {"type": "string", "enum": ["high","medium","low","not_found"]},
        "research_involvement_snippet": {"type": "string"},
        "need_more_info": {"type": "boolean"},
    },
    "required": ["business_type","business_type_confidence","business_type_snippet","specialties",
                 "research_involvement","research_involvement_confidence","research_involvement_snippet","need_more_info"],
}

def prepare(domain, quiet=True):
    """Everything up to (but not including) the classify LLM call: gate -> map -> select -> scrape.
    Returns a state dict. status='pending' with a built 'prompt' if ready to classify; else 'skip_*'."""
    pr = (lambda *a, **k: None) if quiet else print
    credits = 0
    verdict, detail = probe(domain)
    pr(f"GATE a {domain} -> {verdict}")
    if verdict in ("dead","not_found","parked"):
        return {"domain":domain,"status":f"skip_{verdict}","detail":str(detail),"credits":0,
                "sel_in":0,"sel_out":0,"url_specialties":[],"prompt":None,"pages_used":0}
    variants = [f"https://{domain}", f"https://www.{domain}", f"http://{domain}", f"http://www.{domain}"]
    hv, home_md, base = "blocked", "", variants[0]
    for v in variants:
        vv, md = homepage_gate(v); credits += 1
        if vv == "ok":
            hv, home_md, base = "ok", md, v; break
        hv = vv
        if md.strip(): break
    if hv != "ok":
        return {"domain":domain,"status":f"skip_{hv}","detail":str(detail),"credits":credits,
                "sel_in":0,"sel_out":0,"url_specialties":[],"prompt":None,"pages_used":0}

    mp = _fc_retry(app.map, base, limit=500); credits += 1
    raw = getattr(mp,"links",None) or getattr(mp,"urls",None) or mp
    urls = sorted({(u if isinstance(u,str) else getattr(u,"url",str(u))) for u in raw})
    url_specs = mine_specialties(urls)
    inv = "\n".join(urls[:120])
    picks, pi, po = _ask(PagePicks,
        f"Full URL inventory for {domain}. Pick <=5 pages whose CONTENT best reveals (a) what kind of org this is, "
        f"(b) whether it conducts clinical research/trials, (c) its medical specialties. Prefer homepage, about, "
        f"research/trials, providers/team or services. Avoid blogs and near-duplicates.\n\nURLS:\n{inv}")
    seen = {norm(base)}; pages = {base: home_md[:MAX_CHARS_PER_PAGE]}
    inv_norm = {norm(x) for x in urls}
    picked = [u for u in picks.urls if norm(u) in inv_norm and norm(u) not in seen and not seen.add(norm(u))][:4]
    for u in picked:
        md, sc = scrape(u); credits += 1
        if md and sc not in (401,403,404) and sc > 0:
            pages[u] = md[:MAX_CHARS_PER_PAGE]
    prompt = build_classify_prompt(domain, url_specs, inv, pages)
    pr(f"  {domain}: pending, {len(pages)} pages, {credits} credits")
    return {"domain":domain,"status":"pending","detail":"","credits":credits,
            "sel_in":pi,"sel_out":po,"url_specialties":url_specs,"prompt":prompt,"pages_used":len(pages)}

def classify_domain(domain, verbose=False):
    """Live single-domain path: prepare + one classify call."""
    p = prepare(domain, quiet=not verbose)
    if p["status"] != "pending":
        return _row(domain, p["status"], detail=p["detail"], firecrawl_credits=p["credits"])
    res, i1, o1 = _ask(Classification, p["prompt"])
    cin = p["sel_in"] + i1; cout = p["sel_out"] + o1; cost = cin*PRICE_IN + cout*PRICE_OUT
    return _row(domain, "ok", business_type=res.business_type,
                business_type_confidence=res.business_type_confidence,
                business_type_snippet=res.business_type_snippet,
                specialties="; ".join(res.specialties),
                research_involvement=res.research_involvement,
                research_involvement_confidence=res.research_involvement_confidence,
                research_involvement_snippet=res.research_involvement_snippet,
                need_more_info=str(res.need_more_info), url_specialties="; ".join(p["url_specialties"]),
                pages_used=p["pages_used"], llm_in_tok=cin, llm_out_tok=cout,
                llm_cost_usd=round(cost,4), firecrawl_credits=p["credits"])

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("domains",nargs="+"); ap.add_argument("--verbose",action="store_true")
    a=ap.parse_args()
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format="%(message)s", stream=sys.stderr)
    for d in a.domains:
        classify_domain(d.strip().replace("https://","").replace("http://","").strip("/"), a.verbose)

if __name__=="__main__":
    main()
