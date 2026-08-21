import os
import re
import pytest
import pytest_asyncio
from agentkernel.test import Test
import database

pytestmark = pytest.mark.asyncio(loop_scope="session")

@pytest.fixture(scope="session", autouse=True)
def check_gemini_key():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY not set in environment. Skipping live Gemini integration test.")

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("app.py")
    await test.start()
    try:
        yield test
    finally:
        await test.stop()

async def test_live_gemini_coordinator_single_turn_and_persistence(test_client):
    """Controlled single live Gemini agent integration test validating end-to-end coordination and persistence."""
    response = await test_client.send(
        "I am donor d1. I have 25 lunch packets in Colombo available until 6 PM. Please create a donation for this."
    )
    
    # 1. Assert response contains required confirmation substrings
    lower_resp = response.lower()
    assert "created" in lower_resp or "donation" in lower_resp, f"Expected 'created' or 'donation' in response: {response}"
    assert "colombo" in lower_resp, f"Expected 'colombo' in response: {response}"
    
    # 2. Assert response contains donation ID beginning with 'don-'
    match = re.search(r"don-[a-zA-Z0-9_-]+", response)
    assert match is not None, f"Expected donation ID starting with 'don-' in response: {response}"
    donation_id = match.group(0)
    
    # 3. Verify that the donation was persisted in SQLite
    record = database.get_donation_record(donation_id)
    assert record is not None, f"Donation {donation_id} was not found in SQLite database"
    
    # 4. Verify resulting donation status is in valid progression statuses
    assert record["status"] in ["AVAILABLE", "MATCHED", "PICKUP_ASSIGNED"], f"Expected valid active status, got {record['status']}"

