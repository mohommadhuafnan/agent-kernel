import uuid
import pytest
import database
import whatsapp_handler
import resilient_executor
import tools
import routing


@pytest.mark.asyncio
async def test_donor_single_question_step_by_step_progression():
    """Test User A (Donor) progressing strictly one question at a time without repetition or multi-question bursts."""
    donor_phone = f"94771{uuid.uuid4().hex[:6]}"
    sess_id = f"whatsapp:{donor_phone}"
    tools.set_explicit_session_id(sess_id)
    database.clear_draft_donation(donor_phone)
    database.clear_user_conversation_state(donor_phone)

    # Turn 1: Greeting
    r1 = await resilient_executor.execute_deterministic_fallback("Hi", sess_id)
    assert "Donate surplus food" in r1 or "FoodRescue AI" in r1

    # Turn 2: Select Option 1 (Donate)
    r2 = await resilient_executor.execute_deterministic_fallback("1", sess_id)
    assert "type of food" in r2.lower()

    # Turn 3: User provides Food Type
    r3 = await resilient_executor.execute_deterministic_fallback("Chicken Biryani", sess_id)
    assert "Chicken Biryani" in r3
    assert "how many" in r3.lower() or "quantity" in r3.lower()
    draft = database.get_draft_donation(donor_phone)
    assert draft.get("food_type") == "Chicken Biryani"

    # Turn 4: User provides Quantity & Unit
    r4 = await resilient_executor.execute_deterministic_fallback("30 packets", sess_id)
    assert "name" in r4.lower() or "business" in r4.lower()
    draft = database.get_draft_donation(donor_phone)
    assert draft.get("quantity") == 30.0
    assert draft.get("unit") == "packets"

    # Turn 5: User provides Name
    r5 = await resilient_executor.execute_deterministic_fallback("Afnab", sess_id)
    assert "district" in r5.lower() or "city" in r5.lower()
    draft = database.get_draft_donation(donor_phone)
    assert draft.get("donor_name") == "Afnab"

    # Turn 6: User provides Location / Town
    r6 = await resilient_executor.execute_deterministic_fallback("Mawanella", sess_id)
    assert "location" in r6.lower() or "pin" in r6.lower()
    draft = database.get_draft_donation(donor_phone)
    assert draft.get("city") == "Mawanella"
    assert draft.get("district") == "Kegalle"

    # Turn 7: User sends native WhatsApp Location Pin
    loc_payload = {
        "from": donor_phone,
        "type": "location",
        "location": {"latitude": 7.2515, "longitude": 80.4463, "name": "Mawanella Town"},
    }
    r7 = await whatsapp_handler.process_incoming_whatsapp_message(loc_payload)
    assert r7["status"] in ["success", "location_processed"]
    # Verification: Donation Summary card displayed
    draft = database.get_draft_donation(donor_phone)
    assert draft.get("location_received") is True
    state = database.get_user_conversation_state(donor_phone)
    assert state.get("current_question") == "CONFIRMATION"

    # Turn 8: User confirms donation (1)
    r8 = await resilient_executor.execute_deterministic_fallback("1", sess_id)
    assert "created" in r8.lower() or "confirmed" in r8.lower() or "saved" in r8.lower() or "notified" in r8.lower()
    # Verify donation created in database with exact details
    all_dons = database.get_all_donations()
    donor_dons = [d for d in all_dons if "Afnab" in str(d.get("donor_name")) or "Chicken Biryani" in str(d.get("food_type"))]
    assert len(donor_dons) > 0
    created = donor_dons[-1]
    assert created["food_type"] == "Chicken Biryani"
    assert float(created["quantity"]) == 30.0


@pytest.mark.asyncio
async def test_donor_multi_entity_single_turn_no_reasking():
    """Test that providing multiple details at once extracts all fields and skips already-answered questions."""
    donor_phone = f"94772{uuid.uuid4().hex[:6]}"
    sess_id = f"whatsapp:{donor_phone}"
    tools.set_explicit_session_id(sess_id)
    database.clear_draft_donation(donor_phone)
    database.clear_user_conversation_state(donor_phone)

    # Turn 1: Select 1 (Donate)
    await resilient_executor.execute_deterministic_fallback("1", sess_id)

    # Turn 2: User provides all details in one sentence
    full_msg = "I am Afnab from Mawanella and I have 30 packets of Chicken Biryani"
    r2 = await resilient_executor.execute_deterministic_fallback(full_msg, sess_id)

    draft = database.get_draft_donation(donor_phone)
    assert draft.get("food_type") == "Chicken Biryani"
    assert draft.get("quantity") == 30.0
    assert draft.get("unit") == "packets"
    assert draft.get("donor_name") == "Afnab"
    assert draft.get("city") == "Mawanella"
    assert draft.get("district") == "Kegalle"

    # Should ask strictly for WhatsApp Location Pin, NOT re-asking food, quantity, name, or city!
    assert "location" in r2.lower() or "pin" in r2.lower()
    assert "what is your name" not in r2.lower()
    assert "how many packets" not in r2.lower()


@pytest.mark.asyncio
async def test_recipient_organization_progression():
    """Test Recipient Organization (Role 2) progression."""
    org_phone = f"94773{uuid.uuid4().hex[:6]}"
    sess_id = f"whatsapp:{org_phone}"
    tools.set_explicit_session_id(sess_id)
    database.clear_draft_donation(org_phone)
    database.clear_user_conversation_state(org_phone)

    # Turn 1: User selects 2 (Request Food)
    r1 = await resilient_executor.execute_deterministic_fallback("2", sess_id)
    assert "organization" in r1.lower()
    assert "name" in r1.lower()

    # Turn 2: Organization Name
    r2 = await resilient_executor.execute_deterministic_fallback("Hope Food Home", sess_id)
    assert "district" in r2.lower() or "located" in r2.lower()

    # Turn 3: District
    r3 = await resilient_executor.execute_deterministic_fallback("Kegalle", sess_id)
    assert "capacity" in r3.lower() or "portions" in r3.lower() or "type of food" in r3.lower()

    # Turn 4: Capacity & Food Need
    r4 = await resilient_executor.execute_deterministic_fallback("50 meals of Rice and Curry", sess_id)
    assert "location" in r4.lower() or "registered" in r4.lower() or "pin" in r4.lower()


@pytest.mark.asyncio
async def test_volunteer_courier_progression():
    """Test Volunteer Courier (Role 3) registration and task offering."""
    vol_phone = f"94774{uuid.uuid4().hex[:6]}"
    sess_id = f"whatsapp:{vol_phone}"
    tools.set_explicit_session_id(sess_id)
    database.clear_draft_donation(vol_phone)
    database.clear_user_conversation_state(vol_phone)

    # Turn 1: User selects 3 (Volunteer)
    r1 = await resilient_executor.execute_deterministic_fallback("3", sess_id)
    assert "volunteer" in r1.lower()
    assert "name" in r1.lower()

    # Turn 2: Full Name
    r2 = await resilient_executor.execute_deterministic_fallback("Saman Perera", sess_id)
    assert "vehicle" in r2.lower() or "transport" in r2.lower()

    # Turn 3: Vehicle Mode
    r3 = await resilient_executor.execute_deterministic_fallback("Three-Wheeler", sess_id)
    assert "district" in r3.lower()

    # Turn 4: District
    r4 = await resilient_executor.execute_deterministic_fallback("Kegalle", sess_id)
    assert "location" in r4.lower() or "available" in r4.lower() or "pin" in r4.lower()

    # Turn 5: Native WhatsApp Location Pin
    loc_payload = {
        "from": vol_phone,
        "type": "location",
        "location": {"latitude": 7.2520, "longitude": 80.3450, "name": "Kegalle Clock Tower"},
    }
    r5 = await whatsapp_handler.process_incoming_whatsapp_message(loc_payload)
    assert r5["status"] in ["success", "location_processed"]

    # Verify volunteer record registered
    vol_rec = database.get_volunteer_by_phone(vol_phone)
    assert vol_rec is not None
    assert vol_rec["name"] == "Saman Perera"
    assert vol_rec["transport_mode"] == "Three-Wheeler"


@pytest.mark.asyncio
async def test_interleaved_multi_user_role_isolation():
    """Test that concurrent User A (Donor), User B (Org), and User C (Volunteer) never leak data across sessions."""
    p_donor = f"94775{uuid.uuid4().hex[:6]}"
    p_org = f"94776{uuid.uuid4().hex[:6]}"
    p_vol = f"94777{uuid.uuid4().hex[:6]}"

    s_donor = f"whatsapp:{p_donor}"
    s_org = f"whatsapp:{p_org}"
    s_vol = f"whatsapp:{p_vol}"

    for p in [p_donor, p_org, p_vol]:
        database.clear_draft_donation(p)
        database.clear_user_conversation_state(p)

    # Interleaved Turn 1:
    await resilient_executor.execute_deterministic_fallback("1", s_donor)
    await resilient_executor.execute_deterministic_fallback("2", s_org)
    await resilient_executor.execute_deterministic_fallback("3", s_vol)

    # Interleaved Turn 2:
    r_d2 = await resilient_executor.execute_deterministic_fallback("45 boxes of Mutton Kottu", s_donor)
    r_o2 = await resilient_executor.execute_deterministic_fallback("Care Foundation Shelter", s_org)
    r_v2 = await resilient_executor.execute_deterministic_fallback("Kamal Bandara", s_vol)

    # Validate User A's state
    d_draft = database.get_draft_donation(p_donor)
    assert d_draft.get("food_type") == "Mutton Kottu"
    assert d_draft.get("quantity") == 45.0
    assert "Care Foundation" not in str(d_draft)
    assert "Kamal Bandara" not in str(d_draft)

    # Validate User B's state
    o_state = database.get_user_conversation_state(p_org)
    assert o_state.get("org_name") == "Care Foundation Shelter" or "Care Foundation" in str(o_state)
    assert "Mutton Kottu" not in str(o_state)
    assert "Kamal Bandara" not in str(o_state)

    # Validate User C's state
    v_state = database.get_user_conversation_state(p_vol)
    assert v_state.get("vol_name") == "Kamal Bandara" or "Kamal Bandara" in str(v_state)
    assert "Mutton Kottu" not in str(v_state)
    assert "Care Foundation" not in str(v_state)
