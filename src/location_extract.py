"""
Location extractor: LLM call #3 (conditional).
Given assembled page text, returns list[Location].
Only called when org_subcategory gate passes (see pipeline.py).
"""
import logging
import os
import time

import anthropic
import instructor

import src.llm_log as llm_log
from src.config import ANTHROPIC_API_KEY, LANGSMITH_ENABLED, MODEL
from src.html_extract import extract_page_sections
from src.schema import Location, Locations

logger = logging.getLogger(__name__)

_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "locations.txt")
with open(_PROMPT_PATH) as f:
    _PROMPT_TEMPLATE = f.read()


def _log_llm_call(name: str, prompt: str, count: int, duration_s: float,
                  input_tokens: int, output_tokens: int):
    llm_log.write({
        "name": name,
        "model": MODEL,
        "timestamp": time.time(),
        "duration_s": round(duration_s, 2),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "locations_found": count,
    })


def _make_location_fn():
    client = instructor.from_anthropic(
        anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    )

    def _call(prompt: str) -> tuple[Locations, object]:
        t0 = time.time()
        result, completion = client.chat.completions.create_with_completion(
            model=MODEL,
            max_tokens=16000,  # need headroom for sites with 100+ locations (each ~150 tokens of JSON); >16K triggers Anthropic streaming requirement
            messages=[{"role": "user", "content": prompt}],
            response_model=Locations,
        )
        duration = time.time() - t0
        usage = completion.usage
        if not LANGSMITH_ENABLED:
            _log_llm_call("location_extractor", prompt, len(result.locations), duration,
                          usage.input_tokens, usage.output_tokens)
        return result, usage

    if LANGSMITH_ENABLED:
        from langsmith import traceable
        return traceable(name="location_extractor", run_type="llm")(_call)
    else:
        return _call


_location_fn = _make_location_fn()


def extract_locations(
    domain: str,
    homepage_html: str,
    additional_pages: dict[str, str],
) -> tuple[Locations, object]:
    """
    Extract individual locations from the assembled page text.
    Returns (Locations, usage). On failure returns (empty Locations, dummy usage).
    """
    homepage_url = f"https://{domain}"
    pages: dict[str, str] = {}
    homepage_block = extract_page_sections(homepage_html, homepage_url)
    pages[homepage_url] = homepage_block

    for url, html in additional_pages.items():
        block = extract_page_sections(html, url)
        pages[url] = block

    pages_block = "\n\n---\n\n".join(pages.values())
    prompt = _PROMPT_TEMPLATE.format(pages=pages_block)

    logger.info(f"[{domain}] location_extractor: {len(pages)} pages, {len(prompt)} prompt chars")

    try:
        result, usage = _location_fn(prompt)
        logger.info(
            f"[{domain}] location_extractor: {len(result.locations)} location(s)"
            f"{' (CAPPED: ' + result.capped_reason + ')' if result.capped else ''} "
            f"({usage.input_tokens}in/{usage.output_tokens}out tokens)"
        )
        return result, usage
    except Exception as e:
        logger.error(f"[{domain}] location_extractor failed: {e}")

        class _ZeroUsage:
            input_tokens = 0
            output_tokens = 0

        return Locations(), _ZeroUsage()
