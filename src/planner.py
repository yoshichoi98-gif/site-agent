"""
Planner: given homepage HTML, pick up to 5 internal URLs worth crawling.
LLM call #1 in the pipeline.
"""
import logging
import os
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

import anthropic
import instructor
import trafilatura
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

import src.llm_log as llm_log
from src.config import ANTHROPIC_API_KEY, LANGSMITH_ENABLED, MODEL

logger = logging.getLogger(__name__)

# Load prompt once at import time
_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "planner.txt")
with open(_PROMPT_PATH) as f:
    _PROMPT_TEMPLATE = f.read()


class PlannedPage(BaseModel):
    url: str
    reason: str = Field(max_length=150)
    priority: int = Field(ge=1, le=5)


class CrawlPlan(BaseModel):
    pages: list[PlannedPage] = Field(max_length=7)


_CONTACT_PATH_RE = re.compile(r'contact|get-in-touch', re.IGNORECASE)
_CONTACT_TEXT_RE = re.compile(r'contact', re.IGNORECASE)


def _extract_internal_links(html: str, domain: str) -> list[str]:
    """Pull all <a href> links from raw HTML, keep only internal ones.

    Exception: include up to 1 cross-domain link whose path or anchor text
    matches a contact pattern — catches sites where /contact-us redirects to
    a sister domain (e.g. maryland-plastic-surgery.com → mdcosmetic.com).
    """
    soup = BeautifulSoup(html, "html.parser")
    base_url = f"https://{domain}/"
    links = []
    seen = set()
    cross_domain_contact_added = 0

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        href = urljoin(base_url, href)
        parsed = urlparse(href)
        netloc = parsed.netloc
        is_same_domain = netloc == domain or netloc.endswith("." + domain)

        if not is_same_domain:
            # Allow at most 1 cross-domain contact link
            if cross_domain_contact_added < 1:
                anchor_text = tag.get_text(strip=True)
                if (_CONTACT_PATH_RE.search(parsed.path) or
                        _CONTACT_TEXT_RE.search(anchor_text)):
                    if href not in seen:
                        seen.add(href)
                        links.append(href)
                        cross_domain_contact_added += 1
            continue

        if href in seen:
            continue
        seen.add(href)
        links.append(href)

    return links[:100]  # cap to avoid bloating prompt


def _log_llm_call(name: str, input_text: str, output_text: str, model: str,
                  input_tokens: int, output_tokens: int):
    """Write LLM call to local JSONL log when LangSmith is not enabled."""
    import time
    llm_log.write({
        "name": name,
        "model": model,
        "timestamp": time.time(),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "output_preview": output_text[:200],
    })


def _make_planner_fn():
    client = instructor.from_anthropic(
        anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    )

    def _call(homepage_text: str, links: list[str]) -> tuple[CrawlPlan, object]:
        links_str = "\n".join(links) if links else "(no internal links found)"
        prompt = _PROMPT_TEMPLATE.format(
            homepage_text=homepage_text[:4000],  # keep prompt manageable
            links=links_str,
        )
        result, completion = client.chat.completions.create_with_completion(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
            response_model=CrawlPlan,
        )
        usage = completion.usage
        if not LANGSMITH_ENABLED:
            _log_llm_call("planner", prompt, str(result), MODEL,
                          usage.input_tokens, usage.output_tokens)
        return result, usage

    if LANGSMITH_ENABLED:
        from langsmith import traceable
        return traceable(name="planner", run_type="llm")(_call)
    else:
        return _call


_plan_crawl_fn = _make_planner_fn()


def plan_crawl(homepage_html: str, domain: str) -> tuple[CrawlPlan, object]:
    """
    Given raw homepage HTML and the domain, return up to 5 URLs to crawl next.
    Returns (CrawlPlan, usage) where usage.input_tokens / usage.output_tokens are actual counts.
    """
    links = _extract_internal_links(homepage_html, domain)
    homepage_text = trafilatura.extract(homepage_html) or ""

    logger.info(f"[{domain}] planner: {len(links)} internal links, {len(homepage_text)} chars text")

    if not homepage_text and not links:
        logger.warning(f"[{domain}] planner: no extractable content")

        class _ZeroUsage:
            input_tokens = 0
            output_tokens = 0

        return CrawlPlan(pages=[]), _ZeroUsage()

    plan, usage = _plan_crawl_fn(homepage_text, links)

    # Enforce: only return URLs that were in the extracted link list
    valid_links = set(links)
    filtered = [p for p in plan.pages if p.url in valid_links]
    if len(filtered) < len(plan.pages):
        dropped = len(plan.pages) - len(filtered)
        logger.warning(f"[{domain}] planner: dropped {dropped} hallucinated URL(s)")

    plan.pages = sorted(filtered, key=lambda p: p.priority)
    logger.info(
        f"[{domain}] planner: selected {len(plan.pages)} pages "
        f"({usage.input_tokens}in/{usage.output_tokens}out tokens)"
    )
    return plan, usage
