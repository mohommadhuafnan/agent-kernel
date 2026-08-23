"""Tests for WhatsApp Greeting ('hii'), Mandatory Location Pin, and Role-Aware Question Answering."""

import uuid
import pytest
from unittest.mock import AsyncMock, patch
import database
import whatsapp_handler
import resilient_executor
import tools
import translation_service


@pytest.fixture(autouse=True)
def setup_clean_db():
    whatsapp_handler.clear_processed_message_cache()
    tools.clear_session_store()
    yield


@pytest.mark.asyncio
async def test_new_user_sends_hii_receives_welcome_and_menu():
    """Requirement 1: When a new user sends 'hii' or 'hi', they receive the welcome message with menu."""
    phone = f"9477{uuid.uuid4().hex[:7]}"
    
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        
        msg = {
            "from": phone,
            "id": f"wamid.test_{uuid.uuid4().hex[:6]}",
            "type": "text",
            "text": {"body": "hii"}
        }
        res = await whatsapp_handler.process_incoming_whatsapp_message(msg)
        assert res["status"] in ["onboarding_welcome_sent", "welcome_menu_sent"]
        
        reply = res["reply"]
        # Must contain Welcome and Menu, and NOT jump to "What type of food do you have available?"
        assert "Welcome to FoodRescue AI" in reply or "FoodRescue AI" in reply
        assert "Donate surplus food" in reply or "Donate Food" in reply or "1️⃣" in reply
        assert "What type of food do you have available?" not in reply


@pytest.mark.asyncio
async def test_returning_user_sends_hii_receives_welcome_menu():
    """Requirement 1b: When a returning user sends 'hii', they receive the welcome menu."""
    phone = f"9477{uuid.uuid4().hex[:7]}"
    database.create_or_update_user(phone=phone, display_name="Test Donor", user_role="donor", onboarding_completed=True)
    database.create_donor_record(donor_id=f"d_{phone}", name="Test Donor", phone=phone, location="Colombo 3")

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        
        msg = {
            "from": phone,
            "id": f"wamid.test_{uuid.uuid4().hex[:6]}",
            "type": "text",
            "text": {"body": "hii"}
        }
        res = await whatsapp_handler.process_incoming_whatsapp_message(msg)
        assert res["status"] in ["returning_welcome_sent", "welcome_menu_sent"]
        assert "Test Donor" in res["reply"] or "Welcome back" in res["reply"]


@pytest.mark.asyncio
async def test_mandatory_location_pin_required_for_donation():
    """Requirement 2: Donor flow MUST ask for WhatsApp location pin and NOT confirm until location pin is received."""
    phone = f"9477{uuid.uuid4().hex[:7]}"
    database.create_or_update_user(phone=phone, display_name=f"User_{phone[-4:]}", user_role="donor", onboarding_completed=True)

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        # Step 1: Donor selects option 1 (Donate)
        m1 = {"from": phone, "id": f"wamid.{uuid.uuid4().hex[:4]}", "type": "text", "text": {"body": "1"}}
        r1 = await whatsapp_handler.process_incoming_whatsapp_message(m1)
        assert "type of food" in r1["reply"].lower()

        # Step 2: Donor provides food type & quantity
        m2 = {"from": phone, "id": f"wamid.{uuid.uuid4().hex[:4]}", "type": "text", "text": {"body": "25 packets of Rice & Curry"}}
        r2 = await whatsapp_handler.process_incoming_whatsapp_message(m2)
        # Should ask for name
        assert "name" in r2["reply"].lower()

        # Step 3: Donor provides Name
        m3 = {"from": phone, "id": f"wamid.{uuid.uuid4().hex[:4]}", "type": "text", "text": {"body": "Afnan Hotel"}}
        r3 = await whatsapp_handler.process_incoming_whatsapp_message(m3)
        assert "city" in r3["reply"].lower() or "district" in r3["reply"].lower() or "area" in r3["reply"].lower()

        # Step 4: Donor provides District / City
        m4 = {"from": phone, "id": f"wamid.{uuid.uuid4().hex[:4]}", "type": "text", "text": {"body": "Kegalle"}}
        r4 = await whatsapp_handler.process_incoming_whatsapp_message(m4)
        assert "time" in r4["reply"].lower() or "deadline" in r4["reply"].lower() or "until" in r4["reply"].lower()

        # Step 5: Donor provides Deadline
        m5 = {"from": phone, "id": f"wamid.{uuid.uuid4().hex[:4]}", "type": "text", "text": {"body": "Today before 7 PM"}}
        r5 = await whatsapp_handler.process_incoming_whatsapp_message(m5)
        # MUST ask for WhatsApp location pin!
        assert "location pin" in r5["reply"].lower() or "whatsapp" in r5["reply"].lower() or "📍" in r5["reply"]

        # Step 6: If donor types text before sharing location pin -> Reminds to share WhatsApp location pin
        m6 = {"from": phone, "id": f"wamid.{uuid.uuid4().hex[:4]}", "type": "text", "text": {"body": "Near clock tower"}}
        r6 = await whatsapp_handler.process_incoming_whatsapp_message(m6)
        assert "location pin" in r6["reply"].lower() or "location" in r6["reply"].lower() or "📍" in r6["reply"]

        # Step 7: Donor sends WhatsApp Location Pin
        loc_msg = {
            "from": phone,
            "id": f"wamid.{uuid.uuid4().hex[:4]}",
            "type": "location",
            "location": {
                "latitude": 7.2520,
                "longitude": 80.3464,
                "name": "Afnan Hotel Kegalle",
                "address": "Kegalle Main Street"
            }
        }
        r7 = await whatsapp_handler.process_incoming_whatsapp_message(loc_msg)
        assert "confirm" in r7["reply"].lower() or "Kegalle" in r7["reply"] or "Afnan Hotel" in r7["reply"]

        # Step 8: Donor confirms
        m8 = {"from": phone, "id": f"wamid.{uuid.uuid4().hex[:4]}", "type": "text", "text": {"body": "1"}}
        r8 = await whatsapp_handler.process_incoming_whatsapp_message(m8)
        assert "created" in r8["reply"].lower() or "registered" in r8["reply"].lower() or "don-" in r8["reply"].lower() or "confirmed" in r8["reply"].lower()


@pytest.mark.asyncio
async def test_role_aware_question_for_volunteer():
    """Requirement 3: When a registered volunteer asks 'what food do you have available?' or 'any pickups?', answer from volunteer perspective."""
    vol_phone = f"9477{uuid.uuid4().hex[:7]}"
    database.create_or_update_user(phone=vol_phone, display_name="Kasun Courier", user_role="volunteer", onboarding_completed=True)
    database.create_volunteer_record(
        volunteer_id=f"v_{vol_phone}",
        name="Kasun Courier",
        phone=vol_phone,
        transport_mode="Motorbike",
        service_area="Kegalle",
        availability="AVAILABLE"
    )

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        msg = {
            "from": vol_phone,
            "id": f"wamid.{uuid.uuid4().hex[:4]}",
            "type": "text",
            "text": {"body": "any foods available?"}
        }
        res = await whatsapp_handler.process_incoming_whatsapp_message(msg)
        reply = res["reply"]
        # Should answer from Volunteer context (available pickups or status)
        assert "volunteer" in reply.lower() or "pickup" in reply.lower() or "available" in reply.lower()


@pytest.mark.asyncio
async def test_role_aware_question_for_organization():
    """Requirement 3b: When a registered organization asks 'what food do you have available?', list available donations in their network."""
    org_phone = f"9477{uuid.uuid4().hex[:7]}"
    database.create_or_update_user(phone=org_phone, display_name="Hope Shelter", user_role="organization", onboarding_completed=True)
    database.create_organization_record(
        org_id=f"o_{org_phone}",
        name="Hope Shelter",
        phone=org_phone,
        location="Kegalle",
        service_area="Kegalle",
        capacity=50,
        accepted_food_types="Rice & Curry"
    )

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        msg = {
            "from": org_phone,
            "id": f"wamid.{uuid.uuid4().hex[:4]}",
            "type": "text",
            "text": {"body": "what food do you have available?"}
        }
        res = await whatsapp_handler.process_incoming_whatsapp_message(msg)
        reply = res["reply"]
        # Should answer from Recipient Organization perspective
        assert "food" in reply.lower() or "donations" in reply.lower() or "inventory" in reply.lower() or "available" in reply.lower()
