"""Test suite for WhatsApp Self-Service Data Management & In-Workflow Q&A Resumption."""

import uuid
import pytest
from unittest.mock import patch, AsyncMock
import database
import resilient_executor
import tools


@pytest.mark.asyncio
async def test_self_service_delete_organization():
    """Test user deleting their organization profile directly via WhatsApp message."""
    import random

    phone = f"9477{random.randint(1000000, 9999999)}"
    sess_id = f"whatsapp:{phone}"
    tools.set_explicit_session_id(sess_id)

    # Register an organization
    database.create_or_update_user(phone=phone, display_name="Hope Shelter", user_role="organization", default_location="Kegalle")
    tools.register_organization(
        name="Hope Shelter",
        phone=phone,
        service_area="Kegalle",
        accepted_food_types="Cooked Meals",
        capacity="100 meals",
        location="Kegalle Town",
    )

    # Verify registered
    assert database.get_organization_by_phone(phone) is not None

    # Send delete command
    reply = await resilient_executor.execute_deterministic_fallback("delete organization", sess_id)
    assert "Removed Successfully" in reply or "deleted" in reply.lower()

    # Verify organization removed and user role reset
    assert database.get_organization_by_phone(phone) is None
    user = database.get_user_by_phone(phone)
    assert user.get("user_role") == "unknown"


@pytest.mark.asyncio
async def test_self_service_delete_volunteer():
    """Test volunteer deleting their courier profile via WhatsApp command."""
    import random

    phone = f"9477{random.randint(1000000, 9999999)}"
    sess_id = f"whatsapp:{phone}"
    tools.set_explicit_session_id(sess_id)

    # Register a volunteer
    database.create_or_update_user(phone=phone, display_name="Kasun Silva", user_role="volunteer", default_location="Kandy")
    tools.register_volunteer(name="Kasun Silva", phone=phone, service_area="Kandy", transport_mode="Three-Wheeler")

    assert database.get_volunteer_by_phone(phone) is not None

    # Send delete volunteer command
    reply = await resilient_executor.execute_deterministic_fallback("remove my volunteer", sess_id)
    assert "Volunteer Courier Profile Removed" in reply or "removed" in reply.lower()

    assert database.get_volunteer_by_phone(phone) is None
    user = database.get_user_by_phone(phone)
    assert user.get("user_role") == "unknown"


@pytest.mark.asyncio
async def test_self_service_cancel_active_donation():
    """Test donor cancelling an active donation draft and record via WhatsApp."""
    import random

    phone = f"9477{random.randint(1000000, 9999999)}"
    sess_id = f"whatsapp:{phone}"
    tools.set_explicit_session_id(sess_id)

    # Seed draft
    database.save_draft_donation(phone, {"food_type": "Biryani", "quantity": 50, "unit": "packets", "city": "Colombo 03"})
    database.set_user_conversation_state(phone, {"workflow": "DONATION", "current_question": "CONFIRMATION"})

    # Send cancel donation command
    reply = await resilient_executor.execute_deterministic_fallback("cancel donation", sess_id)
    assert "Donation Cancelled" in reply or "cancelled" in reply.lower()

    # Verify draft and state cleared
    draft = database.get_draft_donation(phone)
    assert not draft or not draft.get("food_type")
    state = database.get_user_conversation_state(phone)
    assert not state or not state.get("current_question")


@pytest.mark.asyncio
async def test_self_service_reset_all_account_data():
    """Test user resetting all their data via 'delete my profile'."""
    import random

    phone = f"9477{random.randint(1000000, 9999999)}"
    sess_id = f"whatsapp:{phone}"
    tools.set_explicit_session_id(sess_id)

    database.create_or_update_user(phone=phone, display_name="Test User", user_role="donor")
    tools.register_donor(name="Test User", phone=phone, location="Colombo")

    reply = await resilient_executor.execute_deterministic_fallback("delete my profile", sess_id)
    assert "Account Data Reset Successfully" in reply or "cleared" in reply.lower()

    assert database.get_user_by_phone(phone) is None
    assert database.get_donor_by_phone(phone) is None


@pytest.mark.asyncio
async def test_in_workflow_qa_resumption():
    """Test that asking a question in the middle of registration gets answered with role context and appends a step reminder."""
    import random

    phone = f"9477{random.randint(1000000, 9999999)}"
    sess_id = f"whatsapp:{phone}"
    tools.set_explicit_session_id(sess_id)

    # User is in the middle of volunteer registration awaiting name
    database.set_user_conversation_state(
        phone,
        {
            "workflow": "VOLUNTEER_REGISTRATION",
            "current_question": "VOL_NAME",
            "expected_input_type": "VOL_NAME",
        },
    )

    # Mock chat service to return simulated Gemini answer
    mock_chat_response = {"result": "FoodRescue AI volunteers provide crucial transport for surplus meals. Fuel support is reimbursed per kilometer."}
    with patch("resilient_executor.ChatService.process_async_chat_request", new_callable=AsyncMock) as mock_agent:
        mock_agent.return_value = mock_chat_response

        res = await resilient_executor.run_resilient_chat(prompt="Do you provide fuel reimbursement?", session_id=sess_id)

        reply_text = res.get("result", "")
        # Should contain the answer
        assert "fuel" in reply_text.lower() or "reimbursed" in reply_text.lower()
        # Should contain the resumption prompt
        assert "Full Name" in reply_text or "continue your volunteer courier registration" in reply_text.lower()

        # State should still be preserved
        state = database.get_user_conversation_state(phone)
        assert state.get("current_question") == "VOL_NAME"
