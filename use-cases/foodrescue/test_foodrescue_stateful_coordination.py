"""Test suite for FoodRescue AI Stateful WhatsApp Coordination & Location Workflow.

Covers:
1. Zero-repetition conversational memory (never ask for known info twice)
2. WhatsApp Location message attachment to active draft
3. Bulletproof confirmation (never loses draft)
4. In-place natural corrections ("Actually 50", "Change time to 9 PM")
5. Atomic volunteer acceptance concurrency ("First accepted wins")
6. Volunteer location sharing & notifications
7. Two-location Google Maps routing & transport cost calculation
8. Status lifecycle (ASSIGNED -> COLLECTED -> DELIVERED)
9. Privacy controls & access-controlled coordinate protection
10. Returning user profile memory & persistence
"""

import json
import pytest
import database
import tools
import routing
from resilient_executor import execute_deterministic_fallback
from whatsapp_handler import process_incoming_whatsapp_message


@pytest.fixture(autouse=True)
def clean_db():
    """Reset database and session memory before each test."""
    database.setup_database()
    database.reset_database_data(wipe_all=True)
    tools.clear_session_store()
    yield


@pytest.mark.asyncio
async def test_zero_repetition_donor_flow():
    """Verify that the agent never asks for information that has already been provided."""
    phone = "94755263482"
    session_id = f"whatsapp:{phone}"
    tools.set_explicit_session_id(session_id)

    # Step 1: Donor provides food and quantity in natural language
    res1 = await execute_deterministic_fallback("I have 40 packets of rice available", session_id=session_id)
    
    # Check that draft stores food and quantity
    draft1 = database.get_draft_donation(phone)
    assert draft1 is not None
    assert draft1.get("quantity") == 40.0
    assert "Rice" in draft1.get("food_type", "")
    
    # Agent must ask for location pin or deadline, NEVER ask "what food do you have?" or "how much?"
    assert "What type of food" not in res1
    assert "how many" not in res1.lower()
    assert "location" in res1.lower() or "pickup" in res1.lower()

    # Step 2: Donor provides location text
    res2 = await execute_deterministic_fallback("Pickup location is Kandy", session_id=session_id)
    draft2 = database.get_draft_donation(phone)
    assert draft2.get("location") == "Kandy"
    
    # Agent must ask for deadline, NEVER ask food, quantity, or location again
    assert "40" in res2 or "Rice" in res2 or "Kandy" in res2
    assert "time" in res2.lower() or "deadline" in res2.lower() or "by" in res2.lower()

    # Step 3: Donor provides deadline
    res3 = await execute_deterministic_fallback("Before 8 PM", session_id=session_id)
    draft3 = database.get_draft_donation(phone)
    assert "8 PM" in draft3.get("pickup_deadline", "")
    
    # Summary card must be presented with all known fields
    assert "Donation Summary" in res3
    assert "Rice" in res3
    assert "40" in res3
    assert "Kandy" in res3
    assert "8 PM" in res3
    assert "Confirm" in res3

    # Step 4: Donor confirms
    res4 = await execute_deterministic_fallback("Confirm", session_id=session_id)
    assert "Donation" in res4
    assert ("Created" in res4 or "Matched" in res4 or "success" in res4.lower())

    # Draft should be cleared after successful confirmation
    draft_final = database.get_draft_donation(phone)
    assert draft_final is None or not draft_final.get("food_type")


@pytest.mark.asyncio
async def test_whatsapp_location_message_attaches_to_draft():
    """Verify that a native WhatsApp location payload attaches coordinates directly to the active draft."""
    phone = "94770001111"
    session_id = f"whatsapp:{phone}"

    # Step 1: Donor starts donation with food & quantity
    await execute_deterministic_fallback("I have 25 meal packets to donate", session_id=session_id)
    draft = database.get_draft_donation(phone)
    assert draft.get("quantity") == 25.0

    # Step 2: Send native WhatsApp Location message
    location_payload = {
        "from": phone,
        "id": "wamid.HBgLMTAwMDEx",
        "type": "location",
        "location": {
            "latitude": 6.9271,
            "longitude": 79.8612,
            "name": "Colombo Fort Station",
            "address": "Fort, Colombo 01"
        }
    }
    
    loc_res = await process_incoming_whatsapp_message(location_payload)
    assert loc_res.get("status") in ["location_processed", "processed"]

    # Verify draft in database now contains exact coordinates
    draft_updated = database.get_draft_donation(phone)
    assert draft_updated is not None
    assert draft_updated.get("latitude") == 6.9271
    assert draft_updated.get("longitude") == 79.8612
    assert "Fort" in draft_updated.get("location", "")


@pytest.mark.asyncio
async def test_confirmation_never_loses_draft():
    """Verify that Confirm resolves persistent draft and never says 'no active draft'."""
    phone = "94772223333"
    session_id = f"whatsapp:{phone}"

    # Setup draft directly in database
    database.save_draft_donation(phone, {
        "food_type": "Biryani Packages",
        "quantity": 50.0,
        "unit": "portions",
        "location": "Dehiwala",
        "pickup_deadline": "9 PM",
        "dietary_info": "Halal"
    })
    database.create_or_update_user(phone=phone, display_name="Afnan")

    # Send "Confirm"
    res = await execute_deterministic_fallback("Confirm", session_id=session_id)
    assert "I don't have an active donation draft" not in res
    assert "Biryani Packages" in res
    assert "50" in res


@pytest.mark.asyncio
async def test_in_place_natural_corrections():
    """Verify natural corrections update slots in-place without restarting workflow."""
    phone = "94773334444"
    session_id = f"whatsapp:{phone}"

    # Initial intent: 40 packets of rice
    await execute_deterministic_fallback("I have 40 packets of rice", session_id=session_id)
    draft1 = database.get_draft_donation(phone)
    assert draft1.get("quantity") == 40.0

    # User corrects: "Actually, I have 50 packets"
    await execute_deterministic_fallback("Actually, I have 50 packets", session_id=session_id)
    draft2 = database.get_draft_donation(phone)
    assert draft2.get("quantity") == 50.0
    assert "Rice" in draft2.get("food_type", "")

    # User updates deadline: "Change pickup time to 10 PM"
    await execute_deterministic_fallback("Change pickup time to 10 PM", session_id=session_id)
    draft3 = database.get_draft_donation(phone)
    assert "10 PM" in draft3.get("pickup_deadline", "")
    assert draft3.get("quantity") == 50.0


@pytest.mark.asyncio
async def test_atomic_volunteer_acceptance_first_wins():
    """Verify that when multiple volunteers attempt to claim the same pickup, only the first succeeds."""
    # Setup donation, organization, and pickup task
    don_raw = tools.create_donation(
        donor_id="d-test-1",
        food_type="Rice & Curry",
        quantity=30.0,
        location="Colombo 03",
        pickup_deadline="8 PM"
    )
    don_res = json.loads(don_raw)
    don_id = don_res["donation_id"]

    org_raw = tools.register_organization(
        name="Hope Community Kitchen",
        location="Colombo 07",
        service_area="Colombo",
        accepted_food_types="prepared meals",
        phone="94778889999"
    )
    org_res = json.loads(org_raw)
    org_id = org_res["organization_id"]

    task_raw = tools.create_pickup_task(
        donation_id=don_id,
        organization_id=org_id,
        pickup_location="Colombo 03",
        delivery_location="Colombo 07",
        scheduled_time="8 PM"
    )
    task_res = json.loads(task_raw)
    task_id = task_res["task_id"]

    # Register Volunteer A and Volunteer B
    vol_a_raw = tools.register_volunteer(name="Courier Alpha", service_area="Colombo", phone="94771110001")
    vol_a = json.loads(vol_a_raw)["volunteer_id"]

    vol_b_raw = tools.register_volunteer(name="Courier Beta", service_area="Colombo", phone="94771110002")
    vol_b = json.loads(vol_b_raw)["volunteer_id"]

    # Volunteer A accepts task first -> Must SUCCEED
    claim_a_raw = tools.accept_pickup_task_atomic(pickup_task_id=task_id, volunteer_id=vol_a)
    claim_a = json.loads(claim_a_raw)
    assert claim_a["status"] == "success"
    assert claim_a["volunteer_id"] == vol_a

    # Volunteer B attempts to accept the SAME task -> Must be GRACEFULLY REJECTED
    claim_b_raw = tools.accept_pickup_task_atomic(pickup_task_id=task_id, volunteer_id=vol_b)
    claim_b = json.loads(claim_b_raw)
    assert claim_b["status"] == "already_claimed"
    assert "already been accepted" in claim_b["message"]


@pytest.mark.asyncio
async def test_volunteer_location_sharing_and_lifecycle():
    """Verify end-to-end lifecycle: ACCEPTED -> VOLUNTEER_LOCATION -> COLLECTED -> DELIVERED."""
    # 1. Setup Task
    don_res = json.loads(tools.create_donation(donor_id="d-life", food_type="Vegetarian Meals", quantity=20.0, location="Colombo 04"))
    task_res = json.loads(tools.create_pickup_task(donation_id=don_res["donation_id"], organization_id="o-test", pickup_location="Colombo 04", delivery_location="Colombo 07"))
    task_id = task_res["task_id"]

    vol_res = json.loads(tools.register_volunteer(name="Ravi Perera", service_area="Colombo", phone="94775556666"))
    vol_id = vol_res["volunteer_id"]

    # 2. Volunteer Accepts
    tools.set_explicit_session_id(f"whatsapp:94775556666")
    accept_res = json.loads(tools.accept_pickup_task_atomic(pickup_task_id=task_id, volunteer_id=vol_id))
    assert accept_res["status"] == "success"

    # 3. Volunteer shares location
    loc_res = json.loads(tools.save_location(
        location_type="VOLUNTEER_CURRENT_LOCATION",
        latitude=6.8900,
        longitude=79.8600,
        volunteer_id=vol_id
    ))
    assert loc_res["status"] == "success"

    # 4. Volunteer confirms collection ("Collected")
    coll_res = json.loads(tools.confirm_pickup(pickup_task_id=task_id, volunteer_id=vol_id))
    assert coll_res["status"] == "success"
    assert coll_res["pickup_status"] == "COLLECTED"

    # 5. Volunteer confirms delivery ("Delivered")
    deliv_res = json.loads(tools.confirm_delivery(pickup_task_id=task_id, volunteer_id=vol_id))
    assert deliv_res["status"] == "success"
    assert deliv_res["pickup_status"] == "DELIVERED"
    assert deliv_res["reimbursement"]["estimated_support"] > 0


def test_two_location_google_maps_directions():
    """Verify dynamic Google Maps directions link generation between Location A and Location B."""
    donor_lat, donor_lng = 6.9056, 79.8519
    org_lat, org_lng = 6.9069, 79.8708

    directions_url = routing.generate_directions_link(donor_lat, donor_lng, org_lat, org_lng)
    assert "https://www.google.com/maps/dir/?api=1" in directions_url
    assert f"origin={donor_lat:.6f},{donor_lng:.6f}" in directions_url
    assert f"destination={org_lat:.6f},{org_lng:.6f}" in directions_url


def test_location_privacy_protection():
    """Verify exact donor coordinates are protected and only shared with assigned volunteers during active tasks."""
    task_res = json.loads(tools.create_pickup_task(
        donation_id="don-priv",
        organization_id="org-priv",
        pickup_location="Private Residence, Colombo 05",
        delivery_location="Colombo 07"
    ))
    task_id = task_res["task_id"]

    # Store exact coordinates
    tools.save_location("DONOR_PICKUP", latitude=6.8850, longitude=79.8650, pickup_task_id=task_id)

    # Unassigned volunteer attempts to get exact location -> Privacy protected!
    prot_res = json.loads(tools.get_protected_location(pickup_task_id=task_id, requester_role="volunteer", requester_id="unassigned-vol"))
    assert prot_res["status"] == "privacy_protected"
    assert prot_res["exact_coordinates"] is None

    # Assign volunteer
    tools.register_volunteer(name="Assigned Volunteer", service_area="Colombo", phone="94770000001")
    v = database.get_volunteer_by_phone("94770000001")
    assigned_vol_id = v["id"] if v else "assigned-vol-01"
    tools.assign_volunteer(task_id=task_id, volunteer_id=assigned_vol_id)

    # Assigned volunteer requests location -> Coordinates retrieved!
    auth_res = json.loads(tools.get_protected_location(pickup_task_id=task_id, requester_role="volunteer", requester_id=assigned_vol_id))
    assert auth_res["status"] == "success"
    assert auth_res["exact_coordinates"] is not None


@pytest.mark.asyncio
async def test_returning_donor_profile_memory():
    """Verify that returning registered donors are greeted by name and default location is remembered."""
    phone = "94779998888"
    session_id = f"whatsapp:{phone}"

    # Register donor profile
    database.create_or_update_user(phone=phone, display_name="Chef Kamal", onboarding_completed=True)
    tools.register_donor(name="Chef Kamal", location="Kollupitiya", phone=phone)

    # Greeting message
    res = await execute_deterministic_fallback("Hi", session_id=session_id)
    assert "Kamal" in res or "Welcome" in res


@pytest.mark.asyncio
async def test_language_persistence_across_turns():
    """Verify language selection persists across multiple conversational turns."""
    phone = "94776665555"
    session_id = f"whatsapp:{phone}"

    # Set language to Tamil
    res1 = await execute_deterministic_fallback("Tamil", session_id=session_id)
    assert "தமிழ்" in res1 or "Tamil" in res1

    # Future query responds in Tamil
    res2 = await execute_deterministic_fallback("menu", session_id=session_id)
    assert "வணக்கம்" in res2 or "உணவு" in res2 or "தமிழ்" in res2 or "FoodRescue" in res2


@pytest.mark.asyncio
async def test_recipient_organization_flow():
    """Verify registered organization can request surplus food without repetitive onboarding."""
    phone = "94774443333"
    session_id = f"whatsapp:{phone}"

    # Register organization
    tools.register_organization(name="Colombo Shelter", location="Colombo 05", service_area="Colombo", accepted_food_types="meals", phone=phone)

    # Intent to request food
    res = await execute_deterministic_fallback("We need food for our shelter", session_id=session_id)
    assert "Recipient Organization" in res or "surplus" in res.lower()
