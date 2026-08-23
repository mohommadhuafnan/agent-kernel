"""Test FoodRescue Multi-Party WhatsApp Coordination & Dynamic Logistics.

Verifies:
1. Explicit prompt and persistence of Organization Daily Capacity (no fake default '100 meals').
2. Mandatory prompt and persistence of Donor Food Pickup Deadline (no fake default 'Today before 8 PM').
3. Multi-stage Donor-Organization approval lifecycle:
   - Donor is notified of Organization match with full card & Accept/Reject prompt.
   - Upon Donor Accept, Organization is notified with full Donor details.
4. District Volunteer Dispatch with dynamic distance (KM), dynamic transport reimbursement (LKR/Rs),
   map preview link, and full details card upon volunteer acceptance.
5. Strict cross-notification separation: each party receives their own dedicated message.
"""

import json
import pytest
from unittest.mock import patch, AsyncMock
import database
import tools
import routing
import translation_service
import resilient_executor
import whatsapp_handler


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Reset test database and caches before each test."""
    whatsapp_handler.clear_processed_message_cache()
    database.setup_database()
    database.reset_database_data(wipe_all=True)
    database.seed_test_data()
    tools.clear_session_store()
    tools.set_explicit_session_id(None)
    yield
    database.reset_database_data(wipe_all=True)
    tools.clear_session_store()
    whatsapp_handler.clear_processed_message_cache()


@pytest.mark.asyncio
async def test_dynamic_organization_daily_capacity_no_defaults():
    """Verify Organization registration asks for and persists custom daily capacity (no fake defaults)."""
    org_phone = "94771234001"
    session_id = f"whatsapp:{org_phone}"

    # Turn 1: Organization triggers registration
    r1 = await resilient_executor.execute_deterministic_fallback("2", session_id=session_id)
    assert "name" in r1.lower()

    # Turn 2: Provides name
    r2 = await resilient_executor.execute_deterministic_fallback("Grace Care Sanctuary", session_id=session_id)
    assert "district" in r2.lower() or "located in" in r2.lower()

    # Turn 3: Provides district
    r3 = await resilient_executor.execute_deterministic_fallback("Kandy", session_id=session_id)
    assert "capacity" in r3.lower() or "portions" in r3.lower() or "meals" in r3.lower()

    # Turn 4: Provides explicit daily capacity (e.g. 75 meals/day)
    r4 = await resilient_executor.execute_deterministic_fallback("75 meals per day", session_id=session_id)
    assert "location pin" in r4.lower() or "📍" in r4

    # Verify registered org record in DB has the EXACT dynamic capacity, NOT default 100
    org = database.get_organization_by_phone(org_phone)
    assert org is not None
    assert org["name"] == "Grace Care Sanctuary"
    assert "75 meals" in org["capacity"]
    assert org["service_area"] == "Kandy"


@pytest.mark.asyncio
async def test_donor_food_deadline_mandatory_prompt_and_persistence():
    """Verify Donor flow strictly prompts for food deadline and saves it without fake defaults."""
    donor_phone = "94771234002"
    session_id = f"whatsapp:{donor_phone}"

    # Turn 1: Donor specifies food and quantity
    r1 = await resilient_executor.execute_deterministic_fallback("I have 45 packets of Vegetable Biryani", session_id=session_id)
    assert "name" in r1.lower()
    draft = database.get_draft_donation(donor_phone)
    assert draft["quantity"] == 45.0
    assert "Biryani" in draft["food_type"]

    # Turn 2: Donor gives name
    r2 = await resilient_executor.execute_deterministic_fallback("Hilton Kitchen", session_id=session_id)
    assert "district" in r2.lower()

    # Turn 3: Donor gives district
    r3 = await resilient_executor.execute_deterministic_fallback("Colombo", session_id=session_id)
    # Must ask for DEADLINE
    assert "time" in r3.lower() or "deadline" in r3.lower() or "⏰" in r3 or "pickup" in r3.lower()

    # Turn 4: Donor gives explicit deadline
    r4 = await resilient_executor.execute_deterministic_fallback("Before 9:30 PM tonight", session_id=session_id)
    assert "location pin" in r4.lower() or "📍" in r4

    # Turn 5: Donor sends location coordinates
    database.save_draft_donation(donor_phone, {
        "location_received": True,
        "latitude": 6.9271,
        "longitude": 79.8612,
        "address": "Colombo 03"
    })
    r5 = await resilient_executor.execute_deterministic_fallback("Here is my location pin", session_id=session_id)
    assert "Donation Summary" in r5 or "Confirm" in r5
    assert "45" in r5
    assert "Hilton Kitchen" in r5
    assert "9:30 PM" in r5 or "9:30" in r5


@pytest.mark.asyncio
async def test_multi_stage_approval_donor_to_org_to_volunteers():
    """Verify complete end-to-end multi-party coordination:

    1. Donor confirms donation.
    2. Recipient Organization in same district registers with custom daily capacity.
    3. Donor receives WhatsApp card with Organization details & Accept/Reject choice.
    4. Donor clicks Accept -> Organization receives WhatsApp message with Donor full details.
    5. District volunteer couriers receive task opportunity with dynamic KM and LKR.
    6. Volunteer accepts -> Volunteer receives complete Donor & Org cards + GPS navigation directions link.
    """
    donor_phone = "94779001001"
    org_phone = "94779002002"
    vol_phone = "94779003003"
    other_dist_vol_phone = "94779004004"

    sent_messages = []

    async def mock_send_whatsapp(to_number, text, **kwargs):
        sent_messages.append({"to": to_number, "text": text})
        return {"status": "sent"}

    with patch("whatsapp_handler.send_whatsapp_message", side_effect=mock_send_whatsapp):
        # 1. Register available volunteers in advance
        # Volunteer 1: In Kandy with Three-Wheeler
        tools.register_volunteer(name="Kasun Bandara", transport_mode="Three-Wheeler", service_area="Kandy", phone=vol_phone)
        database.update_user_profile(phone=vol_phone, display_name="Kasun Bandara", user_role="volunteer", default_location="Kandy")

        # Volunteer 2: In Colombo (different district) - Should NOT receive Kandy task
        tools.register_volunteer(name="Saman Perera", transport_mode="Motorbike", service_area="Colombo", phone=other_dist_vol_phone)
        database.update_user_profile(phone=other_dist_vol_phone, display_name="Saman Perera", user_role="volunteer", default_location="Colombo")

        # 2. Donor (Sarah) creates a donation in Kandy
        await whatsapp_handler.process_incoming_whatsapp_message({
            "from": donor_phone, "id": "m1", "type": "text", "text": {"body": "I have 50 packets of Rice & Curry"}
        })
        await whatsapp_handler.process_incoming_whatsapp_message({
            "from": donor_phone, "id": "m2", "type": "text", "text": {"body": "Sarah Cafe"}
        })
        await whatsapp_handler.process_incoming_whatsapp_message({
            "from": donor_phone, "id": "m3", "type": "text", "text": {"body": "Kandy"}
        })
        await whatsapp_handler.process_incoming_whatsapp_message({
            "from": donor_phone, "id": "m4", "type": "text", "text": {"body": "Before 8:00 PM"}
        })
        await whatsapp_handler.process_incoming_whatsapp_message({
            "from": donor_phone, "id": "m5", "type": "text", "text": {"body": "https://maps.google.com/maps?q=7.2906%2C80.6337&z=17"}
        })
        r_confirm = await whatsapp_handler.process_incoming_whatsapp_message({
            "from": donor_phone, "id": "m6", "type": "text", "text": {"body": "Confirm"}
        })
        assert "created" in r_confirm["reply"].lower() or "✅" in r_confirm["reply"]

        # 3. Recipient Organization (Hope Orphanage) registers in Kandy with dynamic capacity (60 meals)
        await whatsapp_handler.process_incoming_whatsapp_message({
            "from": org_phone, "id": "o1", "type": "text", "text": {"body": "2"}
        })
        await whatsapp_handler.process_incoming_whatsapp_message({
            "from": org_phone, "id": "o2", "type": "text", "text": {"body": "Hope Children Orphanage"}
        })
        await whatsapp_handler.process_incoming_whatsapp_message({
            "from": org_phone, "id": "o3", "type": "text", "text": {"body": "Kandy"}
        })
        await whatsapp_handler.process_incoming_whatsapp_message({
            "from": org_phone, "id": "o4", "type": "text", "text": {"body": "60 meals daily capacity"}
        })
        # Org sends location
        r_org_loc = await whatsapp_handler.process_incoming_whatsapp_message({
            "from": org_phone, "id": "o5", "type": "text", "text": {"body": "https://maps.google.com/maps?q=7.2980%2C80.6380&z=17"}
        })
        assert "recorded" in r_org_loc["reply"].lower() or "matched" in r_org_loc["reply"].lower()

        # 4. Donor MUST have received WhatsApp offer message with Organization Details (Name, Daily Capacity, Accept/Reject)
        donor_match_msgs = [m for m in sent_messages if m["to"] == donor_phone and "Hope Children Orphanage" in m["text"]]
        assert len(donor_match_msgs) >= 1
        donor_card = donor_match_msgs[-1]["text"]
        assert "Hope Children Orphanage" in donor_card
        assert "60 meals" in donor_card
        assert "Accept" in donor_card

        # 5. Donor accepts the Organization match
        r_donor_accept = await whatsapp_handler.process_incoming_whatsapp_message({
            "from": donor_phone, "id": "m7", "type": "text", "text": {"body": "Accept"}
        })
        assert "connected" in r_donor_accept["reply"].lower() or "✅" in r_donor_accept["reply"]

        # 6. Organization MUST have received notification message with Donor's Full Details
        org_notifs = [m for m in sent_messages if m["to"] == org_phone and "Sarah Cafe" in m["text"]]
        assert len(org_notifs) >= 1
        org_card = org_notifs[-1]["text"]
        assert "Sarah Cafe" in org_card
        assert "50" in org_card
        assert "Rice & Curry" in org_card
        assert donor_phone in org_card

        # 7. Volunteer in Kandy (Kasun) sends location or checks status -> Receives dynamic task offer with KM & LKR
        r_vol_check = await whatsapp_handler.process_incoming_whatsapp_message({
            "from": vol_phone, "id": "v1", "type": "text", "text": {"body": "https://maps.google.com/maps?q=7.2850%2C80.6300&z=17"}
        })
        assert "pickup available" in r_vol_check["reply"].lower() or "accept" in r_vol_check["reply"].lower()
        vol_offer = r_vol_check["reply"]
        assert "km" in vol_offer.lower()
        assert "LKR" in vol_offer or "Rs" in vol_offer

        # 8. Volunteer in Colombo should NOT have received this Kandy task
        other_dist_msgs = [m for m in sent_messages if m["to"] == other_dist_vol_phone and "Sarah Cafe" in m["text"]]
        assert len(other_dist_msgs) == 0

        # 9. Volunteer accepts the task
        r_vol_accept = await whatsapp_handler.process_incoming_whatsapp_message({
            "from": vol_phone, "id": "v2", "type": "text", "text": {"body": "Accept"}
        })
        assert "assigned" in r_vol_accept["reply"].lower() or "accepted" in r_vol_accept["reply"].lower()
        vol_assigned_card = r_vol_accept["reply"]

        # Verify full details in Volunteer card: Donor & Org details, maps, navigation directions link, LKR support
        assert "Sarah Cafe" in vol_assigned_card
        assert "Hope Children Orphanage" in vol_assigned_card
        assert "60 meals" in vol_assigned_card
        assert "LKR" in vol_assigned_card
        assert "maps.google.com" in vol_assigned_card or "google.com/maps" in vol_assigned_card


@pytest.mark.asyncio
async def test_donor_rejection_keeps_donation_active():
    """Verify Donor rejecting an organization does not cancel the donation."""
    donor_phone = "94779111222"
    session_id = f"whatsapp:{donor_phone}"

    # Seed an organization
    tools.register_organization(name="Old Age Home", location="Colombo", service_area="Colombo", accepted_food_types="Cooked meals", phone="94779111333")

    # Set state as if an org was matched
    database.set_user_conversation_state(donor_phone, {
        "workflow": "DONATION",
        "current_question": "ACCEPT_ORGANIZATION",
        "expected_input_type": "CHOICE",
        "matched_org_id": "o1",
        "donation_id": "don-test-rej",
        "district": "Colombo",
    })

    reply = await resilient_executor.execute_deterministic_fallback("Reject", session_id=session_id)
    assert "active" in reply.lower() or "another organization" in reply.lower()
    # State cleared so user can receive other matches
    assert database.get_user_conversation_state(donor_phone) == {}
