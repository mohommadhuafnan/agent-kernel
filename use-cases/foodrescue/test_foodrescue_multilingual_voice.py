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
    database.setup_database()
    database.seed_test_data()
    # Reset users table for test isolation
    repo = database.get_repository()
    if hasattr(repo, "_get_connection"):
        conn = repo._get_connection()
        with conn:
            conn.execute("DELETE FROM users")
        conn.close()
    elif hasattr(repo, "users_col"):
        repo.users_col.delete_many({})
    yield


# =============================================================================
# 1. NEW USER ONBOARDING & RETURNING USER FLOWS
# =============================================================================

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
        assert "https://foodrescue-ai-ten.vercel.app/" in res["reply"]
        assert "change language" in res["reply"].lower()
        assert "Sinhala" in res["reply"]
        assert "Tamil" in res["reply"]
        assert "Malayalam" in res["reply"]

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
        assert "Language Options / භාෂාව තෝරන්න" not in res["reply"]


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

    # In language menu, numeric selection 4 -> Malayalam
    msg_menu = {"from": phone, "id": "wamid.LangMenuPrompt", "type": "text", "text": {"body": "language"}}
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        await whatsapp_handler.process_incoming_whatsapp_message(msg_menu)

    msg4 = {"from": phone, "id": "wamid.LangMl", "type": "text", "text": {"body": "4"}}
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        res4 = await whatsapp_handler.process_incoming_whatsapp_message(msg4)
        assert res4["status"] == "language_updated"
        assert res4["language"] == "ml"
        assert "മലയാളം" in res4["reply"]


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
    """Scenario 5: Unicode script analysis detects Sinhala, Tamil, Malayalam, and English."""
    # Sinhala
    assert translation_service.detect_language("මට කෑම දානයක් ලබා දෙන්න ඕන") == "si"
    # Tamil
    assert translation_service.detect_language("என்னிடம் அதிகமான உணவு உள்ளது") == "ta"
    # Malayalam
    assert translation_service.detect_language("എനിക്ക് ഭക്ഷണം സംഭാവന ചെയ്യണം") == "ml"
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
        assert "1 - Sinhala" in res["reply"]
        assert "2 - Tamil" in res["reply"]
        assert "3 - English" in res["reply"]
        assert "4 - Malayalam" in res["reply"]


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
# 6. LOCALIZATION TOOLS
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
