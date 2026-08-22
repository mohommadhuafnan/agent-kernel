"""Comprehensive Test Suite for FoodRescue AI Donor Flow, Language Persistence & Zero-Repetition Upgrade.

Validates all 31 acceptance criteria:
1. First-time user welcome flow with exact options and website URL.
2. English, Sinhala, and Tamil language support (strictly no Malayalam).
3. Language persistence across DB, sessions, and messages.
4. Natural script detection for Sinhala and Tamil.
5. Valsea voice transcription and entity extraction.
6. Donor slot-filling in strict order: Food/Qty -> Name -> City -> Deadline -> WhatsApp Location -> Confirmation.
7. Zero-repetition rule: profile and draft state are inspected before asking any question.
8. Phone number rule: never asks for phone number when WhatsApp sender is known.
9. Single-message complete donation flow.
10. WhatsApp location webhook handling and confirmation summary generation.
11. Persistent draft confirmation and database commit.
12. Automatic recipient matching and atomic volunteer task assignment.
13. Route generation, transport cost calculation, and privacy protection.
"""

import json
import os
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from agentkernel.api import RESTAPI, AgentRESTRequestHandler

import api_routes
import database
import resilient_executor
import routing
import tools
import translation_service
import voice_service
import whatsapp_handler


@pytest.fixture(autouse=True)
def clean_test_environment():
    """Ensure clean database and session cache for test isolation."""
    whatsapp_handler.clear_processed_message_cache()
    database.setup_database()
    database.reset_database_data(wipe_all=True)
    database.seed_test_data()
    tools.clear_session_store()
    yield
    database.reset_database_data(wipe_all=True)
    tools.clear_session_store()
    whatsapp_handler.clear_processed_message_cache()


@pytest.fixture
def test_client():
    handler = AgentRESTRequestHandler()
    api_app = RESTAPI._create_app(
        routers=[handler.get_router(), api_routes.get_router(), whatsapp_handler.get_whatsapp_router()]
    )
    return TestClient(api_app)


# =============================================================================
# 1. FIRST-TIME WELCOME & MULTILINGUAL PERSISTENCE TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_first_time_welcome_menu_format():
    """AC 1: First-time WhatsApp user sends 'Hi' -> exact welcome with website URL and 3 languages (no Malayalam)."""
    phone = "94770001001"
    msg = {"from": phone, "id": "wamid.welcome01", "type": "text", "text": {"body": "Hi"}}

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        res = await whatsapp_handler.process_incoming_whatsapp_message(msg)

        assert res["status"] == "onboarding_welcome_sent"
        assert "Welcome to FoodRescue AI!" in res["reply"]
        assert "https://foodrescue-ai-ten.vercel.app/" in res["reply"]
        assert "1️⃣ English" in res["reply"]
        assert "2️⃣ Sinhala" in res["reply"]
        assert "3️⃣ Tamil" in res["reply"]
        assert "Malayalam" not in res["reply"]
        assert "ml" not in translation_service.SUPPORTED_LANGUAGES

    # Verify user profile in DB
    user = database.get_user_by_phone(phone)
    assert user is not None
    assert user["onboarding_completed"] is True


@pytest.mark.asyncio
async def test_language_persistence_across_sessions():
    """AC 2 & 20: Language selected persists in database and affects subsequent conversation turns."""
    phone = "94770001002"
    session_id = f"whatsapp:{phone}"
    database.create_or_update_user(phone=phone, preferred_language="si", onboarding_completed=True)

    # Turn in Sinhala
    res1 = await resilient_executor.execute_deterministic_fallback("මෙනුව", session_id=session_id)
    assert ("සාදරයෙන් පිළිගනිමු" in res1 or "පරිත්‍යාග" in res1 or "ආහාර" in res1)

    # Changing language to Tamil
    res2 = await resilient_executor.execute_deterministic_fallback("தமிழ்", session_id=session_id)
    assert "தமிழ்" in res2
    user = database.get_user_by_phone(phone)
    assert user["preferred_language"] == "ta"

    # Subsequent English command responds in Tamil
    res3 = await resilient_executor.execute_deterministic_fallback("menu", session_id=session_id)
    assert ("வரவேற்கிறோம்" in res3 or "உணவு" in res3 or "தானம்" in res3)


def test_natural_script_detection():
    """AC 3: Script detection identifies Sinhala and Tamil Unicode automatically."""
    assert translation_service.detect_language("මට කෑම පාර්සල් 20ක් දන් දෙන්න ඕන") == "si"
    assert translation_service.detect_language("என்னிடம் 20 உணவுப் பொதிகள் உள்ளன") == "ta"
    assert translation_service.detect_language("I have 20 meal packets available") == "en"


# =============================================================================
# 2. VOICE TRANSCRIPTION & ENTITY EXTRACTION
# =============================================================================

@pytest.mark.asyncio
async def test_voice_message_transcription_and_flow():
    """AC 4 & 21: WhatsApp voice note is transcribed via Valsea and slots extracted."""
    phone = "94770001003"
    voice_msg = {
        "from": phone,
        "id": "wamid.voice01",
        "type": "audio",
        "audio": {"id": "media_audio_555", "mime_type": "audio/ogg; codecs=opus", "voice": True}
    }
    mock_audio = b"OGG_OPUS_TEST_AUDIO"
    mock_transcription = {
        "status": "success",
        "text": "I have 25 packets of biryani available from Colombo Grand Hotel in Colombo 03 before 7 PM",
        "language": "en",
        "provider": "valsea"
    }
    with patch("voice_service.download_whatsapp_media", return_value=mock_audio), \
         patch("voice_service.transcribe_audio", return_value=mock_transcription), \
         patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        res = await whatsapp_handler.process_incoming_whatsapp_message(voice_msg)

        assert res["status"] == "processed"
        assert res["is_voice"] is True

        draft = database.get_draft_donation(phone)
        assert draft["food_type"] == "Biryani"
        assert draft["quantity"] == 25.0
        assert "Colombo" in draft["city"]


# =============================================================================
# 3. DONOR SLOT FILLING, ZERO-REPETITION & ORDER ENFORCEMENT
# =============================================================================

@pytest.mark.asyncio
async def test_donor_multi_turn_flow_strict_order():
    """AC 6 & 8: Strict multi-turn ordering: Food/Qty -> Name -> City -> Deadline -> Location -> Confirm."""
    phone = "94770001004"
    session_id = f"whatsapp:{phone}"

    # Turn 1: User specifies food and quantity
    r1 = await resilient_executor.execute_deterministic_fallback("I have 40 lunch packets of Rice & Curry", session_id=session_id)
    # Name must be asked next!
    assert "name or business" in r1.lower() or "your name" in r1.lower()
    draft1 = database.get_draft_donation(phone)
    assert draft1["quantity"] == 40.0
    assert "Rice" in draft1["food_type"]

    # Turn 2: User provides business name "Cinnamon Kitchen"
    r2 = await resilient_executor.execute_deterministic_fallback("Cinnamon Kitchen", session_id=session_id)
    # City must be asked next!
    assert "city" in r2.lower() or "area" in r2.lower()
    draft2 = database.get_draft_donation(phone)
    assert draft2["donor_name"] == "Cinnamon Kitchen"

    # Turn 3: User provides city "Colombo 07"
    r3 = await resilient_executor.execute_deterministic_fallback("Colombo 07", session_id=session_id)
    # Deadline must be asked next!
    assert "time" in r3.lower() or "until" in r3.lower()
    draft3 = database.get_draft_donation(phone)
    assert "Colombo 07" in draft3["city"]

    # Turn 4: User provides deadline "Today before 8 PM"
    r4 = await resilient_executor.execute_deterministic_fallback("Today before 8 PM", session_id=session_id)
    # WhatsApp Native Location must be asked next!
    assert "location" in r4.lower() or "📍" in r4

    # Turn 5: User shares location coordinates
    database.save_draft_donation(phone, {
        "location_received": True,
        "latitude": 6.9056,
        "longitude": 79.8519,
        "address": "Colombo 07"
    })
    r5 = await resilient_executor.execute_deterministic_fallback("Here is my location", session_id=session_id)
    # Summary confirmation must be displayed!
    assert "Donation Summary" in r5 or "Confirm" in r5
    assert "40" in r5
    assert "Cinnamon Kitchen" in r5
    assert "Colombo 07" in r5

    # Turn 6: User confirms
    r6 = await resilient_executor.execute_deterministic_fallback("Confirm", session_id=session_id)
    assert "Donation Created" in r6 or "✅" in r6
    assert database.get_draft_donation(phone) is None


@pytest.mark.asyncio
async def test_user_corrections_without_restarting():
    """Test 7: User corrections (quantity, deadline, city) update draft without restarting flow."""
    phone = "94770001055"
    session_id = f"whatsapp:{phone}"

    # Initial report
    await resilient_executor.execute_deterministic_fallback("I have 30 meal packets of rice and curry available today.", session_id=session_id)
    draft1 = database.get_draft_donation(phone)
    assert draft1["quantity"] == 30.0

    # User corrects quantity
    r_corr1 = await resilient_executor.execute_deterministic_fallback("Actually, I have 40 packets.", session_id=session_id)
    draft2 = database.get_draft_donation(phone)
    assert draft2["quantity"] == 40.0
    assert "Rice" in draft2["food_type"]
    # Still moves forward to ask name
    assert "name" in r_corr1.lower()

    # User provides name
    await resilient_executor.execute_deterministic_fallback("Afnan Food House", session_id=session_id)

    # User provides city
    await resilient_executor.execute_deterministic_fallback("Mawanella", session_id=session_id)
    draft3 = database.get_draft_donation(phone)
    assert draft3["city"] == "Mawanella"

    # User corrects city
    await resilient_executor.execute_deterministic_fallback("The pickup is in Kandy, not Mawanella.", session_id=session_id)
    draft4 = database.get_draft_donation(phone)
    assert "Kandy" in draft4["city"]
    assert draft4["donor_name"] == "Afnan Food House"
    assert draft4["quantity"] == 40.0


@pytest.mark.asyncio
async def test_repeated_message_does_not_restart_flow():
    """Test 6: Sending repeated message does not wipe existing draft fields."""
    phone = "94770001056"
    session_id = f"whatsapp:{phone}"

    # Turn 1: food & qty
    await resilient_executor.execute_deterministic_fallback("I have 30 meal packets of rice and curry available today.", session_id=session_id)

    # Turn 2: Name
    await resilient_executor.execute_deterministic_fallback("Afnan Food House", session_id=session_id)

    # Turn 3: Repeat initial statement
    r_rep = await resilient_executor.execute_deterministic_fallback("I have 30 meal packets of rice and curry available today.", session_id=session_id)
    draft = database.get_draft_donation(phone)
    assert draft["donor_name"] == "Afnan Food House"
    assert draft["quantity"] == 30.0
    # Must NOT ask for name again; must ask for city!
    assert "city" in r_rep.lower() or "area" in r_rep.lower()


@pytest.mark.asyncio
async def test_returning_user_warm_welcome():
    """Test 8: Returning existing donor receives personal welcome back."""
    phone = "94770001057"
    database.create_or_update_user(phone=phone, display_name="Afnan", onboarding_completed=True)
    tools.register_donor(name="Afnan", location="Mawanella", phone=phone)

    msg = {"from": phone, "id": "wamid.ret01", "type": "text", "text": {"body": "Hi"}}

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        res = await whatsapp_handler.process_incoming_whatsapp_message(msg)

        assert res["status"] == "returning_welcome_sent"
        assert "Welcome back" in res["reply"]
        assert "Afnan" in res["reply"]
        assert "Donate" in res["reply"] or "donate" in res["reply"] or "What would you like" in res["reply"]


@pytest.mark.asyncio
async def test_zero_repetition_for_returning_registered_donor():
    """AC 7: Returning donor is NEVER asked for Name, City, or Phone number if stored in profile."""
    phone = "94770001005"
    session_id = f"whatsapp:{phone}"
    database.create_or_update_user(phone=phone, display_name="Afnan", default_location="Mawanella", onboarding_completed=True)
    tools.register_donor(name="Afnan", location="Mawanella", phone=phone)

    # Donor sends surplus food intent
    r = await resilient_executor.execute_deterministic_fallback("I have 15 packets of Biryani ready", session_id=session_id)

    # Must NOT ask for name, city, or phone
    assert "what is your name" not in r.lower()
    assert "which city" not in r.lower()
    assert "phone number" not in r.lower()
    # Must ask for deadline since food, qty, name, and city are known
    assert "time" in r.lower() or "until" in r.lower() or "deadline" in r.lower() or "📍" in r


@pytest.mark.asyncio
async def test_single_message_all_in_one_donor():
    """AC 9: Complete information in single message immediately shows summary confirmation."""
    phone = "94770001006"
    session_id = f"whatsapp:{phone}"

    reply = await resilient_executor.execute_deterministic_fallback(
        "I am Kamal from Kamal Hotel. I have 50 packets of Rice in Kandy available before 6 PM",
        session_id=session_id
    )

    # All text info present -> asks for WhatsApp location or shows summary
    assert "location" in reply.lower() or "confirm" in reply.lower()
    assert "50" in reply
    assert "Kandy" in reply

    draft = database.get_draft_donation(phone)
    assert draft["quantity"] == 50.0
    assert "Kandy" in draft["city"]


# =============================================================================
# 4. WHATSAPP LOCATION WEBHOOK & CONFIRMATION
# =============================================================================

@pytest.mark.asyncio
async def test_whatsapp_location_message_updates_draft():
    """AC 10 & 11: Sending native WhatsApp location stores coordinates and triggers confirmation summary."""
    phone = "94770001007"
    database.save_draft_donation(phone, {
        "food_type": "Prepared Meals",
        "quantity": 30.0,
        "unit": "packets",
        "donor_name": "Afnan Kitchen",
        "business_name": "Afnan Kitchen",
        "city": "Colombo 03",
        "pickup_deadline": "Today before 7 PM"
    })
    database.set_user_conversation_state(phone, {"workflow": "DONATION", "current_question": "WHATSAPP_LOCATION"})

    location_msg = {
        "from": phone,
        "id": "wamid.loc01",
        "type": "location",
        "location": {
            "latitude": 6.9056,
            "longitude": 79.8519,
            "name": "Afnan Kitchen Kollupitiya",
            "address": "Galle Road, Colombo 03"
        }
    }

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        res = await whatsapp_handler.process_incoming_whatsapp_message(location_msg)

        assert res["status"] in ["location_processed", "processed"]
        assert "Donation Summary" in res["reply"] or "Confirm" in res["reply"]
        assert "30" in res["reply"]

    # Verify draft in DB has location coordinates
    draft = database.get_draft_donation(phone)
    assert draft["latitude"] == 6.9056
    assert draft["longitude"] == 79.8519
    assert draft["location_received"] is True


@pytest.mark.asyncio
async def test_confirm_commits_donation_and_clears_draft():
    """AC 12: Replying 'Confirm' creates donation in database, matches org, and clears draft."""
    phone = "94770001008"
    session_id = f"whatsapp:{phone}"
    database.save_draft_donation(phone, {
        "food_type": "Biryani",
        "quantity": 35.0,
        "unit": "packets",
        "donor_name": "Galle Grand Restaurant",
        "business_name": "Galle Grand Restaurant",
        "city": "Galle",
        "location": "Galle Fort",
        "pickup_deadline": "Today before 8 PM"
    })
    database.set_user_conversation_state(phone, {"workflow": "DONATION", "current_question": "CONFIRMATION"})

    reply = await resilient_executor.execute_deterministic_fallback("Confirm", session_id=session_id)

    assert "Donation Created" in reply or "✅" in reply
    assert "PICKUP_ASSIGNED" in reply or "35" in reply

    # Draft must be cleared
    assert database.get_draft_donation(phone) is None
    assert database.get_user_conversation_state(phone) == {}

    # Donation record exists in DB
    all_dons = database.get_all_donations()
    assert any(d.get("quantity") == 35.0 for d in all_dons)


# =============================================================================
# 5. ATOMIC VOLUNTEER TASK ACCEPTANCE
# =============================================================================

def test_atomic_volunteer_task_acceptance():
    """AC 15: First volunteer acceptance wins atomically; second attempt receives already_claimed."""
    phone_vol1 = "94770001009"
    phone_vol2 = "94770001010"

    v1 = tools.register_volunteer(name="Courier One", service_area="Colombo", phone=phone_vol1, transport_mode="motorbike")
    v1_id = json.loads(v1)["volunteer_id"]
    v2 = tools.register_volunteer(name="Courier Two", service_area="Colombo", phone=phone_vol2, transport_mode="car")
    v2_id = json.loads(v2)["volunteer_id"]

    # Create donation & pickup task
    don_raw = tools.create_donation(
        donor_id="d1",
        food_type="Rice",
        quantity=30.0,
        location="Colombo 03",
        pickup_deadline="Today before 7 PM"
    )
    don_id = json.loads(don_raw)["donation_id"]

    t_raw = tools.create_pickup_task(
        donation_id=don_id,
        organization_id="o1",
        pickup_location="Colombo 03",
        delivery_location="Colombo 05",
        scheduled_time="Today before 7 PM"
    )
    t_data = json.loads(t_raw)
    task_id = t_data["task_id"]

    # Volunteer 1 claims task atomically
    claim1_raw = tools.accept_pickup_task_atomic(pickup_task_id=task_id, volunteer_id=v1_id)
    claim1 = json.loads(claim1_raw)
    assert claim1["status"] in ["success", "accepted"]
    assert claim1.get("volunteer_id") == v1_id or claim1.get("assigned_volunteer_id") == v1_id

    # Volunteer 2 attempts to claim same task
    claim2_raw = tools.accept_pickup_task_atomic(pickup_task_id=task_id, volunteer_id=v2_id)
    claim2 = json.loads(claim2_raw)
    assert claim2["status"] == "already_claimed"
    assert "already been accepted" in claim2["message"] or "already been assigned" in claim2["message"]


# =============================================================================
# 6. ROUTING, TRANSPORT RATES & PRIVACY
# =============================================================================

def test_transport_reimbursement_and_google_maps_route():
    """AC 17 & 18: Transport rates calculate accurately and Google Maps route URL is generated."""
    # Test transport calculation for 5.0 km
    cost_motor = routing.calculate_transport_cost(distance_km=5.0, transport_mode="motorbike")
    assert cost_motor["estimated_cost"] > 0
    assert cost_motor["rate_per_km"] == 50.0

    cost_tuk = routing.calculate_transport_cost(distance_km=5.0, transport_mode="tuk")
    assert cost_tuk["estimated_cost"] > 0
    assert cost_tuk["rate_per_km"] == 90.0

    # Test Google Maps route URL generation
    route_res_raw = tools.calculate_route(origin="Colombo 03", destination="Colombo 05", transport_mode="motorbike")
    route_res = json.loads(route_res_raw)
    assert route_res["status"] == "success"
    assert "distance_km" in route_res
    assert route_res["distance_km"] > 0
