from pydantic import BaseModel, Field, model_validator
from typing import Optional, Literal

Confidence = Literal["high", "medium", "low", "not_found"]


class Evidence(BaseModel):
    value: Optional[str] = None
    source_url: Optional[str] = None
    snippet: Optional[str] = Field(None, max_length=300)
    confidence: Confidence = "not_found"


class Location(BaseModel):
    location_name: Optional[str] = None      # e.g. "HQ", "Palm Beach Branch"
    address_street: Optional[str] = None
    address_city: Optional[str] = None
    address_state: Optional[str] = None
    address_zip: Optional[str] = None
    phone: Optional[str] = None
    source_url: str                           # required — must be one of the fetched PAGE urls
    snippet: str = Field(max_length=300)      # required — verbatim substring from that page
    confidence: Confidence = "not_found"
    # computed after LLM fill — not extracted by the model
    validation_status: Literal["passed", "needs_review"] = "needs_review"

    @model_validator(mode="after")
    def _set_validation_status(self) -> "Location":
        # passed if at least one of street / city / zip is present
        if any([self.address_street, self.address_city, self.address_zip]):
            self.validation_status = "passed"
        else:
            self.validation_status = "needs_review"
        return self


class Locations(BaseModel):
    """Wrapper so instructor can enforce a list response."""
    locations: list[Location] = []
    capped: bool = False                    # True if more locations exist beyond the 20 returned
    capped_reason: Optional[str] = None     # e.g. "20-of-90+ on /locations-by-state page"


class SiteProfile(BaseModel):
    canonical_org_name: Evidence = Field(default_factory=Evidence)
    hq_phone: Evidence = Field(default_factory=Evidence)
    hq_address: Evidence = Field(default_factory=Evidence)
    location_count: Evidence = Field(default_factory=Evidence)
    research_url: Evidence = Field(default_factory=Evidence)
    # structural classification — see extract.txt for definitions
    org_subcategory: Evidence = Field(default_factory=Evidence)
    # populated by separate location extraction call; see pipeline
    locations: list[Location] = []
    locations_capped: bool = False          # True when extractor hit the 20-location cap
    locations_capped_reason: Optional[str] = None  # e.g. "20-of-90+ from /locations-by-state"
