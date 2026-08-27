"""Comprehensive Test Suite for FoodRescue AI Multilingual, Voice & Onboarding Upgrade.

Covers:
1. First-time WhatsApp user detection & onboarding experience with website URL.
2. Onboarding idempotency & returning user experience.
3. Multilingual preferences (English, Sinhala, Tamil, Malayalam) and database persistence.
4. Natural script language detection (Sinhala, Tamil, Malayalam Unicode).
5. Voice message webhook reception & Meta Graph API audio downloading.
6. VALSEA Speech-to-Text transcription and error resilience.
7. Voice-to-donation entity extraction & missing information engine.
8. Multilingual volunteer availability, acceptance, collection, and delivery workflows.
9. Error shielding and graceful fallback across all languages.
"""

import os
import json
import uuid
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import database
import tools
import whatsapp_handler
import resilient_executor
import translation_service
import voice_service


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Reset database and caches for clean test isolation."""
    whatsapp_handler.clear_processed_message_cache()
    tools.clear_session_store()
    database.setup_database()
    database.reset_database_data()
    database.seed_test_data()
    # Reset users table for test isolation
    repo = database.get_repository()
    if hasattr(repo, "_get_connection"):
        conn = repo._get_connection()
        with conn:
            conn.execute("DELETE FROM users")
            conn.execute("DELETE FROM organizations WHERE id IN ('org-test', 'org-test-dummy') OR phone LIKE '%94770000002%'")
            conn.execute("DELETE FROM donors WHERE id IN ('d-test', 'd-test-dummy') OR phone LIKE '%94770000001%'")
        conn.close()
    elif hasattr(repo, "users_col"):
        repo.users_col.delete_many({})
    yield


# =============================================================================
# 1. NEW USER ONBOARDING & RETURNING USER FLOWS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_first_time_user_onboarding_welcome():
    """Scenario 1: First-time WhatsApp message triggers comprehensive onboarding with website URL."""
    phone = "94770000001"
    msg = {
        "from": phone,
        "id": "wamid.FirstTimeUser01",
        "type": "text",
        "text": {"body": "Hi"}
    }
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        res = await whatsapp_handler.process_incoming_whatsapp_message(msg)

        assert res["status"] == "onboarding_welcome_sent"
        assert "Welcome to FoodRescue AI" in res["reply"]
        assert "Donate surplus food" in res["reply"]
        assert "Sinhala" in res["reply"]
        assert "Tamil" in res["reply"]
        assert "English" in res["reply"]
        assert "Malayalam" not in res["reply"]

    # Verify user profile in DB
    user = database.get_user_by_phone(phone)
    assert user is not None
    assert user["phone_number"] == phone
    assert user["onboarding_completed"] is True


@pytest.mark.asyncio
async def test_onboarding_only_occurs_once():
    """Scenario 2: Returning user does not receive full onboarding repeatedly."""
    phone = "94770000002"
    # Pre-register user with onboarding completed
    database.create_or_update_user(phone=phone, preferred_language="en", onboarding_completed=True)

    msg = {
        "from": phone,
        "id": "wamid.ReturningUser02",
        "type": "text",
        "text": {"body": "menu"}
    }
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        res = await whatsapp_handler.process_incoming_whatsapp_message(msg)

        assert res["status"] == "returning_welcome_sent"
        assert "Welcome back to FoodRescue AI" in res["reply"]
        # Should not have the long onboarding intro
        assert "Choose your language" not in res["reply"]


@pytest.mark.asyncio
async def test_first_time_user_immediate_intent():
    """Scenario 3: New user sends an immediate donation intent on turn 1."""
    phone = "94770000003"
    msg = {
        "from": phone,
        "id": "wamid.ImmediateIntent03",
        "type": "text",
        "text": {"body": "I have 25 lunch packets to donate in Colombo 3"}
    }
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        res = await whatsapp_handler.process_incoming_whatsapp_message(msg)

        assert res["status"] == "processed"
        # User profile should be created and marked complete
        user = database.get_user_by_phone(phone)
        assert user is not None
        assert user["onboarding_completed"] is True


# =============================================================================
# 2. MULTILINGUAL PREFERENCE & SCRIPT DETECTION
# =============================================================================

@pytest.mark.asyncio
async def test_explicit_language_selection_numeric_and_text():
    """Scenario 4: Explicit language selection via language names and language menu."""
    phone = "94770000004"
    database.create_or_update_user(phone=phone, preferred_language="en", onboarding_completed=True)

    # By language name 'sinhala'
    msg1 = {"from": phone, "id": "wamid.LangSi", "type": "text", "text": {"body": "sinhala"}}
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        res1 = await whatsapp_handler.process_incoming_whatsapp_message(msg1)
        assert res1["status"] == "language_updated"
        assert res1["language"] == "si"
        assert "සිංහල" in res1["reply"]

    user = database.get_user_by_phone(phone)
    assert user["preferred_language"] == "si"

    # By language name 'tamil'
    msg2 = {"from": phone, "id": "wamid.LangTa", "type": "text", "text": {"body": "tamil"}}
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        res2 = await whatsapp_handler.process_incoming_whatsapp_message(msg2)
        assert res2["status"] == "language_updated"
        assert res2["language"] == "ta"
        assert "தமிழ்" in res2["reply"]

    # In language menu, numeric selection 1 -> English, 2 -> Sinhala, 3 -> Tamil
    msg_menu = {"from": phone, "id": "wamid.LangMenuPrompt", "type": "text", "text": {"body": "language"}}
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        await whatsapp_handler.process_incoming_whatsapp_message(msg_menu)

    msg3 = {"from": phone, "id": "wamid.LangEn", "type": "text", "text": {"body": "1"}}
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        res3 = await whatsapp_handler.process_incoming_whatsapp_message(msg3)
        assert res3["status"] == "language_updated"
        assert res3["language"] == "en"
        assert "English" in res3["reply"]


@pytest.mark.asyncio
async def test_main_menu_digit_1_triggers_donation():
    """Scenario 4b: Typing '1' on main menu triggers Donate Food and does NOT change language."""
    phone = "94770000045"
    database.create_or_update_user(phone=phone, preferred_language="en", onboarding_completed=True)

    msg = {"from": phone, "id": "wamid.MainMenu1", "type": "text", "text": {"body": "1"}}
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        res = await whatsapp_handler.process_incoming_whatsapp_message(msg)

        assert res["status"] == "processed"
        assert "Donation" in res["reply"] or "Food" in res["reply"]
        # Language should still be English
        user = database.get_user_by_phone(phone)
        assert user["preferred_language"] == "en"


def test_natural_script_language_detection():
    """Scenario 5: Unicode script analysis detects Sinhala, Tamil, and English."""
    # Sinhala
    assert translation_service.detect_language("මට කෑම දානයක් ලබා දෙන්න ඕන") == "si"
    # Tamil
    assert translation_service.detect_language("என்னிடம் அதிகமான உணவு உள்ளது") == "ta"
    # English
    assert translation_service.detect_language("I have 20 meals available") == "en"


@pytest.mark.asyncio
async def test_language_command_displays_menu():
    """Scenario 6: User typing 'language' receives language selection options."""
    phone = "94770000006"
    msg = {"from": phone, "id": "wamid.LangMenu06", "type": "text", "text": {"body": "language"}}
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        res = await whatsapp_handler.process_incoming_whatsapp_message(msg)
        assert res["status"] == "language_menu"
        assert "English" in res["reply"]
        assert "Sinhala" in res["reply"]
        assert "Tamil" in res["reply"]
        assert "Malayalam" not in res["reply"]


# =============================================================================
# 3. VOICE MESSAGE RECEPTION & VALSEA TRANSCRIPTION
# =============================================================================

@pytest.mark.asyncio
async def test_whatsapp_voice_message_webhook_reception_and_transcription():
    """Scenario 7: Incoming WhatsApp voice note is downloaded, transcribed via VALSEA, and processed."""
    phone = "94770000007"
    voice_msg = {
        "from": phone,
        "id": "wamid.VoiceTest07",
        "type": "audio",
        "audio": {
            "id": "media_audio_12345",
            "mime_type": "audio/ogg; codecs=opus",
            "voice": True
        }
    }

    mock_audio_bytes = b"OGG_OPUS_SAMPLE_AUDIO_DATA_FOR_FOODRESCUE"
    mock_transcription = {
        "status": "success",
        "text": "I have about 15 packets of rice and curry available from our restaurant until 7 PM",
        "language": "en",
        "provider": "valsea"
    }

    with patch("voice_service.download_whatsapp_media", return_value=mock_audio_bytes) as mock_dl, \
         patch("voice_service.transcribe_audio", return_value=mock_transcription) as mock_trans, \
         patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        res = await whatsapp_handler.process_incoming_whatsapp_message(voice_msg)

        assert res["status"] == "processed"
        assert res["is_voice"] is True
        mock_dl.assert_called_once_with("media_audio_12345")
        mock_trans.assert_called_once()


@pytest.mark.asyncio
async def test_voice_transcription_failure_graceful_fallback():
    """Scenario 8: Voice download/transcription failure activates safe fallback without crashing."""
    phone = "94770000008"
    voice_msg = {
        "from": phone,
        "id": "wamid.VoiceFail08",
        "type": "voice",
        "voice": {
            "id": "media_broken_999",
            "mime_type": "audio/ogg"
        }
    }

    with patch("voice_service.download_whatsapp_media", side_effect=Exception("Meta Media Download 404")), \
         patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        res = await whatsapp_handler.process_incoming_whatsapp_message(voice_msg)
        assert res["status"] == "processed"
        assert res["is_voice"] is True


# =============================================================================
# 4. VOICE → FOOD DONATION & MISSING INFORMATION ENGINE
# =============================================================================

def test_voice_entity_extraction_complete_and_partial():
    """Scenario 9: Entity extraction accurately parses food details and detects missing location."""
    # Complete text
    t1 = "I have 20 meal boxes of vegetable rice available in Colombo 7 before 8 PM"
    e1 = voice_service.extract_donation_entities(t1)
    assert e1["quantity"] == 20.0
    assert "Vegetable Rice" in e1["food_type"] or "Prepared Meals" in e1["food_type"]
    assert e1["location"] is not None
    assert e1["pickup_deadline"] is not None
    assert e1["is_complete"] is True

    # Partial text (missing location)
    t2 = "I have about 15 packets of rice and curry available from our restaurant before 7 PM today"
    e2 = voice_service.extract_donation_entities(t2)
    assert e2["quantity"] == 15.0
    assert "location" in e2["missing_fields"]
    assert e2["is_complete"] is False


def test_missing_information_tool():
    """Scenario 10: identify_missing_donation_info tool pinpoints exact missing field."""
    res_raw = tools.identify_missing_donation_info(food_type="Rice & Curry", quantity=15, location=None, deadline="7 PM")
    res = json.loads(res_raw)
    assert res["is_complete"] is False
    assert "location" in res["missing_fields"]
    assert res["next_prompt_field"] == "location"


# =============================================================================
# 5. MULTILINGUAL VOLUNTEER & LIFECYCLE WORKFLOWS
# =============================================================================

@pytest.mark.asyncio
async def test_multilingual_volunteer_availability_sinhala():
    """Scenario 11: Volunteer declaring availability in Sinhala."""
    reply = await resilient_executor.execute_deterministic_fallback(
        "මම දැන් ස්වේච්ඡාවෙන් උදව් කරන්න ලෑස්තියි",
        "whatsapp:+94770000011"
    )
    assert "AVAILABLE" in reply or "සූදානම්" in reply or "Opportunity" in reply


@pytest.mark.asyncio
async def test_multilingual_volunteer_accept_tamil():
    """Scenario 12: Volunteer accepting a task in Tamil."""
    tools.set_session_context(key="current_task_id", value="task-test-ta")
    reply = await resilient_executor.execute_deterministic_fallback(
        "நான் இந்த பணியை ஏற்கிறேன்",
        "whatsapp:+94770000012"
    )
    assert "Assigned" in reply or "உறுதி" in reply


@pytest.mark.asyncio
async def test_multilingual_collection_and_delivery_confirmation():
    """Scenario 13: Volunteer collection and delivery in natural language."""
    # Setup donation and task
    don_raw = tools.create_donation(donor_id="d1", food_type="Meals", quantity=10, location="Colombo 3")
    don = json.loads(don_raw)
    task_raw = tools.create_pickup_task(donation_id=don["donation_id"], organization_id="o1", pickup_location="Colombo 3", delivery_location="Colombo 7")
    task = json.loads(task_raw)
    task_id = task["task_id"]

    tools.assign_volunteer(task_id=task_id, volunteer_id="v1")
    tools.set_session_context(key="current_task_id", value=task_id)

    # Collection
    r1 = await resilient_executor.execute_deterministic_fallback("ලබාගත්තා", f"whatsapp:94770000013")
    assert "COLLECTED" in r1 or "In Transit" in r1 or "Next Step" in r1

    # Delivery
    r2 = await resilient_executor.execute_deterministic_fallback("භාරදුන්නා", f"whatsapp:94770000013")
    assert "Delivery Completed" in r2 or "COMPLETED" in r2 or "LKR" in r2


# =============================================================================
# 6. LOCALIZATION TOOLS & VALSEA AI TRANSLATION
# =============================================================================

def test_language_management_tools():
    """Scenario 14: set_user_preferred_language and get_user_language tools."""
    phone = "94770000014"
    res1 = json.loads(tools.set_user_preferred_language(language="si", phone=phone))
    assert res1["status"] == "success"
    assert res1["language"] == "si"

    res2 = json.loads(tools.get_user_language(phone=phone))
    assert res2["status"] == "success"
    assert res2["language"] == "si"


def test_valsea_translation_api_success():
    """Scenario 15: VALSEA AI Translation API returns high-quality translated text."""
    with patch.dict(os.environ, {"VALSEA_API_KEY": "valsea_test_key_12345"}), \
         patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "translated_text": "ඔබගේ ආහාර පරිත්‍යාගය සාර්ථකව සටහන් විය.",
            "source_language": "en",
            "target_language": "si"
        }
        mock_post.return_value = mock_resp

        result = translation_service.translate_text("Your food donation was successfully recorded.", target_lang="si")
        assert result == "ඔබගේ ආහාර පරිත්‍යාගය සාර්ථකව සටහන් විය."
        mock_post.assert_called_once()


def test_valsea_translation_api_resilient_fallback():
    """Scenario 16: VALSEA AI Translation API error activates resilient offline fallback without error."""
    with patch.dict(os.environ, {"VALSEA_API_KEY": "valsea_test_key_12345"}), \
         patch("requests.post", side_effect=Exception("VALSEA Translation API 503 Service Unavailable")):
        result_si = translation_service.translate_text("Thank you. Your request was received.", target_lang="si")
        assert "ස්තූතියි" in result_si

        result_ta = translation_service.translate_text("Thank you. Your request was received.", target_lang="ta")
        assert "நன்றி" in result_ta


@pytest.mark.asyncio
async def test_persistent_language_across_multiple_conversation_turns_tamil():
    """Scenario 17: User switches to Tamil once, and all subsequent turns remain in Tamil."""
    phone = "94770000017"
    database.clear_draft_donation(phone)
    database.clear_user_conversation_state(phone)

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        # Turn 1: User explicitly changes language to Tamil
        msg1 = {"from": phone, "id": "wamid.Turn1LangTa", "type": "text", "text": {"body": "tamil"}}
        r1 = await whatsapp_handler.process_incoming_whatsapp_message(msg1)
        assert r1["status"] == "language_updated"
        assert r1["language"] == "ta"
        assert "தமிழ்" in r1["reply"]

        # Verify DB preference is saved
        user = database.get_user_by_phone(phone)
        assert user["preferred_language"] == "ta"

        # Turn 2: User sends menu option '1' (Donate Food) - in English digit!
        msg2 = {"from": phone, "id": "wamid.Turn2Option1", "type": "text", "text": {"body": "1"}}
        r2 = await whatsapp_handler.process_incoming_whatsapp_message(msg2)
        assert r2["status"] == "processed"
        # Reply must be in Tamil
        assert any(ch in r2["reply"] for ch in ["உணவு", "தானம்", "அளவு", "பொதி", "நன்கொடை"])

        # Turn 3: User queries status with English word 'status'
        msg3 = {"from": phone, "id": "wamid.Turn3Status", "type": "text", "text": {"body": "what is my donation status"}}
        r3 = await whatsapp_handler.process_incoming_whatsapp_message(msg3)
        assert r3["status"] == "processed"
        # Status response must be in Tamil
        assert any(ch in r3["reply"] for ch in ["நன்கொடை", "செயலில்", "இல்லை", "உணவு"])

        # Turn 4: User cancels donation with English word 'cancel'
        msg4 = {"from": phone, "id": "wamid.Turn4Cancel", "type": "text", "text": {"body": "cancel"}}
        r4 = await whatsapp_handler.process_incoming_whatsapp_message(msg4)
        assert r4["status"] == "processed"
        # Cancellation response must be in Tamil
        assert any(ch in r4["reply"] for ch in ["ரத்து", "நன்கொடை", "உதவி"])

        # Final verification: User preference in DB still 'ta'
        user_final = database.get_user_by_phone(phone)
        assert user_final["preferred_language"] == "ta"


@pytest.mark.asyncio
async def test_persistent_language_across_multiple_conversation_turns_sinhala():
    """Scenario 18: User switches to Sinhala once, and all subsequent turns remain in Sinhala."""
    phone = "94770000018"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        # Turn 1: User explicitly changes language to Sinhala
        msg1 = {"from": phone, "id": "wamid.Turn1LangSi", "type": "text", "text": {"body": "change language to sinhala"}}
        r1 = await whatsapp_handler.process_incoming_whatsapp_message(msg1)
        assert r1["status"] == "language_updated"
        assert r1["language"] == "si"
        assert "සිංහල" in r1["reply"]

        # Verify DB preference is saved
        user = database.get_user_by_phone(phone)
        assert user["preferred_language"] == "si"

        # Turn 2: User queries status with English word 'status'
        msg2 = {"from": phone, "id": "wamid.Turn2StatusSi", "type": "text", "text": {"body": "where is my donation"}}
        r2 = await whatsapp_handler.process_incoming_whatsapp_message(msg2)
        assert r2["status"] == "processed"
        # Status response must be in Sinhala
        assert any(ch in r2["reply"] for ch in ["පරිත්‍යාග", "සක්‍රිය", "හමු", "නොවීය"])

        # Turn 3: User cancels donation with English word 'cancel'
        msg3 = {"from": phone, "id": "wamid.Turn3CancelSi", "type": "text", "text": {"body": "cancel"}}
        r3 = await whatsapp_handler.process_incoming_whatsapp_message(msg3)
        assert r3["status"] == "processed"
        # Cancellation response must be in Sinhala
        assert any(ch in r3["reply"] for ch in ["අවලංගු", "පරිත්‍යාගය", "උපකාර"])


@pytest.mark.asyncio
async def test_voice_transcription_sets_and_persists_language():
    """Scenario 19: WhatsApp voice note in Tamil locks in Tamil preference for subsequent text turns."""
    phone = "94770000019"
    database.create_or_update_user(phone=phone, preferred_language="en", onboarding_completed=True)

    voice_msg = {
        "from": phone,
        "id": "wamid.VoiceTurnTa",
        "type": "audio",
        "audio": {"id": "media_ta_9999", "mime_type": "audio/ogg", "voice": True}
    }
    mock_transcription = {
        "status": "success",
        "text": "என்னிடம் 20 சோறு பொதிகள் உள்ளன கொழும்பு 3",
        "language": "ta",
        "provider": "valsea"
    }

    with patch("voice_service.download_whatsapp_media", return_value=b"OPUS_DATA"), \
         patch("voice_service.transcribe_audio", return_value=mock_transcription), \
         patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        res = await whatsapp_handler.process_incoming_whatsapp_message(voice_msg)
        assert res["status"] == "processed"

        # Verify language is now Tamil
        user = database.get_user_by_phone(phone)
        assert user["preferred_language"] == "ta"

        # Subsequent text message 'menu'
        text_msg = {"from": phone, "id": "wamid.MenuAfterVoice", "type": "text", "text": {"body": "menu"}}
        res_text = await whatsapp_handler.process_incoming_whatsapp_message(text_msg)
        assert res_text["status"] == "returning_welcome_sent"
        # Reply must be in Tamil
        assert "நல்வரவு" in res_text["reply"]


@pytest.mark.asyncio
async def test_web_simulation_new_user_sends_hi_receives_welcome_and_menu():
    """Scenario 20: Web simulation of new user sending 'Hi' returns welcome mission explanation and menu without URL."""
    from fastapi.testclient import TestClient
    from api_routes import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    phone = "94770000020"
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        resp = client.post(f"/api/conversations/{phone}/simulate", json={"message": "Hi"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "Welcome to FoodRescue AI" in data["reply"]
        assert "Donate surplus food" in data["reply"]
        assert "Request available food" in data["reply"]
        assert "Volunteer to collect and deliver food" in data["reply"]
        assert "https://foodrescue-ai-ten.vercel.app/" not in data["reply"]

        # Verify user in database
        u = database.get_user_by_phone(phone)
        assert u is not None
        assert u["onboarding_completed"] is True


@pytest.mark.asyncio
async def test_organization_registration_asks_name_city_food_need_location():
    """Scenario 21: Organization flow asks organization name, city (no default), food need, and requests location pin."""
    phone = f"9477{uuid.uuid4().hex[:7]}"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        # Step 1: User sends option '2' (Request Food / Organization)
        m1 = {"from": phone, "id": f"wamid.OrgTurn1_{uuid.uuid4().hex[:4]}", "type": "text", "text": {"body": "2"}}
        r1 = await whatsapp_handler.process_incoming_whatsapp_message(m1)
        assert "organization's name" in r1["reply"].lower() or "recipient organization support" in r1["reply"].lower()

        # Step 2: User gives organization name
        m2 = {"from": phone, "id": f"wamid.OrgTurn2_{uuid.uuid4().hex[:4]}", "type": "text", "text": {"body": "Hope Children Home"}}
        r2 = await whatsapp_handler.process_incoming_whatsapp_message(m2)
        assert "city or district" in r2["reply"].lower() or "located in" in r2["reply"].lower()
        assert "Hope Children Home" in r2["reply"]

        # Step 3: User gives location in Mawanella (NOT Colombo!)
        m3 = {"from": phone, "id": f"wamid.OrgTurn3_{uuid.uuid4().hex[:4]}", "type": "text", "text": {"body": "Mawanella"}}
        r3 = await whatsapp_handler.process_incoming_whatsapp_message(m3)
        assert "how many portions" in r3["reply"].lower() or "what type of food" in r3["reply"].lower()

        # Step 4: User gives food need
        m4 = {"from": phone, "id": f"wamid.OrgTurn4_{uuid.uuid4().hex[:4]}", "type": "text", "text": {"body": "40 cooked meal packets"}}
        r4 = await whatsapp_handler.process_incoming_whatsapp_message(m4)
        assert "Mawanella" in r4["reply"]
        assert "location pin" in r4["reply"].lower() or "whatsapp" in r4["reply"].lower()

        # Verify organization record and user role in DB
        org = database.get_organization_by_phone(phone)
        assert org is not None
        assert org["name"] == "Hope Children Home"
        assert org["location"] == "Mawanella"

        user = database.get_user_by_phone(phone)
        assert user["user_role"] == "organization"
        assert user["display_name"] == "Hope Children Home"


@pytest.mark.asyncio
async def test_distinct_delivery_completion_messages_for_donor_and_organization():
    """Scenario 22: Volunteer confirms delivery -> Donor receives thank you impact message, Organization receives food arrival notice."""
    donor_phone = f"9477000{uuid.uuid4().hex[:4]}"
    org_phone = f"9477001{uuid.uuid4().hex[:4]}"
    vol_phone = f"9477002{uuid.uuid4().hex[:4]}"
    donor_id = f"d_test_{uuid.uuid4().hex[:6]}"

    # Setup database records
    database.create_donor_record(donor_id=donor_id, name="Grand Hotel", phone=donor_phone, location="Colombo 3")
    database.create_or_update_user(phone=donor_phone, display_name="Grand Hotel", user_role="donor", onboarding_completed=True)

    tools.register_organization(name="Colombo Care Shelter", location="Colombo 7", service_area="Colombo", accepted_food_types="All", phone=org_phone)
    tools.register_volunteer(name="Ruwan Courier", service_area="Colombo", phone=vol_phone, transport_mode="Motorbike")

    don_raw = tools.create_donation(donor_id=donor_id, food_type="Biryani", quantity=25, location="Colombo 3")
    don = json.loads(don_raw)
    org = database.get_organization_by_phone(org_phone)
    vol = database.get_volunteer_by_phone(vol_phone)
    task_raw = tools.create_pickup_task(donation_id=don["donation_id"], organization_id=org["id"], pickup_location="Colombo 3", delivery_location="Colombo 7")
    task = json.loads(task_raw)
    tools.assign_volunteer(task_id=task["task_id"], volunteer_id=vol["id"])

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        # Volunteer reports delivery completed
        deliv_msg = {"from": vol_phone, "id": "wamid.DelivDone", "type": "text", "text": {"body": "Delivered"}}
        res = await whatsapp_handler.process_incoming_whatsapp_message(deliv_msg)
        assert res["status"] == "processed"

        # Check the distinct messages dispatched to donor and organization
        sent_calls = mock_send.call_args_list
        sent_dict = {call.kwargs.get("to_number"): call.kwargs.get("text") for call in sent_calls}

        donor_msg = sent_dict.get(donor_phone, "")
        org_msg = sent_dict.get(org_phone, "")

        assert "Colombo Care Shelter" in donor_msg
        assert any(w in donor_msg for w in ["delivered", "rescued", "generosity", "භාරදෙන", "வழங்கப்பட்டது"])

        assert "Grand Hotel" in org_msg or any(w in org_msg for w in ["Delivered", "Arrived", "meals", "ලැබිණි", "சேர்ந்தது"])


def test_all_sri_lanka_map_locations_endpoint():
    """Scenario 23: /api/locations correctly handles Sri Lankan hubs outside Colombo (Mawanella, Kandy, Galle)."""
    from fastapi.testclient import TestClient
    from api_routes import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # Register entities in Mawanella and Kandy
    tools.register_organization(name="Mawanella Children Home", location="Mawanella", service_area="Mawanella", accepted_food_types="All", phone="94770000099")
    tools.register_volunteer(name="Kandy Rider", service_area="Kandy", phone="94770000098", transport_mode="Motorbike")

    resp = client.get("/api/locations")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert len(data["markers"]) >= 2

    # Check Mawanella marker
    maw_marker = next((m for m in data["markers"] if "Mawanella Children Home" in m.get("title", "")), None)
    assert maw_marker is not None
    assert abs(maw_marker["latitude"] - 7.2513) < 0.05
    assert abs(maw_marker["longitude"] - 80.4432) < 0.05


