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
    tools.clear_session_store()
    whatsapp_handler.clear_processed_message_cache()


# =============================================================================
# 1. USER ROLE IDENTIFICATION & SEPARATE STORAGE TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_role_identification_and_storage_separation():
    """Verify Donor, Organization, and Volunteer roles are identified and saved separately."""
    import uuid
    uid = uuid.uuid4().hex[:6]
    phone_donor = f"947701{uid[:5]}"
    phone_org = f"947702{uid[:5]}"
    phone_vol = f"947703{uid[:5]}"

    # User 1 chooses Option 1 -> Donor
    res_donor = await resilient_executor.execute_deterministic_fallback("1", session_id=f"whatsapp:{phone_donor}")
    u1 = database.get_user_by_phone(phone_donor)
    assert u1 is not None
    assert u1.get("user_role") == "donor"
    assert any(w in res_donor.lower() for w in ["food", "donation", "rice & curry", "packets", "portions", "🍱", "🍲"])

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
    import uuid
    uid = uuid.uuid4().hex[:6]
    phone = f"947799{uid[:5]}"
    session_id = f"whatsapp:{phone}"
    database.clear_draft_donation(phone)
    database.clear_user_conversation_state(phone)

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
    assert "location pin" in r4.lower() or "location" in r4.lower() or "📍" in r4

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
    import uuid
    uid = uuid.uuid4().hex[:6]
    donor_phone = f"947711{uid[:5]}"
    org_phone = f"947755{uid[:5]}"
    vol_phone = f"947799{uid[:5]}"

    database.create_or_update_user(donor_phone, display_name="Afnan Donor", user_role="donor")
    database.create_or_update_user(org_phone, display_name="Hope Charity", user_role="organization")
    database.create_or_update_user(vol_phone, display_name="Kasun Volunteer", user_role="volunteer")

    d = database.create_donor_record(f"d-{uid}", "Afnan Donor", donor_phone, "Kegalle Town")
    o = database.create_organization_record(f"org-{uid}", "Hope Charity", org_phone, "Mawanella", "Prepared Meals")
    v = database.create_volunteer_record(f"vol-{uid}", "Kasun Volunteer", vol_phone, "Kegalle", "Motorbike", current_status="available")

    don = database.create_donation_record(f"don-{uid}", f"d-{uid}", "Cooked Meals", 30, "packets", "Halal", "Kegalle Town", "Now", "8 PM")
    task = database.create_pickup_task_record(f"task-{uid}", f"don-{uid}", f"org-{uid}", "Kegalle Town", "Mawanella", "8 PM")

    # Set volunteer context to offer this task
    database.set_user_conversation_state(
        vol_phone,
        {"workflow": "VOLUNTEER", "current_question": "ACCEPT_TASK", "expected_input_type": "CHOICE", "task_id": f"task-{uid}"}
    )

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("whatsapp_handler.send_whatsapp_image", new_callable=AsyncMock) as mock_img:
        mock_msg.return_value = {"status": "sent"}
        mock_img.return_value = {"status": "sent"}

        vol_payload = {"from": vol_phone, "id": "msg_vol_1", "type": "text", "text": {"body": "Accept"}}
        res = await whatsapp_handler.process_incoming_whatsapp_message(vol_payload)

        assert res["status"] == "processed"
        reply = res["reply"]

        # 1. Returned message to volunteer contains route details and Mobile Camera Scanner link to scan donor screen
        assert "/scanner" in reply or "scanner" in reply
        assert f"task-{uid}" in reply
        # Anti-cheat check: direct token verification URL is not leaked to volunteer
        assert "FR-PK-" not in reply or "/api/qr/" not in reply

        # 2. Donor received WhatsApp image message containing the Pickup QR Code to display on screen
        donor_img_calls = [c for c in mock_img.call_args_list if c.kwargs.get("to_number") == donor_phone]
        assert len(donor_img_calls) >= 1
        assert "/api/qr/FR-PK-" in donor_img_calls[0].kwargs.get("image_url")


@pytest.mark.asyncio
async def test_organization_receives_delivery_qr_image_on_food_collection():
    """Verify that Organization receives the Delivery QR code image to show, when food is collected."""
    import uuid
    uid = uuid.uuid4().hex[:6]
    donor_phone = f"947722{uid[:5]}"
    org_phone = f"947766{uid[:5]}"
    vol_phone = f"947788{uid[:5]}"

    database.create_or_update_user(donor_phone, display_name="City Cafe", user_role="donor")
    database.create_or_update_user(org_phone, display_name="Elder Care Home", user_role="organization")
    database.create_or_update_user(vol_phone, display_name="Ravi Courier", user_role="volunteer")

    d = database.create_donor_record(f"d-{uid}", "City Cafe", donor_phone, "Kegalle")
    o = database.create_organization_record(f"org-{uid}", "Elder Care Home", org_phone, "Kegalle", "Prepared Meals")
    v = database.create_volunteer_record(f"vol-{uid}", "Ravi Courier", vol_phone, "Kegalle", "Three-Wheeler", current_status="available")

    don = database.create_donation_record(f"don-{uid}", f"d-{uid}", "Rice", 40, "packets", "Standard", "Kegalle", "Now", "9 PM")
    task = database.create_pickup_task_record(f"task-{uid}", f"don-{uid}", f"org-{uid}", "Kegalle", "Mawanella", "8 PM")
    database.assign_volunteer_record(f"task-{uid}", f"vol-{uid}")

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

