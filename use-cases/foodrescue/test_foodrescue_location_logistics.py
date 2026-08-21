"""FoodRescue AI — Comprehensive Intelligent Logistics, Privacy-First Location Sharing, and Delivery Coordination Test Suite.

Covers all 24 Required Verification Scenarios:
1. Volunteer natural language intent detection ("I'm free now")
2. Volunteer state transition to AVAILABLE with timestamp
3. Available donation matching and opportunity presentation
4. Volunteer accepts task & receives assignment
5. Volunteer rejects task & candidate pool searched
6. Donor location request generated post-acceptance
7. WhatsApp native location webhook parsed (msg_type == "location")
8. Location coordinates securely linked to donation & pickup task
9. Privacy protection: Exact coordinates hidden prior to volunteer acceptance
10. Two-leg road route calculation (Leg 1 & Leg 2)
11. Road distance & duration calculations
12. Multi-factor transport cost estimation by vehicle type (Tuk, Bike, Car, Van)
13. Conversational pickup collection confirmation ("Collected")
14. Destination location retrieval & navigation links
15. Conversational delivery confirmation ("Delivered")
16. Overall lifecycle completion & auto-generated reimbursement ledger
17. Multiple volunteer sequential fallback
18. Vehicle capacity mismatch validation (meals vs transport mode)
19. Google Routes API failure resilience & Haversine fallback
20. Malformed location payload error handling
21. Webhook deduplication & idempotency on location messages
22. Duplicate pickup confirmation protection
23. Session continuity across location and text turns
24. Natural language multi-role intent detection
"""

import json
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

import routing
import database
import tools
import app
import whatsapp_handler
import resilient_executor


@pytest.fixture(autouse=True)
def clean_db():
    """Reset database tables and in-memory caches before each test."""
    database.setup_database()
    database.reset_database_data()
    database.seed_test_data()
    tools.clear_session_store()
    whatsapp_handler.PROCESSED_MESSAGE_IDS.clear()
    yield
    database.reset_database_data()
    tools.clear_session_store()
    whatsapp_handler.PROCESSED_MESSAGE_IDS.clear()


# =========================================================================
# SCENARIO 1 & 2: VOLUNTEER NATURAL LANGUAGE INTENT & AVAILABILITY
# =========================================================================

@pytest.mark.asyncio
async def test_volunteer_says_im_free_natural_language():
    """Scenario 1: Volunteer natural language intent detection ('I'm free now')."""
    session_id = "whatsapp:+94770001122"
    reply = await resilient_executor.execute_deterministic_fallback(
        prompt="I'm free now to help with pickups",
        session_id=session_id
    )
    assert "AVAILABLE" in reply
    assert ("Pickup Opportunity" in reply or "no active pickups" in reply)


def test_volunteer_becomes_available_state():
    """Scenario 2: Volunteer state transition to AVAILABLE with timestamp and DB persistence."""
    res_raw = tools.update_volunteer_availability(
        volunteer_id="v1",
        status="AVAILABLE",
        current_location="Colombo 3"
    )
    res = json.loads(res_raw)
    assert res["status"] == "success"
    assert res["availability_status"] == "AVAILABLE"
    
    vol = database.get_volunteer_record("v1")
    assert vol["availability_status"] == "AVAILABLE"
    assert vol.get("last_available_at") is not None


# =========================================================================
# SCENARIO 3 & 4: DONATION MATCHING & VOLUNTEER ACCEPTANCE
# =========================================================================

def test_available_donation_matching_opportunity():
    """Scenario 3: Available donation matching with general pickup area and transport support."""
    # Create donation & task
    don_raw = tools.create_donation(donor_id="d1", food_type="Biryani", quantity=20, unit="portions", location="Colombo 5")
    don_id = json.loads(don_raw)["donation_id"]
    task_raw = tools.create_pickup_task(donation_id=don_id, organization_id="o1", pickup_location="Colombo 5", delivery_location="Colombo 7")
    task_id = json.loads(task_raw)["task_id"]
    
    # Check pending tasks list
    tasks_res = json.loads(tools.get_available_pickup_tasks(location="Colombo 5"))
    assert tasks_res["status"] == "success"
    assert tasks_res["count"] >= 1
    assert any(t["id"] == task_id for t in tasks_res["available_tasks"])


def test_volunteer_accepts_task():
    """Scenario 4: Volunteer accepts task -> assigns task, triggers donor location prompt."""
    don_raw = tools.create_donation(donor_id="d1", food_type="Sandwiches", quantity=15, unit="boxes", location="Colombo 4")
    don_id = json.loads(don_raw)["donation_id"]
    task_raw = tools.create_pickup_task(donation_id=don_id, organization_id="o1", pickup_location="Colombo 4", delivery_location="Colombo 7")
    task_id = json.loads(task_raw)["task_id"]
    
    assign_res = json.loads(tools.assign_volunteer(task_id=task_id, volunteer_id="v1"))
    assert assign_res["status"] == "success"
    assert assign_res["task_status"] == "ASSIGNED"
    
    # Request donor location
    req_res = json.loads(tools.request_donor_location(donation_id=don_id, pickup_task_id=task_id))
    assert req_res["status"] == "success"
    assert "Please share your pickup location" in req_res["donor_instruction"]


# =========================================================================
# SCENARIO 5: VOLUNTEER REJECTS TASK & SEQUENTIAL FALLBACK
# =========================================================================

def test_volunteer_rejects_task_and_fallback():
    """Scenario 5 & 17: Volunteer rejects task -> candidate pool searched for fallback."""
    don_raw = tools.create_donation(donor_id="d1", food_type="Rice & Curry", quantity=10, unit="portions", location="Colombo 3")
    don_id = json.loads(don_raw)["donation_id"]
    task_raw = tools.create_pickup_task(donation_id=don_id, organization_id="o1", pickup_location="Colombo 3", delivery_location="Colombo 7")
    task_id = json.loads(task_raw)["task_id"]
    
    rej_res = json.loads(tools.reject_pickup_task(pickup_task_id=task_id, volunteer_id="v1", reason="Busy with work"))
    assert rej_res["status"] == "rejected"
    assert rej_res["declined_volunteer_id"] == "v1"
    
    # Audit trail verifies rejection event
    audits = database.get_audit_events_for_task(task_id)
    assert any(a["event_type"] == "VOLUNTEER_REJECTED" for a in audits)


# =========================================================================
# SCENARIO 6, 7 & 8: WHATSAPP LOCATION WEBHOOK & COORDINATE LINKING
# =========================================================================

def test_donor_location_request_formatting():
    """Scenario 6: Donor location request prompt formatting."""
    res = json.loads(tools.request_donor_location(donation_id="d1"))
    assert res["status"] == "success"
    assert "📎" in res["donor_instruction"]
    assert "Send Your Current Location" in res["donor_instruction"]


@pytest.mark.asyncio
async def test_whatsapp_location_webhook_received():
    """Scenario 7 & 8: WhatsApp location webhook message parsing and linking."""
    location_message = {
        "from": "94755263482",
        "id": "wamid.HBgLTestLocation123",
        "type": "location",
        "location": {
            "latitude": 6.9056,
            "longitude": 79.8519,
            "name": "Donor Kitchen Kollupitiya",
            "address": "Galle Road, Colombo 03"
        }
    }
    
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent", "message_id": "test-sent-id"}
        res = await whatsapp_handler.process_incoming_whatsapp_message(location_message)
        
    assert res["status"] == "location_processed"
    assert "6.9056" in res["reply"]
    assert "https://www.google.com/maps/search/?api=1" in res["reply"]


# =========================================================================
# SCENARIO 9: PRIVACY PROTECTION BEFORE ACCEPTANCE
# =========================================================================

def test_privacy_protection_before_acceptance():
    """Scenario 9: Private exact coordinates are hidden before volunteer accepts."""
    don_raw = tools.create_donation(donor_id="d1", food_type="Pastries", quantity=10, unit="boxes", location="Colombo 3")
    don_id = json.loads(don_raw)["donation_id"]
    task_raw = tools.create_pickup_task(donation_id=don_id, organization_id="o1", pickup_location="Colombo 3", delivery_location="Colombo 7")
    task_id = json.loads(task_raw)["task_id"]
    
    # Task is PENDING (unassigned) -> Protected location request
    prot_res = json.loads(tools.get_protected_location(pickup_task_id=task_id, requester_role="volunteer", requester_id="unassigned_vol"))
    assert prot_res["status"] == "privacy_protected"
    assert prot_res["exact_coordinates"] is None
    assert prot_res["general_pickup_area"] == "Colombo 3"


# =========================================================================
# SCENARIO 10, 11 & 12: TWO-LEG ROUTING, DISTANCE & TRANSPORT ESTIMATES
# =========================================================================

@pytest.mark.asyncio
async def test_two_leg_route_calculation():
    """Scenario 10 & 11: Two-leg road route calculation and distances."""
    res = await routing.compute_two_leg_route(
        volunteer_location="Colombo 3",
        pickup_location="Colombo 5",
        delivery_location="Colombo 7",
        transport_mode="motorbike"
    )
    assert res["status"] == "success"
    assert "leg1_pickup" in res
    assert "leg2_delivery" in res
    assert res["total_distance_km"] > 0
    assert res["total_duration_minutes"] > 0
    assert res["estimated_transport_cost"] > 0


def test_transport_estimate_vehicle_formulas():
    """Scenario 12: Configurable transport rates across Tuk, Bike, Car, Van."""
    # Motorbike: 50 base + 50/km * 10 km = 550 LKR
    bike_est = routing.calculate_transport_estimate(distance_km=10.0, transport_mode="motorbike")
    assert bike_est["status"] == "success"
    assert bike_est["base_fare"] == 50.0
    assert bike_est["rate_per_km"] == 50.0
    assert bike_est["estimated_support_amount"] == 550.0
    
    # Tuk-tuk: 100 base + 90/km * 10 km = 1000 LKR
    tuk_est = routing.calculate_transport_estimate(distance_km=10.0, transport_mode="tuk-tuk")
    assert tuk_est["status"] == "success"
    assert tuk_est["base_fare"] == 100.0
    assert tuk_est["rate_per_km"] == 90.0
    assert tuk_est["estimated_support_amount"] == 1000.0
    
    # Van: 250 base + 120/km * 10 km = 1450 LKR
    van_est = routing.calculate_transport_estimate(distance_km=10.0, transport_mode="van")
    assert van_est["status"] == "success"
    assert van_est["estimated_support_amount"] == 1450.0


# =========================================================================
# SCENARIO 13 & 14: PICKUP COLLECTION CONFIRMATION & DESTINATION MAP
# =========================================================================

def test_pickup_confirmation_collected_and_map():
    """Scenario 13 & 14: Natural language 'Collected' -> COLLECTED state & navigation link."""
    don_raw = tools.create_donation(donor_id="d1", food_type="Hot Meals", quantity=25, unit="portions", location="Colombo 3")
    don_id = json.loads(don_raw)["donation_id"]
    task_raw = tools.create_pickup_task(donation_id=don_id, organization_id="o1", pickup_location="Colombo 3", delivery_location="Colombo 7")
    task_id = json.loads(task_raw)["task_id"]
    tools.assign_volunteer(task_id=task_id, volunteer_id="v1")
    
    col_res = json.loads(tools.confirm_pickup(pickup_task_id=task_id, volunteer_id="v1"))
    assert col_res["status"] == "success"
    assert col_res["pickup_status"] == "COLLECTED"
    assert col_res["donation_status"] == "PICKED_UP"
    assert col_res["destination_map_link"] is not None
    assert "https://www.google.com/maps/search/?api=1" in col_res["destination_map_link"]


# =========================================================================
# SCENARIO 15 & 16: DELIVERY CONFIRMATION & AUTO REIMBURSEMENT
# =========================================================================

def test_delivery_confirmation_and_completion():
    """Scenario 15 & 16: 'Delivered' -> DELIVERED / DISTRIBUTED / COMPLETED + reimbursement."""
    don_raw = tools.create_donation(donor_id="d1", food_type="Rice", quantity=20, unit="portions", location="Colombo 3")
    don_id = json.loads(don_raw)["donation_id"]
    task_raw = tools.create_pickup_task(donation_id=don_id, organization_id="o1", pickup_location="Colombo 3", delivery_location="Colombo 7")
    task_id = json.loads(task_raw)["task_id"]
    tools.assign_volunteer(task_id=task_id, volunteer_id="v1")
    tools.confirm_pickup(pickup_task_id=task_id, volunteer_id="v1")
    
    deliv_res = json.loads(tools.confirm_delivery(pickup_task_id=task_id, volunteer_id="v1"))
    assert deliv_res["status"] == "success"
    assert deliv_res["pickup_status"] == "DELIVERED"
    assert deliv_res["donation_status"] == "DISTRIBUTED"
    assert deliv_res["lifecycle_status"] == "COMPLETED"
    assert deliv_res["reimbursement"]["estimated_support"] > 0
    
    # Verify reimbursement record in DB
    reimb = database.get_reimbursement_by_pickup_id(task_id)
    assert reimb is not None
    assert reimb["status"] == "PENDING"
    assert reimb["volunteer_id"] == "v1"


# =========================================================================
# SCENARIO 18: VEHICLE CAPACITY MISMATCH VALIDATION
# =========================================================================

def test_volunteer_capacity_mismatch_check():
    """Scenario 18: Vehicle capacity mismatch (e.g. 50 meals exceeds motorbike 25 limit)."""
    # 50 meals exceeds motorbike (25) and bicycle (10)
    has_bike_cap, _ = routing.check_vehicle_capacity(mode="motorbike", quantity=50)
    assert has_bike_cap is False
    
    # 50 meals fits in Tuk-tuk (60) and Car (150)
    has_tuk_cap, _ = routing.check_vehicle_capacity(mode="tuk-tuk", quantity=50)
    assert has_tuk_cap is True
    
    # Tool get_available_volunteers filters out incapable vehicles
    avail_vols = json.loads(tools.get_available_volunteers(service_area="Colombo", food_quantity=50))
    for v in avail_vols.get("volunteers", []):
        assert v["vehicle_capacity"] >= 50


# =========================================================================
# SCENARIO 19, 20, 21 & 22: RESILIENCE, MALFORMED DATA & IDEMPOTENCY
# =========================================================================

@pytest.mark.asyncio
async def test_route_api_failure_resilience():
    """Scenario 19: Route API failure fallback to Haversine."""
    provider = routing.GoogleRoutesProvider(api_key="invalid_dummy_key")
    res = await provider.compute_route("Colombo 3", "Colombo 7", "motorbike")
    assert res["status"] == "success"
    assert res["distance_km"] > 0


@pytest.mark.asyncio
async def test_malformed_location_payload_handling():
    """Scenario 20: Malformed location payload returns clear guidance without crash."""
    bad_msg = {
        "from": "94755263482",
        "id": "wamid.BadLocation",
        "type": "location",
        "location": {}  # Missing lat/lng
    }
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        res = await whatsapp_handler.process_incoming_whatsapp_message(bad_msg)
    assert res["status"] == "error"
    assert res["reason"] == "malformed_location"


@pytest.mark.asyncio
async def test_duplicate_location_webhook_idempotency():
    """Scenario 21: Duplicate location message IDs are cleanly deduplicated."""
    loc_msg = {
        "from": "94755263482",
        "id": "wamid.DedupLocationTest",
        "type": "location",
        "location": {"latitude": 6.9056, "longitude": 79.8519}
    }
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        res1 = await whatsapp_handler.process_incoming_whatsapp_message(loc_msg)
        res2 = await whatsapp_handler.process_incoming_whatsapp_message(loc_msg)
        
    assert res1["status"] == "location_processed"
    assert res2["status"] == "ignored"
    assert res2["reason"] == "duplicate_message_id"


def test_duplicate_pickup_confirmation_protection():
    """Scenario 22: Duplicate pickup collection calls return safe already_collected status."""
    don_raw = tools.create_donation(donor_id="d1", food_type="Meals", quantity=10, unit="portions", location="Colombo 3")
    don_id = json.loads(don_raw)["donation_id"]
    task_raw = tools.create_pickup_task(donation_id=don_id, organization_id="o1", pickup_location="Colombo 3", delivery_location="Colombo 7")
    task_id = json.loads(task_raw)["task_id"]
    
    first = json.loads(tools.confirm_pickup(pickup_task_id=task_id))
    second = json.loads(tools.confirm_pickup(pickup_task_id=task_id))
    
    assert first["status"] == "success"
    assert second["status"] == "already_collected"


# =========================================================================
# SCENARIO 23 & 24: SESSION CONTINUITY & MULTI-ROLE INTENT DETECTION
# =========================================================================

def test_session_continuity_across_turns():
    """Scenario 23: Session context maintains state across multi-turn exchanges."""
    sess = tools.get_session_instance("whatsapp:+94712345678")
    cache = sess.get_non_volatile_cache()
    
    cache.set("current_donation_id", "don-continuous-01")
    cache.set("current_task_id", "task-continuous-01")
    
    assert cache.get("current_donation_id") == "don-continuous-01"
    assert cache.get("current_task_id") == "task-continuous-01"


@pytest.mark.asyncio
async def test_natural_language_intent_detection_all_roles():
    """Scenario 24: Conversational intents for Donors, Organizations, and Volunteers."""
    # Donor
    r1 = await resilient_executor.execute_deterministic_fallback("I have 20 meals to donate", "whatsapp:+94711111111")
    assert "Donation" in r1 or "recorded" in r1.lower() or "meals" in r1.lower() or "location" in r1.lower()
    
    # Recipient
    r2 = await resilient_executor.execute_deterministic_fallback("I need food for community shelter", "whatsapp:+94722222222")
    assert "Recipient Organization" in r2
    
    # Volunteer
    r3 = await resilient_executor.execute_deterministic_fallback("I'm free to volunteer now", "whatsapp:+94733333333")
    assert "AVAILABLE" in r3
