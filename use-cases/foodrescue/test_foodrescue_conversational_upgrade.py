import asyncio
import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from agentkernel.api import RESTAPI, AgentRESTRequestHandler

import api_routes
import database
import resilient_executor
import tools
import translation_service
import voice_service
import whatsapp_handler
from db_mongo import MongoRepository
from db_sqlite import SQLiteRepository


@pytest.fixture(autouse=True)
def clean_test_state():
    """Ensure a clean database and session cache before each test."""
    database.setup_database()
    database.reset_database_data()
    database.seed_test_data()
    tools.clear_session_store()
    whatsapp_handler.PROCESSED_MESSAGE_IDS.clear()
    yield
    database.reset_database_data()
    tools.clear_session_store()
    whatsapp_handler.PROCESSED_MESSAGE_IDS.clear()


@pytest.fixture
def test_client():
    handler = AgentRESTRequestHandler()
    api_app = RESTAPI._create_app(
        routers=[handler.get_router(), api_routes.get_router(), whatsapp_handler.get_whatsapp_router()]
    )
    return TestClient(api_app)


# =============================================================================
# 1. DATABASE PERSISTENCE & PARITY (SQLITE & MONGO)
# =============================================================================

def test_database_persistence_sqlite():
    """Test user profile, conversation state, response mode, and draft donation methods in SQLite."""
    phone = "+94770001001"
    
    # User creation and response mode
    u = database.create_or_update_user(phone=phone, display_name="Test User", preferred_language="ta", preferred_response_mode="voice")
    assert u["phone_number"] in [phone, "94770001001"]
    assert u["preferred_language"] == "ta"
    assert u["preferred_response_mode"] == "voice"

    database.set_user_response_mode(phone, "text")
    u2 = database.get_user_by_phone(phone)
    assert u2["preferred_response_mode"] == "text"

    # Conversation state
    state = {"workflow": "DONATION", "current_question": "QUANTITY", "expected_input_type": "QUANTITY"}
    database.set_user_conversation_state(phone, state)
    st = database.get_user_conversation_state(phone)
    assert st["workflow"] == "DONATION"
    assert st["current_question"] == "QUANTITY"

    database.clear_user_conversation_state(phone)
    st_cleared = database.get_user_conversation_state(phone)
    assert st_cleared == {}

    # Draft donation
    draft = database.save_draft_donation(phone, {"food_type": "Rice & Curry", "quantity": 25.0, "location": "Colombo 05"})
    assert draft["food_type"] == "Rice & Curry"
    assert draft["quantity"] == 25.0
    assert draft["location"] == "Colombo 05"

    draft_retrieved = database.get_draft_donation(phone)
    assert draft_retrieved["food_type"] == "Rice & Curry"

    # Merge draft update
    draft_merged = database.save_draft_donation(phone, {"pickup_deadline": "Before 8 PM"})
    assert draft_merged["food_type"] == "Rice & Curry"
    assert draft_merged["pickup_deadline"] == "Before 8 PM"

    database.clear_draft_donation(phone)
    assert not database.get_draft_donation(phone)


import mongomock


def test_database_persistence_mongo_parity():
    """Test user profile, conversation state, response mode, and draft donation methods in MongoRepository."""
    client = mongomock.MongoClient()
    db = client["foodrescue_test"]
    repo = MongoRepository(db_instance=db)
    repo.setup_database()
    phone = "+94770001002"

    u = repo.create_or_update_user(phone=phone, display_name="Mongo User", preferred_language="si", preferred_response_mode="voice")
    assert u["phone_number"] in [phone, "94770001002"]
    assert u["preferred_response_mode"] == "voice"

    repo.set_user_response_mode(phone, "text")
    u2 = repo.get_user_by_phone(phone)
    assert u2["preferred_response_mode"] == "text"

    state = {"workflow": "DONATION", "current_question": "LOCATION"}
    repo.set_user_conversation_state(phone, state)
    assert repo.get_user_conversation_state(phone)["current_question"] == "LOCATION"

    repo.clear_user_conversation_state(phone)
    assert repo.get_user_conversation_state(phone) == {}

    draft = repo.save_draft_donation(phone, {"food_type": "Biryani", "quantity": 30.0})
    assert draft["food_type"] == "Biryani"
    assert repo.get_draft_donation(phone)["quantity"] == 30.0

    repo.clear_draft_donation(phone)
    assert not repo.get_draft_donation(phone)


# =============================================================================
# 2. FIX REPEATED QUESTIONS & DYNAMIC SLOT-FILLING
# =============================================================================

@pytest.mark.asyncio
async def test_dynamic_slot_filling_and_no_repeated_questions():
    """Test multi-turn donation flow: answers are remembered in DB draft and never asked repeatedly."""
    session_id = "whatsapp:+94771122334"
    phone = "+94771122334"

    # Turn 1: User says "I have 20 vegetarian meals"
    r1 = await resilient_executor.execute_deterministic_fallback(
        prompt="I have 20 vegetarian meals",
        session_id=session_id
    )
    # Location should be asked next
    assert "Where can the food be collected" in r1 or "📍" in r1
    draft1 = database.get_draft_donation(phone)
    assert draft1["quantity"] == 20.0
    assert "Vegetarian" in draft1["food_type"]

    # Turn 2: User provides district "Colombo 05" -> Immediately asks for Live Location Pin!
    r2 = await resilient_executor.execute_deterministic_fallback(
        prompt="Colombo 05",
        session_id=session_id
    )
    assert "location" in r2.lower() or "📍" in r2
    assert "How many meals" not in r2
    draft2 = database.get_draft_donation(phone)
    assert draft2["location"] == "Colombo 05"

    # Turn 3: User shares live location coordinates
    database.save_draft_donation(phone, {
        "location_received": True,
        "latitude": 6.8900,
        "longitude": 79.8700,
        "pickup_deadline": "Before 8 PM"
    })
    r3 = await resilient_executor.execute_deterministic_fallback(
        prompt="Here is my location pin",
        session_id=session_id
    )
    # All slots collected -> Summary confirmation presented
    assert "Donation Summary" in r3 or "Confirm" in r3
    assert "20" in r3
    assert "Colombo 05" in r3

    # Turn 4: User confirms "Confirm"
    r4 = await resilient_executor.execute_deterministic_fallback(
        prompt="Confirm",
        session_id=session_id
    )
    assert "Donation Created" in r4 or "Donation Confirmed" in r4 or "✅" in r4
    assert "PICKUP_ASSIGNED" in r4 or "Organization" in r4 or "Organizations" in r4 or "Match" in r4 or "recipient" in r4.lower()

    # Turn 5: User accepts matched organization if matched
    if database.get_user_conversation_state(phone).get("current_question") == "ACCEPT_ORGANIZATION":
        r5 = await resilient_executor.execute_deterministic_fallback(
            prompt="Accept",
            session_id=session_id
        )
        assert "Connected" in r5 or "✅" in r5

    # Draft and state are cleared
    assert database.get_draft_donation(phone) is None
    assert database.get_user_conversation_state(phone) == {}


@pytest.mark.asyncio
async def test_all_in_one_message_skips_intermediate_questions():
    """If user provides all text slots at once in one message, ask for location pin and on pin show confirmation immediately."""
    session_id = "whatsapp:+94775566778"
    phone = "+94775566778"

    reply = await resilient_executor.execute_deterministic_fallback(
        prompt="I have 25 vegetarian rice meals at Colombo 05 ready before 8 PM",
        session_id=session_id
    )
    assert "location" in reply.lower() or "📍" in reply
    assert "25" in reply
    assert "Colombo 05" in reply

    # Draft in DB is populated
    draft = database.get_draft_donation(phone)
    assert draft is not None
    assert draft["quantity"] == 25.0
    assert draft["location"] == "Colombo 05"


@pytest.mark.asyncio
async def test_in_place_slot_update_does_not_create_duplicate_draft():
    """User correcting 'Actually 30 meals' updates draft quantity in-place without duplicating records."""
    session_id = "whatsapp:+94779988776"
    phone = "+94779988776"

    # Initial input: 20 meals
    await resilient_executor.execute_deterministic_fallback("I have 20 meals", session_id)
    assert database.get_draft_donation(phone)["quantity"] == 20.0

    # In-place update: "Actually 30 meals"
    await resilient_executor.execute_deterministic_fallback("Actually 30 meals", session_id)
    draft = database.get_draft_donation(phone)
    assert draft["quantity"] == 30.0


# =============================================================================
# 3. NUMBERED MENUS & CONTEXT-AWARE DISAMBIGUATION
# =============================================================================

@pytest.mark.asyncio
async def test_context_aware_numbered_food_choice():
    """When asked for food type, typing '1' selects 'Rice & Curry' and advances to quantity without resetting."""
    session_id = "whatsapp:+94771230001"
    phone = "+94771230001"

    # Start donation flow with '1'
    r1 = await resilient_executor.execute_deterministic_fallback("1", session_id)
    assert "What type of Food do you have for Donation?" in r1

    # Reply '1' for Rice & Curry
    r2 = await resilient_executor.execute_deterministic_fallback("1", session_id)
    # Next question is quantity
    assert "How many meals" in r2 or "📦" in r2
    draft = database.get_draft_donation(phone)
    assert draft["food_type"] == "Rice & Curry"


@pytest.mark.asyncio
async def test_quantity_15_not_mistaken_for_menu_item_15():
    """When asked for quantity, typing '15' is parsed as 15 portions and not an invalid menu choice."""
    session_id = "whatsapp:+94771230002"
    phone = "+94771230002"

    database.save_draft_donation(phone, {"food_type": "Biryani"})
    database.set_user_conversation_state(phone, {"workflow": "DONATION", "current_question": "QUANTITY", "expected_input_type": "QUANTITY"})

    reply = await resilient_executor.execute_deterministic_fallback("15", session_id)
    # Next question should be location
    assert "Where can the food be collected" in reply or "📍" in reply
    draft = database.get_draft_donation(phone)
    assert draft["quantity"] == 15.0


@pytest.mark.asyncio
async def test_multiple_food_selection_1_and_3():
    """User entering '1 and 3' when asked for food type combines both options."""
    session_id = "whatsapp:+94771230003"
    phone = "+94771230003"

    database.set_user_conversation_state(phone, {"workflow": "DONATION", "current_question": "FOOD_TYPE", "expected_input_type": "FOOD_CHOICE"})
    await resilient_executor.execute_deterministic_fallback("1 and 3", session_id)

    draft = database.get_draft_donation(phone)
    assert "Rice" in draft["food_type"]
    assert "Vegetarian" in draft["food_type"]


@pytest.mark.asyncio
async def test_custom_food_entry_other():
    """User entering '5' or 'Other - vegetable biryani' saves custom food type."""
    session_id = "whatsapp:+94771230004"
    phone = "+94771230004"

    database.set_user_conversation_state(phone, {"workflow": "DONATION", "current_question": "FOOD_TYPE", "expected_input_type": "FOOD_CHOICE"})
    await resilient_executor.execute_deterministic_fallback("Other - vegetable biryani", session_id)

    draft = database.get_draft_donation(phone)
    assert "Biryani" in draft["food_type"] or "biryani" in draft["food_type"].lower()


# =============================================================================
# 4. MULTILINGUAL & VOICE PIPELINE
# =============================================================================

@pytest.mark.asyncio
async def test_natural_language_change_tamil():
    """User says 'தமிழ்' or 'Change language to Tamil' -> persisted in DB without asking every message."""
    session_id = "whatsapp:+94772233445"
    phone = "+94772233445"

    reply = await resilient_executor.execute_deterministic_fallback("Change language to Tamil", session_id)
    assert "தமிழ்" in reply

    user = database.get_user_by_phone(phone)
    assert user["preferred_language"] == "ta"

    # Next message in English script responds in Tamil!
    r2 = await resilient_executor.execute_deterministic_fallback("menu", session_id)
    assert "FoodRescue AI" in r2 and ("வரவேற்கிறோம்" in r2 or "உணவ" in r2 or "தமிழ்" in r2 or "தானம்" in r2)


@pytest.mark.asyncio
async def test_natural_language_change_sinhala():
    """User says 'සිංහලෙන් කතා කරන්න' -> persisted in DB."""
    session_id = "whatsapp:+94773344556"
    phone = "+94773344556"

    reply = await resilient_executor.execute_deterministic_fallback("සිංහලෙන් කතා කරන්න", session_id)
    assert "සිංහල" in reply

    user = database.get_user_by_phone(phone)
    assert user["preferred_language"] == "si"


@pytest.mark.asyncio
async def test_tamil_voice_entity_extraction():
    """Tamil message extracts Tamil units and returns localized response."""
    entities = voice_service.extract_donation_entities("என்னிடம் 30 உணவுப் பொதிகள் உள்ளன கொழும்பு 03")
    assert entities["quantity"] == 30.0
    assert entities["location"] == "Colombo 03"


@pytest.mark.asyncio
async def test_response_mode_preference():
    """User requests voice replies -> preferred_response_mode updated to voice."""
    session_id = "whatsapp:+94774455667"
    phone = "+94774455667"

    reply = await resilient_executor.execute_deterministic_fallback("Voice replies please", session_id)
    assert "VOICE" in reply

    user = database.get_user_by_phone(phone)
    assert user["preferred_response_mode"] == "voice"


# =============================================================================
# 5. RETURNING USER RECOGNITION
# =============================================================================

@pytest.mark.asyncio
async def test_returning_donor_recognized_by_profile():
    """Returning registered donor greeting uses returning_donor_welcome with their name."""
    phone = "94770009999"
    database.create_or_update_user(phone=phone, display_name="Hilton Colombo", preferred_language="en", onboarding_completed=True)
    tools.register_donor(name="Hilton Colombo", location="Colombo 01", phone=phone)

    msg = {"from": phone, "id": "wamid.ReturningDonorTest", "type": "text", "text": {"body": "menu"}}
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        res = await whatsapp_handler.process_incoming_whatsapp_message(msg)

        assert res["status"] == "returning_welcome_sent"
        assert "Hilton Colombo" in res["reply"]
        assert "Registered Donor" in res["reply"]


# =============================================================================
# 6. ERROR SHIELDING & WEBHOOK RELIABILITY
# =============================================================================

@pytest.mark.asyncio
async def test_error_shielding_no_stack_traces(test_client):
    """Internal exceptions during message handling are caught and shielded with a localized error message."""
    phone = "94770008888"
    msg = {"from": phone, "id": "wamid.ErrorShieldTest", "type": "text", "text": {"body": "cause error"}}

    with patch("resilient_executor.run_resilient_chat", side_effect=Exception("Critical Database Connection Timeout")):
        with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"status": "sent"}
            res = await whatsapp_handler.process_incoming_whatsapp_message(msg)

            assert "Critical Database Connection Timeout" not in res["reply"]
            assert "Traceback" not in res["reply"]
            assert "I'm sorry" in res["reply"] or "trouble" in res["reply"]


@pytest.mark.asyncio
async def test_webhook_deduplication_idempotency(test_client):
    """Duplicate message ID from Meta webhook is ignored cleanly."""
    phone = "94770007777"
    msg = {"from": phone, "id": "wamid.DedupUniqueId01", "type": "text", "text": {"body": "Hello FoodRescue"}}

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        r1 = await whatsapp_handler.process_incoming_whatsapp_message(msg)
        r2 = await whatsapp_handler.process_incoming_whatsapp_message(msg)

        assert r1["status"] in ["onboarding_welcome_sent", "returning_welcome_sent", "processed"]
        assert r2["status"] == "ignored"
        assert r2["reason"] == "duplicate_message_id"


# =============================================================================
# 7. MULTI-ROLE TOOLS EXTENSION
# =============================================================================

def test_conversation_state_and_draft_tools():
    """Verify new agent tools for conversation state and draft donations."""
    phone = "+94778899001"
    tools.set_explicit_session_id(f"whatsapp:{phone}")

    # set_conversation_state tool
    s_raw = tools.set_conversation_state(state=json.dumps({"workflow": "DONATION", "current_question": "LOCATION"}), phone=phone)
    s = json.loads(s_raw)
    assert s["status"] == "success"
    assert s["state"]["current_question"] == "LOCATION"

    # get_conversation_state tool
    g_raw = tools.get_conversation_state(phone=phone)
    g = json.loads(g_raw)
    assert g["state"]["current_question"] == "LOCATION"

    # update_draft_donation tool
    d_raw = tools.update_draft_donation(food_type="Pastries", quantity=50, unit="pieces", location="Galle", phone=phone)
    d = json.loads(d_raw)
    assert d["status"] == "success"
    assert d["draft"]["food_type"] == "Pastries"
    assert d["draft"]["quantity"] == 50.0

    # get_draft_donation tool
    gd_raw = tools.get_draft_donation(phone=phone)
    gd = json.loads(gd_raw)
    assert gd["draft"]["location"] == "Galle"

    # get_user_profile tool
    prof_raw = tools.get_user_profile(phone=phone)
    prof = json.loads(prof_raw)
    assert prof["status"] == "success"
    assert prof["phone"] == phone
    assert prof["active_draft"]["food_type"] == "Pastries"

    # clear_draft_donation tool
    tools.clear_draft_donation(phone=phone)
    gd_empty = json.loads(tools.get_draft_donation(phone=phone))
    assert gd_empty["draft"] == {}
