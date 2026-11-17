"""
Business classifier: given cached page text, label an org along two independent dimensions
(business_type + research_involvement) plus a list of specialties.

This is a SEPARATE, focused LLM call — NOT the big extractor. It exists so we can re-categorize
all orgs cheaply from cached HTML without re-running the whole pipeline. See prompts/classify.txt
for the taxonomy and rules. Modeled on src/extract.py.
"""
import logging
import os
import time
from typing import Literal

import anthropic
import instructor
from pydantic import BaseModel, Field

import src.llm_log as llm_log
from src.config import ANTHROPIC_API_KEY, LANGSMITH_ENABLED, MODEL
from src.html_extract import extract_page_sections

logger = logging.getLogger(__name__)

_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "classify.txt")
with open(_PROMPT_PATH) as f:
    _PROMPT_TEMPLATE = f.read()

Confidence = Literal["high", "medium", "low", "not_found"]

BusinessType = Literal[
    "hospital_health_system",
    "clinic_medical_practice",
    "clinical_research_site",
    "site_management_org",
    "cro",
    "biotech_pharma_device",
    "government_community",
    "nonprofit_foundation",
    "other",
]

ResearchInvolvement = Literal["primary", "secondary", "none", "unclear"]


class BusinessClassification(BaseModel):
    business_type: BusinessType
    business_type_confidence: Confidence = "not_found"
    business_type_snippet: str = Field("", max_length=300)
    # one specialty per item, canonical name where one exists; [] if none apply
    specialties: list[str] = Field(default_factory=list)
    research_involvement: ResearchInvolvement
    research_involvement_confidence: Confidence = "not_found"
    research_involvement_snippet: str = Field("", max_length=300)


# Cap text per page to bound cost. extract_page_sections front-loads the high-signal sections
# (TITLE, HEADINGS, META, CONTACT, FOOTER) before BODY, so truncating the tail is safe for a
# coarse business-type/research classification and keeps input ~2K tokens/page.
MAX_CHARS_PER_PAGE = 8000


def _build_pages_block(pages: dict[str, str]) -> str:
    return "\n\n---\n\n".join(b[:MAX_CHARS_PER_PAGE] for b in pages.values())


def _make_classifier_fn():
    client = instructor.from_anthropic(anthropic.Anthropic(api_key=ANTHROPIC_API_KEY))

    def _call(prompt: str) -> tuple[BusinessClassification, object]:
        t0 = time.time()
        result, completion = client.chat.completions.create_with_completion(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
            response_model=BusinessClassification,
        )
        duration = time.time() - t0
        usage = completion.usage
        if not LANGSMITH_ENABLED:
            llm_log.write({
                "name": "classifier",
                "model": MODEL,
                "timestamp": time.time(),
                "duration_s": round(duration, 2),
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            })
        return result, usage

    if LANGSMITH_ENABLED:
        from langsmith import traceable
        return traceable(name="classifier", run_type="llm")(_call)
    return _call


_classify_fn = _make_classifier_fn()


def classify(domain: str, homepage_html: str,
             additional_pages: dict[str, str] | None = None) -> tuple[BusinessClassification, object]:
    """Classify one org from its cached homepage (+ optional extra pages like a research page).
    Returns (BusinessClassification, usage)."""
    homepage_url = f"https://{domain}"
    pages: dict[str, str] = {homepage_url: extract_page_sections(homepage_html, homepage_url)}
    for url, html in (additional_pages or {}).items():
        if html:
            pages[url] = extract_page_sections(html, url)

    prompt = _PROMPT_TEMPLATE.format(pages=_build_pages_block(pages))
    logger.info(f"[{domain}] classifier: {len(pages)} pages, {len(prompt)} prompt chars")

    result, usage = _classify_fn(prompt)
    logger.info(
        f"[{domain}] -> {result.business_type} / {result.research_involvement} "
        f"| specialties={result.specialties} "
        f"({usage.input_tokens}in/{usage.output_tokens}out)"
    )
    return result, usage
