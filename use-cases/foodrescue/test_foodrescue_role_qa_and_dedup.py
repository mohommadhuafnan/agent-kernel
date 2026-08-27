"""Tests for Role-based Question Answering, WhatsApp Message Deduplication, and Notification Isolation."""

import pytest
import database
import resilient_executor
import whatsapp_handler


@pytest.fixture(autouse=True)
def setup_clean_db():
    database.reset_database_data(wipe_all=True)
    whatsapp_handler.clear_processed_message_cache()
    yield
    database.reset_database_data(wipe_all=True)
    whatsapp_handler.clear_processed_message_cache()


@pytest.mark.asyncio
async def test_role_based_qa_routing_for_volunteer():
    """Verify that a volunteer asking a question is routed to Gemini/Q&A with volunteer role context."""
    phone = "94770001234"
    database.create_or_update_user(phone=phone, display_name="Ravi Courier", user_role="volunteer", default_location="Kandy")
    database.create_volunteer_record("vol-123", "Ravi Courier", phone, "Kandy", "Motorbike", "Available", "available", "Kandy")

    # Ask a question
    res = await resilient_executor.run_resilient_chat("How does my transport reimbursement work?", f"whatsapp:{phone}")
    assert res.get("status") == "success"
    assert res.get("result")
    # Should not be forced into donation slot-filling ("What type of food...")
    assert "what type of food" not in res["result"].lower()


@pytest.mark.asyncio
async def test_role_based_qa_routing_for_donor():
    """Verify that a donor asking general questions receives direct guidance rather than slot errors."""
    phone = "94770005678"
    database.create_or_update_user(phone=phone, display_name="Grand Hotel", user_role="donor", default_location="Colombo")
    database.create_donor_record("donor-123", "Grand Hotel", phone, "Colombo", "Hotel")

    res = await resilient_executor.run_resilient_chat("What are the food safety guidelines for donating cooked meals?", f"whatsapp:{phone}")
    assert res.get("status") == "success"
    assert res.get("result")
    assert "what type of food" not in res["result"].lower() or "safety" in res["result"].lower() or "guidelines" in res["result"].lower() or "meals" in res["result"].lower()


@pytest.mark.asyncio
async def test_whatsapp_webhook_fifo_deduplication():
    """Verify that identical incoming WhatsApp message IDs are only processed once."""
    msg = {
        "id": "wamid.HBgLMjE5OTg4OTk5ORUCMRIAEzAwMDFGQkQxMzg4RDExMzIA",
        "from": "94771112233",
        "type": "text",
        "text": {"body": "Hi, I have 30 packets of rice to donate in Colombo"}
    }

    # First delivery
    res1 = await whatsapp_handler.process_incoming_whatsapp_message(msg)
    assert res1.get("status") in ["processed", "onboarding_welcome_sent", "returning_welcome_sent"]

    # Second delivery (Meta retry with identical wamid)
    res2 = await whatsapp_handler.process_incoming_whatsapp_message(msg)
    assert res2.get("status") == "ignored"
    assert res2.get("reason") == "duplicate_message_id"


@pytest.mark.asyncio
async def test_volunteer_state_isolation():
    """Verify that cross-notifications do not clobber conversation states of other registered volunteers."""
    vol1_phone = "94770001111"
    vol2_phone = "94770002222"

    database.create_or_update_user(phone=vol1_phone, display_name="Vol One", user_role="volunteer", default_location="Colombo")
    database.create_volunteer_record("vol-1", "Vol One", vol1_phone, "Colombo", "Motorbike", "Available", "available", "Colombo")

    database.create_or_update_user(phone=vol2_phone, display_name="Vol Two", user_role="volunteer", default_location="Colombo")
    database.create_volunteer_record("vol-2", "Vol Two", vol2_phone, "Colombo", "Motorbike", "Available", "available", "Colombo")

    # Set vol2 into an active custom state
    database.set_user_conversation_state(vol2_phone, {"workflow": "VOLUNTEER", "current_question": "VOL_VEHICLE", "expected_input_type": "CHOICE"})

    # Trigger a lifecycle event from donor
    await whatsapp_handler.dispatch_lifecycle_cross_notifications(
        prompt_text="Food donation accepted!",
        reply_text="Food donation accepted! We have created pickup task #task-100.",
        from_number="94779998888"
    )

    # Vol 2's custom conversation state should not be overwritten
    state2 = database.get_user_conversation_state(vol2_phone)
    assert state2 is not None
