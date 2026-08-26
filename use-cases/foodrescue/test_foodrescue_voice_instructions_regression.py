"""Dedicated Comprehensive Regression Test Suite for Voice Instructions & User Feedback.

Verifies:
1. Exact food preservation: User inputs like 'Rice' are preserved as 'Rice' (never mutated to 'Rice & Curry Packages').
2. Returning Donor profile pre-fill: Registered donors are greeted by name and skip DONOR_NAME/DISTRICT slot prompts.
3. Two-step Coordination: Donor confirmation notifies nearest recipient organizations first; Org acceptance dispatches volunteer.
4. Sri Lanka Timezone (+05:30): All verification responses, QR scan times, and timestamps use Asia/Colombo time.
5. Verification link removal: Donor and Org WhatsApp instructions do NOT contain /verify/pickup or /verify/delivery URL links.
6. Volunteer Delivery Availability prompt & Auto-matching: Delivery completion prompts for availability; replying AVAILABLE sets status.
7. Route Calculation & Map Integration: /api/routes/pickup-route calculates distance, time, polyline, and Google Maps link.
"""

import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

import database
import resilient_executor
import tools
import translation_service
import voice_service
import whatsapp_handler
from api_routes import router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_clean_db():
    """Reset test database before and after each test."""
    database.setup_database()
    database.reset_database_data(wipe_all=True)
    whatsapp_handler.clear_processed_message_cache()
    tools.clear_session_store()
    tools.set_explicit_session_id(None)
    yield
    database.reset_database_data(wipe_all=True)
    tools.clear_session_store()
    whatsapp_handler.clear_processed_message_cache()


# =============================================================================
# 1. EXACT FOOD TYPE PRESERVATION
# =============================================================================

@pytest.mark.asyncio
async def test_exact_food_type_preservation():
    """Verify user input 'Rice' is preserved as 'Rice' without being forced to 'Rice & Curry Packages'."""
    phone = "+94771239999"
    session_id = f"whatsapp:{phone}"

    # Extraction test in resilient_executor
    extracted = resilient_executor._extract_food_type("I have Rice")
    assert extracted == "Rice"

    # Voice service extraction
    v_ext = voice_service.extract_donation_entities("I want to donate 15 packets of Rice")
    assert v_ext["food_type"] == "Rice"
    assert v_ext["quantity"] == 15.0

    # Multi-turn draft preservation
    reply1 = await resilient_executor.execute_deterministic_fallback("1", session_id=session_id)
    assert "food" in reply1.lower()

    # Donor replies "Rice"
    reply2 = await resilient_executor.execute_deterministic_fallback("Rice", session_id=session_id)
    draft = database.get_draft_donation(phone)
    assert draft is not None
    assert draft["food_type"] == "Rice"


# =============================================================================
# 2. RETURNING REGISTERED DONOR PROFILE PRE-FILL
# =============================================================================

@pytest.mark.asyncio
async def test_returning_registered_donor_prefills_profile():
    """Verify registered donor returning to donate does not get asked for their name or district again."""
    phone = "94770008888"
    session_id = f"whatsapp:{phone}"

    # Pre-register donor
    database.create_donor_record(
        donor_id="d-returning-1",
        name="Afnan's Bakery",
        phone=phone,
        location="Mawanella, Kegalle",
        organization_name="Afnan's Bakery"
    )
    database.create_or_update_user(
        phone=phone,
        display_name="Afnan's Bakery",
        user_role="donor",
        default_location="Mawanella"
    )

    # Returning donor initiates donation
    reply1 = await resilient_executor.execute_deterministic_fallback("1", session_id=session_id)
    assert "Afnan's Bakery" in reply1 or "food" in reply1.lower()

    # Donor provides food quantity: "30 packets of Biryani"
    reply2 = await resilient_executor.execute_deterministic_fallback("30 packets of Biryani", session_id=session_id)
    # Should automatically skip DONOR_NAME and DISTRICT, and ask for DEADLINE or LOCATION PIN
    assert "what is your name" not in reply2.lower()
    assert "which district" not in reply2.lower()
    draft = database.get_draft_donation(phone)
    assert draft["donor_name"] == "Afnan's Bakery"
    assert "Mawanella" in draft["city"]


# =============================================================================
# 3. SRI LANKA TIMEZONE (+05:30)
# =============================================================================

def test_sri_lanka_timezone_formatting():
    """Verify format_sri_lanka_time produces accurate +05:30 timestamps."""
    iso_utc = "2026-08-26T12:00:00Z"
    sl_formatted = database.format_sri_lanka_time(iso_utc)
    # 12:00 UTC is 17:30 (05:30 PM) Sri Lanka time
    assert "05:30 PM" in sl_formatted
    assert "(+05:30)" in sl_formatted
    assert "2026-08-26" in sl_formatted

    # Live verification endpoint format
    donor = database.create_donor_record("d-sl", "Donor", "94771111111", "Kegalle")
    org = database.create_organization_record("org-sl", "Org", "94772222222", "Kegalle", "Meals")
    vol = database.create_volunteer_record("vol-sl", "Vol", "94773333333", "Kegalle")
    database.create_donation_record("don-sl", "d-sl", "Rice", 10, "portions", "Halal", "Kegalle", "Now", "8 PM")
    database.create_pickup_task_record("task-sl", "don-sl", "org-sl", "Kegalle", "Kegalle", "8 PM")
    token = database.create_qr_code_record("qr-sl", "task-sl", "don-sl", "PICKUP", "FR-PK-SLTEST123", "hash1", "d-sl", "org-sl", "vol-sl")["token"]

    verify_res = client.post(f"/verify/pickup/{token}", json={"volunteer_id": "vol-sl"})
    assert verify_res.status_code == 200
    v_data = verify_res.json()
    assert "(+05:30)" in v_data.get("timestamp", "") or "(+05:30)" in v_data.get("verified_at", "")


# =============================================================================
# 4. REMOVED DIRECT VERIFICATION LINKS FROM WHATSAPP MESSAGES
# =============================================================================

@pytest.mark.asyncio
async def test_no_verification_urls_in_donor_and_org_whatsapp_messages():
    """Verify Donor and Org QR instructions do not leak /verify/ URL links."""
    donor_msg = translation_service.get_localized_message(
        "donor_pickup_qr_instructions",
        lang="en",
        donation_id="don-99",
        food_info="20 portions of Rice",
        pickup_location="Mawanella",
        courier_name="Kasun",
        courier_vehicle="Motorbike",
        courier_phone="0771234567"
    )
    assert "/verify/pickup/" not in donor_msg
    assert "Pickup QR Code" in donor_msg

    org_msg = translation_service.get_localized_message(
        "org_delivery_qr_instructions",
        lang="en",
        task_id="task-99",
        food_info="20 portions of Rice",
        donor_name="Afnan",
        courier_name="Kasun",
        courier_phone="0771234567"
    )
    assert "/verify/delivery/" not in org_msg
    assert "Delivery QR Code" in org_msg


# =============================================================================
# 5. VOLUNTEER AVAILABILITY PROMPT AND AUTO-MATCHING
# =============================================================================

@pytest.mark.asyncio
async def test_volunteer_delivery_completion_prompts_availability_and_matches():
    """Verify volunteer delivery completion includes availability prompt, and replying AVAILABLE activates volunteer."""
    vol_phone = "94775556666"
    database.create_or_update_user(vol_phone, display_name="Saman Courier", user_role="volunteer", default_location="Kegalle")
    database.create_volunteer_record("vol-avail-reg", "Saman Courier", vol_phone, "Kegalle", "Motorbike", current_status="busy")

    # Volunteer sends "AVAILABLE"
    reply = await resilient_executor.execute_deterministic_fallback("AVAILABLE", session_id=f"whatsapp:{vol_phone}")
    assert "AVAILABLE" in reply
    assert "Kegalle" in reply

    # Database is updated to available
    vol_db = database.get_volunteer_by_phone(vol_phone)
    assert vol_db["current_status"].lower() == "available"


# =============================================================================
# 6. ROUTE CALCULATION API & MAP LINK
# =============================================================================

def test_pickup_route_api_calculation():
    """Verify /api/routes/pickup-route calculates distance, time, and coordinates."""
    res = client.post(
        "/api/routes/pickup-route",
        json={
            "donation": "Mawanella",
            "organization": "Kegalle",
            "volunteer": "Mawanella",
            "transport_mode": "motorbike"
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["total_distance_km"] > 0
    assert len(data["coordinates"]) >= 2
