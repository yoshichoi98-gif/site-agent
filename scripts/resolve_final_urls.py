"""Resolve each domain's final URL after following redirects (HEAD, GET fallback). No LLM — just
HTTP. Records domain, final_url, redirected (input host != final host), status. Output:
data/sam_missing_final_urls.csv. Runs independent of the extraction pipeline."""
import asyncio, csv, sys
from urllib.parse import urlparse
import httpx

INPUT = "data/sam_missing_input.csv"
OUT = "data/sam_missing_final_urls.csv"
CONCURRENCY = 12
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def host(u):
    h = (urlparse(u).netloc or "").lower()
    return h[4:] if h.startswith("www.") else h


async def resolve(client, domain):
    start = f"https://{domain}"
    for method in ("HEAD", "GET"):
        try:
            r = await client.request(method, start, headers={"User-Agent": UA})
            final = str(r.url)
            redirected = host(final) != domain.lower() and host(final) != ""
            return {"domain": domain, "final_url": final, "redirected": redirected, "status": r.status_code}
        except Exception:
            if method == "GET":
                # one http:// retry for SSL/HTTPS-less sites
                try:
                    r = await client.get(f"http://{domain}", headers={"User-Agent": UA})
                    final = str(r.url)
                    return {"domain": domain, "final_url": final,
                            "redirected": host(final) != domain.lower() and host(final) != "", "status": r.status_code}
                except Exception as e:
                    return {"domain": domain, "final_url": "", "redirected": "", "status": f"error: {type(e).__name__}"}
    return {"domain": domain, "final_url": "", "redirected": "", "status": "error"}


async def main():
    domains = [r["domain"].strip() for r in csv.DictReader(open(INPUT)) if r.get("domain", "").strip()]
    sem = asyncio.Semaphore(CONCURRENCY)
    rows = []
    done = 0
    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(connect=5, read=15, write=5, pool=5),
                                 verify=False) as client:
        async def one(d):
            nonlocal done
            async with sem:
                res = await resolve(client, d)
            rows.append(res)
            done += 1
            if done % 50 == 0:
                print(f"{done}/{len(domains)}", file=sys.stderr)
        await asyncio.gather(*[one(d) for d in domains])

    order = {d: i for i, d in enumerate(domains)}
    rows.sort(key=lambda r: order.get(r["domain"], 1e9))
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["domain", "final_url", "redirected", "status"]); w.writeheader(); w.writerows(rows)
    red = sum(1 for r in rows if r["redirected"] is True)
    err = sum(1 for r in rows if str(r["status"]).startswith("error"))
    print(f"resolved {len(rows)} | redirected to different host: {red} | errors: {err} -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
