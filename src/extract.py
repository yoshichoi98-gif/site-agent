"""
Extractor: given raw HTML from up to 5 pages, produce a validated SiteProfile.
LLM call #2 in the pipeline.
"""
import logging
import os
import time

import anthropic
import instructor

import src.llm_log as llm_log
from src.config import ANTHROPIC_API_KEY, LANGSMITH_ENABLED, MODEL
from src.html_extract import extract_page_sections
from src.schema import SiteProfile

logger = logging.getLogger(__name__)

_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "extract.txt")
with open(_PROMPT_PATH) as f:
    _PROMPT_TEMPLATE = f.read()


def _build_pages_block(pages: dict[str, str]) -> str:
    """Join pre-formatted page section blocks with a separator."""
    return "\n\n---\n\n".join(pages.values())


def _log_llm_call(name: str, prompt: str, result: SiteProfile, duration_s: float,
                  input_tokens: int, output_tokens: int):
    llm_log.write({
        "name": name,
        "model": MODEL,
        "timestamp": time.time(),
        "duration_s": round(duration_s, 2),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "output_fields_found": sum(
            1 for f in SiteProfile.model_fields
            if f not in {"locations", "locations_capped", "locations_capped_reason"}
            and getattr(result, f).confidence != "not_found"
        ),
    })


def _make_extractor_fn():
    client = instructor.from_anthropic(
        anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    )

    def _call(prompt: str) -> tuple[SiteProfile, object]:
        t0 = time.time()
        result, completion = client.chat.completions.create_with_completion(
            model=MODEL,
            max_tokens=16000,  # bumped from 4096 — was hitting truncation retries
            messages=[{"role": "user", "content": prompt}],
            response_model=SiteProfile,
        )
        duration = time.time() - t0
        usage = completion.usage
        if not LANGSMITH_ENABLED:
            _log_llm_call("extractor", prompt, result, duration,
                          usage.input_tokens, usage.output_tokens)
        return result, usage

    if LANGSMITH_ENABLED:
        from langsmith import traceable
        return traceable(name="extractor", run_type="llm")(_call)
    else:
        return _call


_extract_fn = _make_extractor_fn()


def extract(domain: str, homepage_html: str, additional_pages: dict[str, str]) -> tuple[SiteProfile, object]:
    """
    Produce a SiteProfile from the homepage + any additional fetched pages.
    Returns (SiteProfile, usage) where usage.input_tokens / usage.output_tokens are actual counts.
    """
    homepage_url = f"https://{domain}"
    pages: dict[str, str] = {}

    homepage_block = extract_page_sections(homepage_html, homepage_url)
    pages[homepage_url] = homepage_block

    for url, html in additional_pages.items():
        block = extract_page_sections(html, url)
        pages[url] = block

    pages_block = _build_pages_block(pages)
    prompt = _PROMPT_TEMPLATE.format(pages=pages_block)

    logger.info(f"[{domain}] extractor: {len(pages)} pages, {len(prompt)} prompt chars")

    profile, usage = _extract_fn(prompt)
    _non_evidence = {"locations", "locations_capped", "locations_capped_reason"}
    evidence_fields = [f for f in SiteProfile.model_fields if f not in _non_evidence]
    fields_found = sum(
        1 for f in evidence_fields
        if getattr(profile, f).confidence != "not_found"
    )
    logger.info(
        f"[{domain}] extractor: {fields_found}/{len(evidence_fields)} fields found "
        f"({usage.input_tokens}in/{usage.output_tokens}out tokens)"
    )
    return profile, usage
