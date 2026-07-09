"""Step 1 of the RCA rollup: resolve member-practice external domains.
Scrape retinaconsultantsofamerica.com/about-rca/practices -> ~37 detail pages -> each practice's
external website domain. Writes data/rca_practices.csv (practice_name, practice_domain) and
data/rca_practice_domains.csv (single 'domain' column for smart_location_recount)."""
import os, csv, re, urllib.parse
from dotenv import load_dotenv; load_dotenv()
from concurrent.futures import ThreadPoolExecutor, as_completed
from firecrawl import Firecrawl

fc = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"], timeout=90)
INDEX = "https://www.retinaconsultantsofamerica.com/about-rca/practices"
SOCIAL = ("facebook", "linkedin", "twitter", "instagram", "youtube", "google.", "privacy",
          "tiktok", "doximity", "vimeo", "apple.", "maps.", "goo.gl")


def norm(host):
    h = (host or "").lower().strip()
    return h[4:] if h.startswith("www.") else h


def detail_links():
    r = fc.scrape(INDEX, formats=["links"])
    links = sorted(set(r.links or []))
    return [l for l in links if re.search(r"/about-rca/practices/[a-z0-9-]+$", l)]


def external_domain(detail_url):
    try:
        r = fc.scrape(detail_url, formats=["links"])
    except Exception as e:
        return detail_url, "", f"err:{type(e).__name__}"
    hosts = []
    for l in (r.links or []):
        if not l.startswith("http"):
            continue
        h = urllib.parse.urlparse(l).netloc
        if "retinaconsultantsofamerica.com" in h:
            continue
        if any(s in l.lower() for s in SOCIAL):
            continue
        hosts.append(norm(h))
    # most common external host = the practice site
    name = detail_url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
    host = ""
    if hosts:
        host = max(set(hosts), key=hosts.count)
    return detail_url, host, name


def main():
    details = detail_links()
    print(f"detail pages: {len(details)}")
    rows = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(external_domain, d): d for d in details}
        for fut in as_completed(futs):
            url, host, name = fut.result()
            rows.append((name, host, url))
    rows.sort(key=lambda r: r[0])
    with open("data/rca_practices.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["practice_name", "practice_domain", "rca_detail_url"]); w.writerows(rows)
    doms = sorted({h for _, h, _ in rows if h})
    with open("data/rca_practice_domains.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["domain"]); [w.writerow([d]) for d in doms]
    print(f"resolved {len(rows)} practices | {len(doms)} unique domains | missing domain: {sum(1 for _,h,_ in rows if not h)}")
    for n, h, _ in rows:
        print(f"  {n[:38]:38} -> {h or '(none)'}")


if __name__ == "__main__":
    main()
