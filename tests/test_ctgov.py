"""
CT.gov API tests. Hits the real API — requires network.
Run: pytest tests/test_ctgov.py -v
"""
import pytest
from src.ctgov import get_trials_status


@pytest.mark.asyncio
async def test_mayo_clinic_has_active_trials():
    result = await get_trials_status("Mayo Clinic")
    assert result.value == "active"
    assert result.confidence == "high"
    assert result.source_url is not None
    assert "clinicaltrials.gov" in result.source_url


@pytest.mark.asyncio
async def test_empty_name_returns_not_found():
    result = await get_trials_status("")
    assert result.confidence == "not_found"


@pytest.mark.asyncio
async def test_fake_org_returns_unknown():
    result = await get_trials_status("Zzzzz Nonexistent Research Corp Xyz")
    assert result.value == "unknown"
    assert result.confidence == "low"
