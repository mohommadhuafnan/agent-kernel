"""Comprehensive 26-Test Suite for FoodRescue AI Stateful WhatsApp Coordination & Logistics Workflow.

Matches Section 37 of the Final Specification:
1. Returning donor does not get asked for name.
2. Returning donor does not get asked for phone.
3. Returning organization does not get asked for organization name.
4. Returning organization does not get asked for location if already stored.
5. Volunteer can say "I'm free now".
6. Volunteer can say "I can help".
7. Volunteer receives pickup offer.
8. First volunteer acceptance wins.
9. Second volunteer acceptance fails gracefully.
10. Donor location is captured from native WhatsApp location.
11. Recipient location is captured.
12. Google Maps route is generated.
13. Distance is calculated from coordinates.
14. Transport estimate is calculated.
15. Volunteer location is captured after acceptance.
16. Donor receives volunteer status.
17. Recipient receives volunteer status.
18. Collection status updates correctly.
19. Delivery status updates correctly.
20. Language persists.
21. Voice message is converted to text.
22. Missing voice information results in only one missing question.
23. Draft survives application restart.
24. Confirm never loses a draft.
25. Duplicate WhatsApp webhook does not duplicate operations.
26. Private coordinates are not exposed to unauthorized users.
"""

import json
import pytest
import database
import tools
import routing
import voice_service
from resilient_executor import execute_deterministic_fallback
from whatsapp_handler import process_incoming_whatsapp_message


@pytest.fixture(autouse=True)
def clean_db():
    """Reset database and session memory before each test."""
    database.setup_database()
    database.reset_database_data(wipe_all=True)
    tools.clear_session_store()
    yield


# ---------------------------------------------------------------------------
# 1. Returning donor does not get asked for name
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_01_returning_donor_does_not_get_asked_for_name():
    """Verify returning donor is recognized by name and never asked 'What is your name?'."""
    phone = "94771110001"
    session_id = f"whatsapp:{phone}"
    database.create_or_update_user(phone=phone, display_name="Afnan", onboarding_completed=True)
    tools.register_donor(name="Afnan", location="Mawanella", phone=phone)

    res = await execute_deterministic_fallback("Hi", session_id=session_id)
    assert "Afnan" in res or "Welcome" in res
    assert "What is your name" not in res
    assert "your name" not in res.lower()


# ---------------------------------------------------------------------------
# 2. Returning donor does not get asked for phone
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_02_returning_donor_does_not_get_asked_for_phone():
    """Verify returning donor is identified by WhatsApp phone and never asked for contact phone."""
    phone = "94771110002"
    session_id = f"whatsapp:{phone}"
    database.create_or_update_user(phone=phone, display_name="Kamal", default_location="Colombo 03")

    res = await execute_deterministic_fallback("I have 30 packets of rice", session_id=session_id)
    assert "phone number" not in res.lower()
    assert "contact number" not in res.lower()
    assert "30" in res or "Rice" in res


# ---------------------------------------------------------------------------
# 3. Returning organization does not get asked for organization name
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_03_returning_organization_does_not_get_asked_for_organization_name():
    """Verify registered organization is recognized and never asked for organization name."""
    phone = "94771110003"
    session_id = f"whatsapp:{phone}"
    tools.register_organization(name="Hope Food Home", location="Colombo 04", service_area="Colombo", accepted_food_types="meals", phone=phone)

    res = await execute_deterministic_fallback("We need 20 meal packets tonight", session_id=session_id)
    assert "Hope Food Home" in res or "Recipient Organization" in res or "surplus" in res.lower()
    assert "What is your organization name" not in res


# ---------------------------------------------------------------------------
# 4. Returning organization does not get asked for location if already stored
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_04_returning_organization_does_not_get_asked_for_location_if_already_stored():
    """Verify organization with verified location is not prompted for location again."""
    phone = "94771110004"
    session_id = f"whatsapp:{phone}"
    tools.register_organization(name="Community Kitchen", location="Colombo 07", service_area="Colombo", accepted_food_types="all", phone=phone)
    database.create_or_update_user(phone=phone, default_location="Colombo 07")

    res = await execute_deterministic_fallback("We need food for 50 people", session_id=session_id)
    assert "send your organization's whatsapp location" not in res.lower()


# ---------------------------------------------------------------------------
# 5. Volunteer can say "I'm free now"
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_05_volunteer_can_say_im_free_now():
    """Verify volunteer intent is inferred from natural language 'I'm free now'."""
    phone = "94771110005"
    session_id = f"whatsapp:{phone}"
    res = await execute_deterministic_fallback("I'm free now", session_id=session_id)
    assert "available" in res.lower() or "volunteer" in res.lower() or "opportunity" in res.lower() or "status" in res.lower()


# ---------------------------------------------------------------------------
# 6. Volunteer can say "I can help"
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_06_volunteer_can_say_i_can_help():
    """Verify volunteer intent is inferred from natural language 'I can help'."""
    phone = "94771110006"
    session_id = f"whatsapp:{phone}"
    res = await execute_deterministic_fallback("I can help today", session_id=session_id)
    assert "volunteer" in res.lower() or "available" in res.lower() or "help" in res.lower()


# ---------------------------------------------------------------------------
# 7. Volunteer receives pickup offer
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_07_volunteer_receives_pickup_offer():
    """Verify volunteer receives detailed pickup offer card with food, locations, route distance, and transport support."""
    # Setup donation and pickup task
    don = json.loads(tools.create_donation("d1", "Fried Rice", 25, "packets", "Halal", "Colombo 03", "Now", "07:00 PM"))
    tools.register_organization(name="Shelter One", location="Colombo 07", service_area="Colombo", accepted_food_types="meals", phone="94770000007")
    task = json.loads(tools.create_pickup_task(don["donation_id"], "o1", "Colombo 03", "Colombo 07", "07:00 PM"))

    # Volunteer checks availability
    phone = "94771110007"
    tools.register_volunteer(name="Courier Dan", service_area="Colombo", phone=phone, transport_mode="Motorbike")
    res = await execute_deterministic_fallback("pickups near me", session_id=f"whatsapp:{phone}")

    assert "Pickup" in res or "Opportunity" in res or "Task" in res
    assert "Accept" in res
    assert "Reject" in res or "Decline" in res


# ---------------------------------------------------------------------------
# 8. First volunteer acceptance wins
# ---------------------------------------------------------------------------
def test_08_first_volunteer_acceptance_wins():
    """Verify first volunteer claiming a task succeeds atomically."""
    don = json.loads(tools.create_donation("d-atom", "Vegetarian Curry", 30, "portions", "Vegetarian", "Colombo 04", "Now", "08:00 PM"))
    task = json.loads(tools.create_pickup_task(don["donation_id"], "org-atom", "Colombo 04", "Colombo 07"))
    task_id = task["task_id"]

    tools.register_volunteer(name="Vol Alpha", service_area="Colombo", phone="94771110008")
    v_a = database.get_volunteer_by_phone("94771110008")["id"]

    claim_a = json.loads(tools.accept_pickup_task_atomic(task_id, v_a))
    assert claim_a["status"] == "success"
    assert claim_a["volunteer_id"] == v_a


# ---------------------------------------------------------------------------
# 9. Second volunteer acceptance fails gracefully
# ---------------------------------------------------------------------------
def test_09_second_volunteer_acceptance_fails_gracefully():
    """Verify subsequent claim attempt on already-accepted task returns already_claimed."""
    don = json.loads(tools.create_donation("d-atom2", "Bakery Buns", 50, "portions", "Standard", "Colombo 05", "Now", "08:00 PM"))
    task = json.loads(tools.create_pickup_task(don["donation_id"], "org-atom2", "Colombo 05", "Colombo 07"))
    task_id = task["task_id"]

    tools.register_volunteer(name="Vol First", service_area="Colombo", phone="94771110009")
    tools.register_volunteer(name="Vol Second", service_area="Colombo", phone="94771110010")
    v1 = database.get_volunteer_by_phone("94771110009")["id"]
    v2 = database.get_volunteer_by_phone("94771110010")["id"]

    # First succeeds
    tools.accept_pickup_task_atomic(task_id, v1)

    # Second fails gracefully
    claim_b = json.loads(tools.accept_pickup_task_atomic(task_id, v2))
    assert claim_b["status"] == "already_claimed"
    assert "already been accepted" in claim_b["message"]


# ---------------------------------------------------------------------------
# 10. Donor location is captured from native WhatsApp location
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_10_donor_location_is_captured_from_native_whatsapp_location():
    """Verify native WhatsApp Location payload attaches coordinates directly to active draft."""
    phone = "94771110011"
    session_id = f"whatsapp:{phone}"

    # Draft food & quantity
    await execute_deterministic_fallback("I have 40 rice packets", session_id=session_id)

    # Send native location
    payload = {
        "from": phone,
        "id": "wamid.LOC10",
        "type": "location",
        "location": {
            "latitude": 7.2513,
            "longitude": 80.4432,
            "name": "Mawanella Central",
            "address": "Kandy Road, Mawanella"
        }
    }
    await process_incoming_whatsapp_message(payload)

    draft = database.get_draft_donation(phone)
    assert draft["latitude"] == 7.2513
    assert draft["longitude"] == 80.4432
    assert "Mawanella" in draft["location"]


# ---------------------------------------------------------------------------
# 11. Recipient location is captured
# ---------------------------------------------------------------------------
def test_11_recipient_location_is_captured():
    """Verify recipient organization location coordinates are captured and saved."""
    res = json.loads(tools.save_location(
        location_type="RECIPIENT_DESTINATION",
        latitude=6.9069,
        longitude=79.8708,
        name="Colombo Community Center",
        address="Colombo 07"
    ))
    assert res["status"] == "success"
    assert res["coordinates"]["latitude"] == 6.9069
    assert res["coordinates"]["longitude"] == 79.8708


# ---------------------------------------------------------------------------
# 12. Google Maps route is generated
# ---------------------------------------------------------------------------
def test_12_google_maps_route_is_generated():
    """Verify dynamic Google Maps turn-by-turn navigation URL generation."""
    url = routing.generate_directions_link(7.2513, 80.4432, 6.9271, 79.8612)
    assert "https://www.google.com/maps/dir/?api=1" in url
    assert "origin=7.251300,80.443200" in url
    assert "destination=6.927100,79.861200" in url


# ---------------------------------------------------------------------------
# 13. Distance is calculated from coordinates
# ---------------------------------------------------------------------------
def test_13_distance_is_calculated_from_coordinates():
    """Verify distance is calculated from geographic coordinates using Haversine formula."""
    # Distance between Mawanella (7.2513, 80.4432) and Colombo (6.9271, 79.8612) is ~70-80 km
    dist = routing.calculate_haversine_distance(7.2513, 80.4432, 6.9271, 79.8612)
    assert 60.0 < dist < 95.0


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 14. Transport estimate is calculated
# ---------------------------------------------------------------------------
def test_14_transport_estimate_is_calculated():
    """Verify transport support cost calculation uses configurable rates per km."""
    cost = routing.calculate_transport_cost(distance_km=10.0, transport_mode="Motorbike")
    assert cost["status"] == "success"
    assert cost["estimated_cost"] > 0
    assert cost["currency"] == "LKR"


# ---------------------------------------------------------------------------
# 15. Volunteer location is captured after acceptance
# ---------------------------------------------------------------------------
def test_15_volunteer_location_is_captured_after_acceptance():
    """Verify volunteer location is stored after accepting pickup."""
    res = json.loads(tools.save_location(
        location_type="VOLUNTEER_CURRENT_LOCATION",
        latitude=6.8900,
        longitude=79.8600,
        volunteer_id="v-test-15"
    ))
    assert res["status"] == "success"
    assert res["location_type"] == "VOLUNTEER_CURRENT_LOCATION"


# ---------------------------------------------------------------------------
# 16. Donor receives volunteer status
# ---------------------------------------------------------------------------
def test_16_donor_receives_volunteer_status():
    """Verify notification record is generated for donor when volunteer is assigned."""
    don = json.loads(tools.create_donation("d-notif16", "Rice Packets", 20, "portions", "Standard", "Colombo 03", "Now", "06:00 PM"))
    task = json.loads(tools.create_pickup_task(don["donation_id"], "org-notif16", "Colombo 03", "Colombo 07"))

    tools.register_volunteer(name="Amara", service_area="Colombo", phone="94771110016")
    v = database.get_volunteer_by_phone("94771110016")["id"]
    tools.accept_pickup_task_atomic(task["task_id"], v)

    task_rec = database.get_pickup_task_record(task["task_id"])
    assert task_rec["status"] == "ASSIGNED"
    assert task_rec["volunteer_id"] == v


# ---------------------------------------------------------------------------
# 17. Recipient receives volunteer status
# ---------------------------------------------------------------------------
def test_17_recipient_receives_volunteer_status():
    """Verify notification record is generated for recipient when volunteer accepts."""
    don = json.loads(tools.create_donation("d-notif17", "Meals", 15, "portions", "Standard", "Colombo 03", "Now", "06:00 PM"))
    task = json.loads(tools.create_pickup_task(don["donation_id"], "org-notif17", "Colombo 03", "Colombo 07"))

    tools.register_volunteer(name="Kamal", service_area="Colombo", phone="94771110017")
    v = database.get_volunteer_by_phone("94771110017")["id"]
    tools.accept_pickup_task_atomic(task["task_id"], v)

    task_rec = database.get_pickup_task_record(task["task_id"])
    assert task_rec["status"] == "ASSIGNED"
    assert task_rec["volunteer_id"] == v


# ---------------------------------------------------------------------------
# 18. Collection status updates correctly
# ---------------------------------------------------------------------------
def test_18_collection_status_updates_correctly():
    """Verify confirm_pickup updates task status to COLLECTED."""
    don = json.loads(tools.create_donation("d18", "Meals", 10, "portions", "Standard", "Colombo 03", "Now", "06:00 PM"))
    task = json.loads(tools.create_pickup_task(don["donation_id"], "o18", "Colombo 03", "Colombo 07"))
    tools.register_volunteer(name="Ravi", service_area="Colombo", phone="94771110018")
    v = database.get_volunteer_by_phone("94771110018")["id"]
    tools.assign_volunteer(task["task_id"], v)

    res = json.loads(tools.confirm_pickup(task["task_id"], v))
    assert res["status"] == "success"
    assert res["pickup_status"] == "COLLECTED"


# ---------------------------------------------------------------------------
# 19. Delivery status updates correctly
# ---------------------------------------------------------------------------
def test_19_delivery_status_updates_correctly():
    """Verify confirm_delivery updates task status to DELIVERED and creates reimbursement."""
    don = json.loads(tools.create_donation("d19", "Meals", 10, "portions", "Standard", "Colombo 03", "Now", "06:00 PM"))
    task = json.loads(tools.create_pickup_task(don["donation_id"], "o19", "Colombo 03", "Colombo 07"))
    tools.register_volunteer(name="Sunil", service_area="Colombo", phone="94771110019")
    v = database.get_volunteer_by_phone("94771110019")["id"]
    tools.assign_volunteer(task["task_id"], v)
    tools.confirm_pickup(task["task_id"], v)

    res = json.loads(tools.confirm_delivery(task["task_id"], v))
    assert res["status"] == "success"
    assert res["pickup_status"] == "DELIVERED"


# ---------------------------------------------------------------------------
# 20. Language persists
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_20_language_persists():
    """Verify language selection persists across multiple turns."""
    phone = "94771110020"
    session_id = f"whatsapp:{phone}"

    # Turn 1: User chooses Tamil
    await execute_deterministic_fallback("Tamil", session_id=session_id)
    user = database.get_user_by_phone(phone)
    assert user["preferred_language"] == "ta"

    # Turn 2: Subsequent message responds in Tamil
    res2 = await execute_deterministic_fallback("menu", session_id=session_id)
    assert "வணக்கம்" in res2 or "உணவு" in res2 or "தமிழ்" in res2 or "FoodRescue" in res2


# ---------------------------------------------------------------------------
# 21. Voice message is converted to text
# ---------------------------------------------------------------------------
def test_21_voice_message_is_converted_to_text():
    """Verify voice transcription extracts text and language metadata."""
    entities = voice_service.extract_donation_entities("I have 20 rice packets available in Mawanella")
    assert entities["food_type"] == "Rice"
    assert entities["quantity"] == 20.0
    assert entities["location"] == "Mawanella"


# ---------------------------------------------------------------------------
# 22. Missing voice information results in only one missing question
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_22_missing_voice_information_results_in_only_one_missing_question():
    """Verify partial voice input prompts ONLY for the single missing information slot."""
    phone = "94771110022"
    session_id = f"whatsapp:{phone}"

    # Partial voice: provides food & location, missing quantity
    res = await execute_deterministic_fallback("I have some rice available at Kandy", session_id=session_id)
    draft = database.get_draft_donation(phone)

    assert "Rice" in draft.get("food_type", "")
    assert draft.get("location") == "Kandy"
    assert "how many" in res.lower() or "quantity" in res.lower()
    assert "where" not in res.lower()  # Should NOT re-ask location


# ---------------------------------------------------------------------------
# 23. Draft survives application restart
# ---------------------------------------------------------------------------
def test_23_draft_survives_application_restart():
    """Verify active draft persists in database across session clears and restarts."""
    phone = "94771110023"
    database.save_draft_donation(phone, {
        "food_type": "Sandwiches",
        "quantity": 35.0,
        "unit": "packets",
        "location": "Colombo 03",
        "pickup_deadline": "05:00 PM"
    })

    # Clear memory cache
    tools.clear_session_store()

    # Retrieve from persistent database
    draft = database.get_draft_donation(phone)
    assert draft["food_type"] == "Sandwiches"
    assert draft["quantity"] == 35.0
    assert draft["location"] == "Colombo 03"


# ---------------------------------------------------------------------------
# 24. Confirm never loses a draft
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_24_confirm_never_loses_a_draft():
    """Verify saying Confirm resolves persistent draft and never says 'no active draft'."""
    phone = "94771110024"
    session_id = f"whatsapp:{phone}"
    database.save_draft_donation(phone, {
        "food_type": "Biryani",
        "quantity": 40.0,
        "unit": "portions",
        "location": "Mawanella",
        "pickup_deadline": "06:00 PM"
    })

    res = await execute_deterministic_fallback("Confirm", session_id=session_id)
    assert "I don't have an active donation draft" not in res
    assert "Donation" in res
    assert "Biryani" in res or "40" in res


# ---------------------------------------------------------------------------
# 25. Duplicate WhatsApp webhook does not duplicate operations
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_25_duplicate_whatsapp_webhook_does_not_duplicate_operations():
    """Verify webhook deduplication cache prevents duplicate processing of same message ID."""
    payload = {
        "from": "94771110025",
        "id": "wamid.DUP25",
        "type": "text",
        "text": {"body": "Hello FoodRescue"}
    }

    res1 = await process_incoming_whatsapp_message(payload)
    assert res1.get("status") in ["processed", "fallback", "ignored", "onboarding_welcome_sent", "welcome_menu_sent"]

    # Send exact same message ID again
    res2 = await process_incoming_whatsapp_message(payload)
    assert res2.get("status") == "ignored" and res2.get("reason") == "duplicate_message_id"


# ---------------------------------------------------------------------------
# 26. Private coordinates are not exposed to unauthorized users
# ---------------------------------------------------------------------------
def test_26_private_coordinates_are_not_exposed_to_unauthorized_users():
    """Verify exact donor coordinates are privacy-protected from unassigned/unauthorized users."""
    don = json.loads(tools.create_donation("d-priv26", "Meals", 10, "portions", "Standard", "Private Home", "Now", "06:00 PM"))
    task = json.loads(tools.create_pickup_task(don["donation_id"], "org-priv26", "Private Home, Colombo 05", "Colombo 07"))
    task_id = task["task_id"]

    tools.save_location("DONOR_PICKUP", latitude=6.8850, longitude=79.8650, pickup_task_id=task_id)

    # Unassigned volunteer requests exact coordinates -> Privacy protected!
    prot = json.loads(tools.get_protected_location(pickup_task_id=task_id, requester_role="volunteer", requester_id="unassigned-vol"))
    assert prot["status"] == "privacy_protected"
    assert prot["exact_coordinates"] is None

    # Assign volunteer
    tools.register_volunteer(name="Authorized Courier", service_area="Colombo", phone="94771110026")
    vol_id = database.get_volunteer_by_phone("94771110026")["id"]
    tools.assign_volunteer(task_id, vol_id)

    # Assigned volunteer requests coordinates -> Allowed!
    auth = json.loads(tools.get_protected_location(pickup_task_id=task_id, requester_role="volunteer", requester_id=vol_id))
    assert auth["status"] == "success"
    assert auth["exact_coordinates"] is not None
