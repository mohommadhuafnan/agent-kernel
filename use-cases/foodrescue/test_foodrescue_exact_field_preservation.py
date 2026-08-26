"""Test exact field preservation across all multi-party notifications in FoodRescue AI.

Verifies:
1. Exact food type preservation (e.g. 'Rice' remains 'Rice', never forced to 'Rice & Curry')
2. Exact quantity preservation and clean display (e.g. 15 remains 15, not 15.0, not default 20/30)
3. Exact pickup deadline preservation (e.g. 'at 10', 'before 10 PM', 'by 10' remain 'Today before 10 PM')
4. Exact location preservation (e.g. 'Colombo 03' passed to Org and Volunteer, not default location)
5. Multi-party cross-notification content fidelity (Org offer request and Volunteer task cards)
"""

import pytest
import voice_service
import database
import routing
import resilient_executor
import whatsapp_handler
import translation_service


def test_voice_service_deadline_and_food_extraction():
    """Verify natural time expressions and food types are extracted without mutating to defaults."""
    # 1. Test 'at 10'
    e1 = voice_service.extract_donation_entities("I want to donate 15 packets of Rice in Colombo 03 at 10")
    assert e1["food_type"] == "Rice"
    assert e1["quantity"] == 15.0
    assert e1["unit"] == "packets"
    assert e1["pickup_deadline"] == "Today before 10 PM"
    assert "Colombo" in (e1["city"] or "")

    # 2. Test 'by 10'
    e2 = voice_service.extract_donation_entities("I have 25 portions of Biryani in Kandy by 10")
    assert e2["food_type"] == "Biryani"
    assert e2["quantity"] == 25.0
    assert e2["pickup_deadline"] == "Today before 10 PM"

    # 3. Test 'before 10 PM'
    e3 = voice_service.extract_donation_entities("Donating 40 meal packets of Fried Rice in Galle before 10 PM")
    assert e3["food_type"] == "Fried Rice"
    assert e3["quantity"] == 40.0
    assert e3["pickup_deadline"] == "Today before 10 PM"

    # 4. Test 'at 8:00 AM'
    e4 = voice_service.extract_donation_entities("I have 12 boxes of Bakery & Bread in Negombo at 8:00 AM")
    assert "Bread" in e4["food_type"] or "Bakery" in e4["food_type"]
    assert e4["quantity"] == 12.0
    assert "8:00 AM" in e4["pickup_deadline"]


def test_format_food_info_helper():
    """Verify _format_food_info helper formats cleanly without default values."""
    # Integer quantity formatting
    don1 = {"quantity": 15.0, "unit": "packets", "food_type": "Rice"}
    assert whatsapp_handler._format_food_info(don1) == "15 packets of Rice"
    assert resilient_executor._format_food_info(don1) == "15 packets of Rice"

    # Float quantity preserved if fractional
    don2 = {"quantity": 12.5, "unit": "kg", "food_type": "Fresh Produce"}
    assert whatsapp_handler._format_food_info(don2) == "12.5 kg of Fresh Produce"

    # Specific dishes
    don3 = {"quantity": 50, "unit": "portions", "food_type": "Chicken Biryani"}
    assert whatsapp_handler._format_food_info(don3) == "50 portions of Chicken Biryani"


@pytest.mark.asyncio
async def test_end_to_end_donor_creation_preserves_exact_fields():
    """Test full donor donation creation and verify exact fields in database record."""
    phone = "+94770001122"
    session_id = f"whatsapp:{phone}"
    database.clear_draft_donation(phone)
    database.clear_user_conversation_state(phone)

    # 1. Donor sends donation details
    prompt = "I want to donate 15 packets of Rice in Colombo 03 at 10"
    reply = await resilient_executor.run_resilient_chat(prompt, session_id)
    assert reply["status"] == "success"

    draft = database.get_draft_donation(phone)
    assert draft is not None
    assert draft.get("food_type") == "Rice"
    assert draft.get("quantity") == 15.0
    assert draft.get("unit") == "packets"
    assert "10 PM" in draft.get("pickup_deadline", "")
    assert "Colombo" in draft.get("city", "")

    # 2. Donor provides location pin
    msg_loc = {
        "from": phone,
        "id": "w_loc_1",
        "type": "location",
        "location": {"latitude": 6.9034, "longitude": 79.8540, "name": "Colombo 03", "address": "Galle Rd, Colombo 03"}
    }
    loc_res = await whatsapp_handler.process_incoming_whatsapp_message(msg_loc)
    assert loc_res["status"] == "location_processed"
    # Verification summary should include 15 packets (not 15.0 and not 20/30) and Rice (not Rice & Curry)
    assert "15" in loc_res["reply"]
    assert "Rice" in loc_res["reply"]
    assert "10 PM" in loc_res["reply"]

    # 3. Donor confirms donation
    confirm_res = await resilient_executor.run_resilient_chat("1", session_id)
    assert confirm_res["status"] == "success"
    assert "15" in confirm_res["result"]
    assert "Rice" in confirm_res["result"]

    # Verify donation in database
    donor_rec = database.get_donor_by_phone(phone)
    all_dons = database.get_all_donations()
    if donor_rec:
        donor_dons = [d for d in all_dons if d.get("donor_id") == donor_rec["id"]]
    else:
        donor_dons = [d for d in all_dons if d.get("food_type") == "Rice"]
    assert len(donor_dons) > 0
    latest_don = donor_dons[-1]
    assert latest_don["food_type"] == "Rice"
    assert latest_don["quantity"] == 15.0
    assert "10 PM" in latest_don["pickup_deadline"]


@pytest.mark.asyncio
async def test_org_offer_request_receives_exact_donor_fields():
    """Verify organization offer notification contains exact food, quantity, location, and deadline."""
    import uuid
    uid = uuid.uuid4().hex[:6]
    org_phone = f"+947700{uid[:5]}"
    donor_phone = f"+947711{uid[:5]}"
    org_id = f"org-{uid}"
    don_id = f"don-{uid}"

    database.create_organization_record(
        org_id=org_id,
        name="Colombo Community Center",
        phone=org_phone,
        location="Colombo 03",
        accepted_food_types="Rice, Cooked Meals",
        capacity="100 portions",
        service_area="Colombo"
    )

    don_rec = database.create_donation_record(
        donation_id=don_id,
        donor_id=f"donor-{uid}",
        food_type="Rice",
        quantity=15.0,
        unit="packets",
        dietary_info="Standard",
        location="Kollupitiya, Colombo 03",
        available_from="Now",
        deadline="Today before 10 PM"
    )
    database.create_or_update_user(phone=donor_phone, display_name="Zahira Caterers", user_role="donor")

    # Retrieve context
    don_context = whatsapp_handler._get_donor_donation_context(donor_phone, donation_id=don_id)
    assert don_context is not None
    assert don_context["food_type"] == "Rice"
    assert don_context["quantity"] == 15.0
    assert don_context["pickup_deadline"] == "Today before 10 PM"
    assert don_context["pickup_location"] == "Kollupitiya, Colombo 03"

    food_info = whatsapp_handler._format_food_info(don_context)
    assert food_info == "15 packets of Rice"

    # Render org message
    org_msg = translation_service.get_localized_message(
        "org_donation_offer_request",
        lang="en",
        district="Colombo",
        food_info=food_info,
        donor_name="Zahira Caterers",
        donor_location="Kollupitiya, Colombo 03",
        distance_km=1.2,
        deadline="Today before 10 PM"
    )

    assert "15 packets of Rice" in org_msg
    assert "Kollupitiya, Colombo 03" in org_msg
    assert "Today before 10 PM" in org_msg
    assert "Rice & Curry" not in org_msg
    assert "8:00 AM" not in org_msg
    assert "30 meal packets" not in org_msg


@pytest.mark.asyncio
async def test_volunteer_task_receives_exact_donor_fields():
    """Verify volunteer task card and notification receive exact food, quantity, and deadline."""
    import uuid
    uid = uuid.uuid4().hex[:6]
    don_id = f"don-{uid}"
    task_id = f"task-{uid}"

    database.create_donation_record(
        donation_id=don_id,
        donor_id=f"donor-{uid}",
        food_type="Rice",
        quantity=15.0,
        unit="packets",
        dietary_info="Standard",
        location="Kollupitiya, Colombo 03",
        available_from="Now",
        deadline="Today before 10 PM"
    )

    task = {
        "id": task_id,
        "donation_id": don_id,
        "organization_id": f"org-{uid}",
        "pickup_location": "Kollupitiya, Colombo 03",
        "delivery_location": "Colombo 03",
        "status": "OPEN",
    }
    vol = {
        "id": f"vol-{uid}",
        "name": "Kamal Perera",
        "phone": f"+947722{uid[:5]}",
        "transport_mode": "Motorbike",
        "service_area": "Colombo"
    }

    metrics = resilient_executor._get_task_extended_metrics(task, vol)
    assert metrics["food_info"] == "15 packets of Rice"
    assert metrics["deadline"] == "Today before 10 PM"
    assert "Kollupitiya, Colombo 03" in metrics["pickup_location"]
