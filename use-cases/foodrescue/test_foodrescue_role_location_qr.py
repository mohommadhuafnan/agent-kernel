"""Comprehensive unit & integration tests verifying:
1. User Role Identification & Separate Storage (Donor, Organization, Volunteer)
2. Strict Donor Workflow State Progression & WhatsApp Location Pin Gate
3. QR Code URL & Image Delivery to Volunteer on Task Acceptance
"""

import json
import pytest
from unittest.mock import AsyncMock, patch

import database
import qr_service
import resilient_executor
import tools
import whatsapp_handler


@pytest.fixture(autouse=True)
def setup_test_db():
    database.setup_database()
    database.seed_test_data()
    whatsapp_handler.clear_processed_message_cache()


# =============================================================================
# 1. USER ROLE IDENTIFICATION & SEPARATE STORAGE TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_role_identification_and_storage_separation():
    """Verify Donor, Organization, and Volunteer roles are identified and saved separately."""
    phone_donor = "94770000001"
    phone_org = "94770000002"
    phone_vol = "94770000003"

    # User 1 chooses Option 1 -> Donor
    res_donor = await resilient_executor.execute_deterministic_fallback("1", session_id=f"whatsapp:{phone_donor}")
    u1 = database.get_user_by_phone(phone_donor)
    assert u1 is not None
    assert u1.get("user_role") == "donor"
    assert "Food" in res_donor or "Donation" in res_donor or "🍱" in res_donor

    # User 2 chooses Option 2 -> Organization
    res_org = await resilient_executor.execute_deterministic_fallback("2", session_id=f"whatsapp:{phone_org}")
    u2 = database.get_user_by_phone(phone_org)
    assert u2 is not None
    assert u2.get("user_role") == "organization"
    assert "Organization" in res_org or "Support" in res_org or "🏢" in res_org

    # User 3 chooses Option 3 -> Volunteer
    res_vol = await resilient_executor.execute_deterministic_fallback("3", session_id=f"whatsapp:{phone_vol}")
    u3 = database.get_user_by_phone(phone_vol)
    assert u3 is not None
    assert u3.get("user_role") == "volunteer"
    assert "Volunteer" in res_vol or "Courier" in res_vol or "❤️" in res_vol


# =============================================================================
# 2. DONOR FLOW LOCATION PIN GATE & NO PREMATURE ADVANCE
# =============================================================================

@pytest.mark.asyncio
async def test_donor_location_pin_gate_prevents_premature_confirmation():
    """Verify donor flow does NOT advance past location step on arbitrary text and requires location pin."""
    phone = "94779998877"
    session_id = f"whatsapp:{phone}"

    # Step 1: Food type & Quantity
    r1 = await resilient_executor.execute_deterministic_fallback("I have 25 packets of Fried Rice", session_id=session_id)
    assert "name" in r1.lower()
    draft = database.get_draft_donation(phone)
    assert draft["food_type"] == "Fried Rice"
    assert draft["quantity"] == 25.0

    # Step 2: Name
    r2 = await resilient_executor.execute_deterministic_fallback("Lotus Hotel", session_id=session_id)
    assert "district" in r2.lower()

    # Step 3: District
    r3 = await resilient_executor.execute_deterministic_fallback("Kegalle", session_id=session_id)
    # Asking for deadline or location pin
    assert "time" in r3.lower() or "deadline" in r3.lower() or "location" in r3.lower() or "📍" in r3 or "⏰" in r3

    # Step 4: Deadline
    r4 = await resilient_executor.execute_deterministic_fallback("Before 7:00 PM", session_id=session_id)
    assert "location pin" in r4.lower() or "📍" in r4

    # Step 5: User sends random non-location text instead of WhatsApp live location pin
    r5 = await resilient_executor.execute_deterministic_fallback("I am currently near the junction", session_id=session_id)
    # Must stay on location pin requirement and NOT advance to confirmation!
    assert "location pin" in r5.lower() or "location" in r5.lower() or "📍" in r5
    assert "donation summary" not in r5.lower()
    assert "published" not in r5.lower()

    # State in DB must still be WHATSAPP_LOCATION
    state = database.get_user_conversation_state(phone)
    assert state.get("current_question") == "WHATSAPP_LOCATION"

    # Step 6: User sends another regular message
    r6 = await resilient_executor.execute_deterministic_fallback("Please hurry up", session_id=session_id)
    assert "location pin" in r6.lower() or "location" in r6.lower() or "📍" in r6
    assert "donation summary" not in r6.lower()

    # Step 7: User finally sends Google Maps GPS link or WhatsApp location
    r7 = await resilient_executor.execute_deterministic_fallback(
        "https://maps.google.com/maps?q=7.2512,80.3464", session_id=session_id
    )
    # NOW all required fields are satisfied -> show donation summary!
    assert "donation summary" in r7.lower() or "confirm" in r7.lower()
    assert "25" in r7
    assert "Lotus Hotel" in r7

    # Step 8: User confirms
    r8 = await resilient_executor.execute_deterministic_fallback("Confirm", session_id=session_id)
    assert "created" in r8.lower() or "✅" in r8 or "matched" in r8.lower() or "assigned" in r8.lower() or "connected" in r8.lower() or "🎉" in r8


# =============================================================================
# 3. DONOR QR CODE DELIVERY & VOLUNTEER SCANNER LINK ON TASK ACCEPTANCE
# =============================================================================

@pytest.mark.asyncio
async def test_donor_receives_pickup_qr_image_and_volunteer_receives_scan_verification_link():
    """Verify that Donor receives the Pickup QR code image to show, and Volunteer receives verification link and instructions to scan."""
    donor_phone = "94771122334"
    org_phone = "94775566778"
    vol_phone = "94779900112"

    database.create_or_update_user(donor_phone, display_name="Afnan Donor", user_role="donor")
    database.create_or_update_user(org_phone, display_name="Hope Charity", user_role="organization")
    database.create_or_update_user(vol_phone, display_name="Kasun Volunteer", user_role="volunteer")

    d = database.create_donor_record("d-vqr", "Afnan Donor", donor_phone, "Kegalle Town")
    o = database.create_organization_record("org-vqr", "Hope Charity", org_phone, "Mawanella", "Prepared Meals")
    v = database.create_volunteer_record("vol-vqr", "Kasun Volunteer", vol_phone, "Kegalle", "Motorbike", current_status="available")

    don = database.create_donation_record("don-vqr", "d-vqr", "Cooked Meals", 30, "packets", "Halal", "Kegalle Town", "Now", "8 PM")
    task = database.create_pickup_task_record("task-vqr", "don-vqr", "org-vqr", "Kegalle Town", "Mawanella", "8 PM")

    # Set volunteer context to offer this task
    database.set_user_conversation_state(
        vol_phone,
        {"workflow": "VOLUNTEER", "current_question": "ACCEPT_TASK", "expected_input_type": "CHOICE", "task_id": "task-vqr"}
    )

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("whatsapp_handler.send_whatsapp_image", new_callable=AsyncMock) as mock_img:
        mock_msg.return_value = {"status": "sent"}
        mock_img.return_value = {"status": "sent"}

        vol_payload = {"from": vol_phone, "id": "msg_vol_1", "type": "text", "text": {"body": "Accept"}}
        res = await whatsapp_handler.process_incoming_whatsapp_message(vol_payload)

        assert res["status"] == "processed"
        reply = res["reply"]

        # 1. Returned message to volunteer contains route details and Mobile Verification Link to scan/verify
        assert "/verify/pickup/FR-PK-" in reply
        assert "Task ID" in reply or "task-vqr" in reply

        # 2. Donor received WhatsApp image message containing the Pickup QR Code to display on screen
        donor_img_calls = [c for c in mock_img.call_args_list if c.kwargs.get("to_number") == donor_phone]
        assert len(donor_img_calls) >= 1
        assert "/api/qr/FR-PK-" in donor_img_calls[0].kwargs.get("image_url")


@pytest.mark.asyncio
async def test_organization_receives_delivery_qr_image_on_food_collection():
    """Verify that Organization receives the Delivery QR code image to show, when food is collected."""
    donor_phone = "94772233445"
    org_phone = "94776677889"
    vol_phone = "94779988776"

    database.create_or_update_user(donor_phone, display_name="City Cafe", user_role="donor")
    database.create_or_update_user(org_phone, display_name="Elder Care Home", user_role="organization")
    database.create_or_update_user(vol_phone, display_name="Ravi Courier", user_role="volunteer")

    d = database.create_donor_record("d-dqr", "City Cafe", donor_phone, "Kegalle")
    o = database.create_organization_record("org-dqr", "Elder Care Home", org_phone, "Mawanella", "Meals")
    v = database.create_volunteer_record("vol-dqr", "Ravi Courier", vol_phone, "Kegalle", "Motorbike", current_status="busy")

    don = database.create_donation_record("don-dqr", "d-dqr", "Fried Rice", 25, "packets", "Halal", "Kegalle", "Now", "8 PM")
    task = database.create_pickup_task_record("task-dqr", "don-dqr", "org-dqr", "Kegalle", "Mawanella", "8 PM")
    database.assign_volunteer_record("task-dqr", "vol-dqr")

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("whatsapp_handler.send_whatsapp_image", new_callable=AsyncMock) as mock_img:
        mock_msg.return_value = {"status": "sent"}
        mock_img.return_value = {"status": "sent"}

        vol_payload = {"from": vol_phone, "id": "msg_vol_col_1", "type": "text", "text": {"body": "Collected"}}
        res = await whatsapp_handler.process_incoming_whatsapp_message(vol_payload)

        assert res["status"] == "processed"

        # Organization received WhatsApp image message containing the Delivery QR Code to display on screen
        org_img_calls = [c for c in mock_img.call_args_list if c.kwargs.get("to_number") == org_phone]
        assert len(org_img_calls) >= 1
        assert "/api/qr/FR-DL-" in org_img_calls[0].kwargs.get("image_url")

