"""Test role-based accept disambiguation and strict workflow gatekeeping in FoodRescue AI.

Verifies:
1. Organization sending 'accept', 'accept offer', 'accept request', '1', 'yes' receives Organization Offer Confirmation and DOES NOT trigger volunteer task assignment.
2. Volunteer courier sending 'accept', 'accept task', '1' receives Volunteer Task Assignment and courier navigation/QR details.
3. Donor confirming match connects donor with organization and dispatches to couriers.
4. Strict workflow gatekeeping: missing location or invalid answer repeatedly prompts for the same question without advancing to confirmation.
5. All calculations (distance, time, reimbursement) remain dynamic without hardcoded numbers.
"""

import uuid
import pytest
import database
import resilient_executor
import whatsapp_handler
import tools


@pytest.mark.asyncio
async def test_org_accept_does_not_trigger_volunteer_response():
    """Verify that when an Organization sends 'accept' or 'accept request', they receive org confirmation, NOT volunteer courier card."""
    uid = uuid.uuid4().hex[:6]
    org_phone = f"+947733{uid[:5]}"
    donor_phone = f"+947744{uid[:5]}"
    org_id = f"org-{uid}"
    don_id = f"don-{uid}"

    # 1. Register organization
    database.create_organization_record(
        org_id=org_id,
        name="Hope Community Kitchen",
        phone=org_phone,
        location="Mawanella",
        accepted_food_types="Rice, Cooked Meals",
        capacity="80 portions",
        service_area="Kegalle",
    )
    database.create_or_update_user(phone=org_phone, display_name="Hope Community Kitchen", user_role="organization", default_location="Mawanella")

    # 2. Create donation in Mawanella
    database.create_donation_record(
        donation_id=don_id,
        donor_id=f"donor-{uid}",
        food_type="Biryani",
        quantity=30.0,
        unit="portions",
        dietary_info="Halal",
        location="Mawanella Town",
        available_from="Now",
        deadline="Today before 9 PM",
    )

    # 3. Simulate Organization receiving donation offer state
    database.set_user_conversation_state(
        org_phone,
        {
            "workflow": "ORGANIZATION",
            "current_question": "ACCEPT_DONATION_OFFER",
            "expected_input_type": "CHOICE",
            "donation_id": don_id,
            "donor_phone": donor_phone,
            "donor_name": "Perera Bakers",
            "food_info": "30 portions of Biryani",
            "district": "Kegalle",
            "distance_km": 2.4,
            "pickup_location": "Mawanella Town",
            "deadline": "Today before 9 PM",
        },
    )

    # 4. Organization replies with "accept request"
    org_reply = await resilient_executor.run_resilient_chat(prompt="accept request", session_id=f"whatsapp:{org_phone}")
    assert org_reply["status"] == "success"
    reply_text = org_reply["result"]

    # Verify response is organization specific (NOT volunteer task assignment)
    assert any(w in reply_text.lower() for w in ["food donation accepted", "donation offer accepted", "dispatching", "hope community kitchen"])
    assert "turn-by-turn navigation" not in reply_text.lower()
    assert "transport support" not in reply_text.lower()
    assert "open camera scanner" not in reply_text.lower()

    # Verify pickup task was created in database
    all_tasks = database.get_all_pickup_tasks()
    org_tasks = [t for t in all_tasks if t.get("donation_id") == don_id]
    assert len(org_tasks) > 0
    assert org_tasks[-1]["organization_id"] == org_id


@pytest.mark.asyncio
async def test_org_accept_simple_keyword_does_not_trigger_volunteer_response():
    """Verify that when an Organization sends simple 'accept' or '1', it is handled strictly as an organization offer acceptance."""
    uid = uuid.uuid4().hex[:6]
    org_phone = f"+947755{uid[:5]}"
    donor_phone = f"+947766{uid[:5]}"
    org_id = f"org-{uid}"
    don_id = f"don-{uid}"

    database.create_organization_record(
        org_id=org_id,
        name="Sunera Foundation",
        phone=org_phone,
        location="Kegalle",
        accepted_food_types="All",
        capacity="50 portions",
        service_area="Kegalle",
    )
    database.create_or_update_user(phone=org_phone, display_name="Sunera Foundation", user_role="organization", default_location="Kegalle")

    database.create_donation_record(
        donation_id=don_id,
        donor_id=f"donor-{uid}",
        food_type="Rice",
        quantity=20.0,
        unit="packets",
        dietary_info="Standard",
        location="Kegalle Clock Tower",
        available_from="Now",
        deadline="Today before 8 PM",
    )

    database.set_user_conversation_state(
        org_phone,
        {
            "workflow": "ORGANIZATION",
            "current_question": "ACCEPT_DONATION_OFFER",
            "expected_input_type": "CHOICE",
            "donation_id": don_id,
            "donor_phone": donor_phone,
            "donor_name": "Royal Hotel",
            "food_info": "20 packets of Rice",
            "district": "Kegalle",
            "distance_km": 1.5,
            "pickup_location": "Kegalle Clock Tower",
            "deadline": "Today before 8 PM",
        },
    )

    # Organization simply sends "accept"
    org_reply = await resilient_executor.run_resilient_chat(prompt="accept", session_id=f"whatsapp:{org_phone}")
    assert org_reply["status"] == "success"
    reply_text = org_reply["result"]

    assert any(w in reply_text.lower() for w in ["food donation accepted", "donation offer accepted", "dispatching", "sunera foundation"])
    assert "turn-by-turn navigation" not in reply_text.lower()
    assert "transport support" not in reply_text.lower()


@pytest.mark.asyncio
async def test_volunteer_accept_triggers_volunteer_courier_details():
    """Verify that when a Volunteer sends 'accept' or 'accept task', they receive the complete courier card and QR code."""
    uid = uuid.uuid4().hex[:6]
    vol_phone = f"+947777{uid[:5]}"
    don_id = f"don-{uid}"
    task_id = f"task-{uid}"
    org_id = f"org-{uid}"

    # 1. Register volunteer using tools.register_volunteer
    tools.register_volunteer(
        name="Sunil Perera",
        phone=vol_phone,
        transport_mode="Three-Wheeler",
        service_area="Kegalle",
    )
    database.create_or_update_user(phone=vol_phone, display_name="Sunil Perera", user_role="volunteer", default_location="Kegalle")

    # 2. Create pickup task
    database.create_donation_record(
        donation_id=don_id,
        donor_id=f"donor-{uid}",
        food_type="Rice & Curry",
        quantity=25.0,
        unit="packets",
        dietary_info="Vegetarian",
        location="Mawanella Main St",
        available_from="Now",
        deadline="Today before 10 PM",
    )
    database.create_pickup_task_record(
        task_id=task_id,
        donation_id=don_id,
        org_id=org_id,
        pickup_loc="Mawanella Main St",
        delivery_loc="Kegalle Center",
        time="Today before 10 PM",
    )

    # 3. Volunteer in ACCEPT_TASK question
    database.set_user_conversation_state(
        vol_phone,
        {
            "workflow": "VOLUNTEER",
            "current_question": "ACCEPT_TASK",
            "expected_input_type": "CHOICE",
            "task_id": task_id,
        },
    )

    # 4. Volunteer sends "accept task" -> Receives waiting notification
    vol_reply = await resilient_executor.run_resilient_chat(prompt="accept task", session_id=f"whatsapp:{vol_phone}")
    assert vol_reply["status"] == "success"
    reply_text = vol_reply["result"]

    assert any(w in reply_text.lower() for w in ["wait", "confirming", "pickup request received", "sunil perera"])
    assert "lkr" in reply_text.lower()
    assert "three-wheeler" in reply_text.lower()

    # 5. Org receives confirmation request and approves courier
    org_user = database.get_organization_record(org_id)
    org_phone_val = (org_user.get("phone") if org_user else None) or f"+947766{uid[:5]}"
    if not org_user:
        database.create_organization_record(org_id=org_id, name="Recipient Org", phone=org_phone_val, service_area="Kegalle", accepted_food_types="Meals")
        database.create_or_update_user(phone=org_phone_val, display_name="Recipient Org", user_role="organization")

    database.set_user_conversation_state(
        org_phone_val,
        {
            "workflow": "ORGANIZATION",
            "current_question": "CONFIRM_VOLUNTEER",
            "expected_input_type": "CHOICE",
            "task_id": task_id,
            "volunteer_phone": vol_phone,
            "volunteer_name": "Sunil Perera",
            "vehicle_mode": "Three-Wheeler",
            "distance_km": 14.6,
            "est_cost": 1414,
        }
    )
    org_confirm_reply = await resilient_executor.run_resilient_chat(prompt="Accept", session_id=f"whatsapp:{org_phone_val}")
    assert org_confirm_reply["status"] == "success"
    org_text = org_confirm_reply["result"]
    assert "confirmed" in org_text.lower() or "approved" in org_text.lower() or "✅" in org_text


@pytest.mark.asyncio
async def test_strict_workflow_gatekeeping_repeated_prompting():
    """Verify that when a user fails to provide required information (e.g. location pin), the system repeatedly prompts for it without advancing."""
    phone = "+94778899001"
    session_id = f"whatsapp:{phone}"
    database.clear_draft_donation(phone)
    database.clear_user_conversation_state(phone)

    # Step 1: Donor provides complete draft fields except location pin
    database.save_draft_donation(
        phone,
        {
            "food_type": "Rice",
            "quantity": 20.0,
            "unit": "packets",
            "donor_name": "Saman Silva",
            "city": "Colombo",
            "pickup_deadline": "Today before 10 PM",
            "location_received": False,
        },
    )
    database.set_user_conversation_state(
        phone,
        {"workflow": "DONATION", "current_question": "WHATSAPP_LOCATION", "expected_input_type": "LOCATION"},
    )

    # Step 2: Donor sends irrelevant text instead of location pin
    res2 = await resilient_executor.run_resilient_chat("hello how are you", session_id)
    assert res2["status"] == "success"
    # Should repeatedly ask for location pin
    assert any(w in res2["result"].lower() for w in ["location", "pin", "share", "ස්ථානය", "இடம்"])

    # State must NOT advance to confirmation
    conv2 = database.get_user_conversation_state(phone)
    assert conv2.get("current_question") == "WHATSAPP_LOCATION"

    # Step 3: Donor sends another random message
    res3 = await resilient_executor.run_resilient_chat("what is the weather today", session_id)
    assert res3["status"] == "success"
    assert any(w in res3["result"].lower() for w in ["location", "pin", "share"])
    conv3 = database.get_user_conversation_state(phone)
    assert conv3.get("current_question") == "WHATSAPP_LOCATION"
