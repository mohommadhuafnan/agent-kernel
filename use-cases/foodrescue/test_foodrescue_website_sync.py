"""
FoodRescue AI — Comprehensive Website UI, Dashboard & WhatsApp Data Synchronization Test Suite.
Tests API routes, database parity, WhatsApp chat synchronization, live pipeline metrics,
and settings configuration.
"""

import os
import sys
import json
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database
from api_routes import router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Reset database and seed initial test data before each test."""
    database.reset_database_data()
    database.seed_test_data()
    yield


def test_dashboard_stats_endpoint():
    """Verify /api/dashboard returns complete aggregated KPIs, impact metrics, and recent activity."""
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    stats = data["stats"]
    assert "total_donations" in stats
    assert "total_food_quantity" in stats
    assert "meals_rescued" in stats
    assert "food_rescued_kg" in stats
    assert "co2_saved_kg" in stats
    assert "available_donations" in stats
    assert "active_pickups" in stats
    assert "available_volunteers" in stats
    assert "registered_organizations" in stats
    assert "active_users" in stats
    assert "recent_activity" in stats


def test_users_and_persistent_profiles():
    """Verify /api/users returns registered WhatsApp users with roles and language preferences."""
    # Create persistent users
    database.set_user_language("+94770001111", "si")
    database.set_user_response_mode("+94770001111", "voice")
    database.set_onboarding_completed("+94770001111", True)

    database.set_user_language("+94770002222", "ta")
    database.set_user_response_mode("+94770002222", "text")

    response = client.get("/api/users")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["count"] >= 2
    users = {u["phone_number"]: u for u in data["users"]}
    
    # Check normalized phone numbers
    norm_phone = "94770001111"
    assert norm_phone in users
    assert users[norm_phone]["preferred_language"] == "si"
    assert users[norm_phone]["preferred_response_mode"] == "voice"
    assert users[norm_phone]["onboarding_completed"] is True


def test_donors_and_organizations_endpoints():
    """Verify /api/donors and /api/organizations endpoints return seeded data."""
    don_res = client.get("/api/donors")
    assert don_res.status_code == 200
    assert don_res.json()["count"] >= 2

    org_res = client.get("/api/organizations")
    assert org_res.status_code == 200
    assert org_res.json()["count"] >= 2


def test_volunteers_crud_endpoints():
    """Verify /api/volunteers listing and courier creation."""
    # List volunteers
    v_res = client.get("/api/volunteers")
    assert v_res.status_code == 200
    assert v_res.json()["count"] >= 2

    # Create new courier
    post_res = client.post("/api/volunteers", json={
        "name": "Nimal Jayasinghe",
        "phone": "+94773344556",
        "service_area": "Colombo, Kotte",
        "transport_mode": "Motorbike"
    })
    assert post_res.status_code == 200
    assert post_res.json()["status"] == "success"

    # Verify courier is present
    v_res2 = client.get("/api/volunteers")
    phones = [v["phone"] for v in v_res2.json()["volunteers"]]
    assert "+94773344556" in phones


def test_donations_crud_endpoints():
    """Verify /api/donations creation and retrieval."""
    post_res = client.post("/api/donations", json={
        "food_type": "Fresh Biryani & Curries",
        "quantity": 35.0,
        "unit": "portions",
        "dietary_info": "Halal",
        "location": "Colombo 03",
        "donor_name": "Royal Feast",
        "donor_phone": "+94778899001",
        "pickup_deadline": "Before 9 PM"
    })
    assert post_res.status_code == 200
    don_data = post_res.json()["donation"]
    assert don_data["food_type"] == "Fresh Biryani & Curries"
    assert don_data["quantity"] == 35.0

    # Retrieve all donations
    get_res = client.get("/api/donations")
    assert get_res.status_code == 200
    items = get_res.json()["donations"]
    assert any(d["id"] == don_data["id"] for d in items)


def test_conversations_and_message_history_sync():
    """Verify WhatsApp conversation message recording and thread querying."""
    phone = "+94755263482"
    norm_phone = "94755263482"
    
    # Record user message
    database.record_message(
        phone=phone,
        sender="user",
        text="I have 20 rice packets available in Bambalapitiya",
        is_voice=False
    )
    # Record agent reply
    database.record_message(
        phone=phone,
        sender="agent",
        text="Great! Where in Bambalapitiya should the courier collect the food?",
        is_voice=False
    )

    # Query all conversations
    conv_res = client.get("/api/conversations")
    assert conv_res.status_code == 200
    convs = conv_res.json()["conversations"]
    matching_conv = next((c for c in convs if c["phone_number"] in [phone, norm_phone]), None)
    assert matching_conv is not None
    assert matching_conv["message_count"] == 2

    # Query chronological messages for this user
    msgs_res = client.get(f"/api/conversations/{phone}/messages")
    assert msgs_res.status_code == 200
    msgs = msgs_res.json()["messages"]
    assert len(msgs) == 2
    assert msgs[0]["sender"] == "user"
    assert "20 rice packets" in msgs[0]["message_text"]
    assert msgs[1]["sender"] == "agent"
    assert "Bambalapitiya" in msgs[1]["message_text"]


def test_live_operations_pipeline_aggregation():
    """Verify /api/live-operations aggregates active rescue stages with step numbers."""
    # Seed a donation
    don = database.create_donation_record(
        donation_id="don-pipeline-1",
        donor_id="d1",
        food_type="15 Bakery Sandwiches",
        quantity=15,
        unit="portions",
        dietary_info="Standard",
        location="Colombo 04",
        available_from="Now",
        deadline="Before 6 PM"
    )

    ops_res = client.get("/api/live-operations")
    assert ops_res.status_code == 200
    ops = ops_res.json()["operations"]
    found_op = next((o for o in ops if o["donation_id"] == "don-pipeline-1"), None)
    assert found_op is not None
    assert found_op["status"] == "AVAILABLE"
    assert found_op["stage_step"] == 1


def test_agent_events_audit_log_endpoint():
    """Verify /api/agent-events returns audited operational decisions."""
    database.create_audit_event_record(
        event_id="evt-101",
        event_type="VOLUNTEER_ASSIGNED",
        actor="Logistics Engine",
        related_id="task-99",
        metadata={"volunteer_id": "v1", "distance_km": 3.2}
    )

    res = client.get("/api/agent-events")
    assert res.status_code == 200
    events = res.json()["events"]
    assert len(events) >= 1
    assert any(e["id"] == "evt-101" for e in events)


def test_map_locations_endpoint():
    """Verify /api/locations returns operational coordinates for organizations and volunteers."""
    res = client.get("/api/locations")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "markers" in data
    assert len(data["markers"]) >= 4  # 2 orgs + 2 volunteers seeded


def test_reports_and_analytics_endpoint():
    """Verify /api/reports returns impact metrics and distribution data."""
    res = client.get("/api/reports")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "summary" in data
    assert "regional_distribution" in data
    assert "volunteer_leaderboard" in data


def test_settings_transport_cost_read_and_update():
    """Verify /api/settings reads and updates dynamic transport reimbursement rates."""
    # Read initial
    get_res = client.get("/api/settings")
    assert get_res.status_code == 200
    t_cfg = get_res.json()["transport_cost"]
    assert "base_fare" in t_cfg
    assert "cost_per_km" in t_cfg

    # Update configuration
    post_res = client.post("/api/settings", json={
        "base_fare": 200.0,
        "cost_per_km": 95.0,
        "currency": "LKR"
    })
    assert post_res.status_code == 200
    updated = post_res.json()["transport_cost"]
    assert updated["base_fare"] == 200.0
    assert updated["cost_per_km"] == 95.0

    # Verify persistence
    get_res2 = client.get("/api/settings")
    assert get_res2.json()["transport_cost"]["base_fare"] == 200.0
    assert get_res2.json()["transport_cost"]["cost_per_km"] == 95.0


def test_whatsapp_conversation_simulator_endpoint():
    """Verify /api/conversations/{phone}/simulate runs the resilient agent and records both messages."""
    sim_phone = "+94779998877"
    res = client.post(f"/api/conversations/{sim_phone}/simulate", json={
        "message": "I want to donate 10 boxes of prepared food",
        "is_voice": False
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "reply" in data
    assert len(data["messages"]) >= 2
    assert data["messages"][0]["sender"] == "user"
    assert data["messages"][1]["sender"] == "agent"


def test_distributed_donation_pipeline_step_7():
    """Verify DISTRIBUTED status maps to stage_step 7 in live operations pipeline."""
    don = database.create_donation_record(
        donation_id="don-dist-test-1",
        donor_id="d1",
        food_type="Rice & Curry",
        quantity=10,
        unit="packets",
        dietary_info="Standard",
        location="Kegalle, Sabaragamuwa, LK",
        available_from="Now",
        deadline="Before 8 PM"
    )
    database.update_donation_status_record("don-dist-test-1", "DISTRIBUTED")

    ops_res = client.get("/api/live-operations")
    assert ops_res.status_code == 200
    ops = ops_res.json()["operations"]
    found_op = next((o for o in ops if o["donation_id"] == "don-dist-test-1"), None)
    assert found_op is not None
    assert found_op["status"] == "DISTRIBUTED"
    assert found_op["stage_step"] == 7
    assert found_op["stage_badge"] == "completed"
    assert found_op["stage_label"] == "Delivered & Rescued"


def test_registered_volunteer_multi_turn_and_user_directory():
    """Verify registered volunteer messaging multiple times gets volunteer responses and no donor drafts."""
    import tools
    vol_res = json.loads(tools.register_volunteer(
        name="a volunteer",
        service_area="Kegalle",
        phone="+94772117131",
        transport_mode="Car"
    ))
    assert vol_res["status"] == "success"

    # Simulate volunteer messaging
    res1 = client.post("/api/conversations/+94772117131/simulate", json={
        "message": "Hi",
        "is_voice": False
    })
    assert res1.status_code == 200
    r1_text = res1.json()["reply"]
    assert "Volunteer Courier" in r1_text or "a volunteer" in r1_text or "Volunteer" in r1_text

    # Ask about food / pickups
    res2 = client.post("/api/conversations/+94772117131/simulate", json={
        "message": "any food available?",
        "is_voice": False
    })
    assert res2.status_code == 200
    r2_text = res2.json()["reply"]
    assert "Volunteer" in r2_text or "pickup" in r2_text.lower() or "AVAILABLE" in r2_text

    # Verify user directory
    users_res = client.get("/api/users")
    assert users_res.status_code == 200
    users = {u["phone_number"]: u for u in users_res.json()["users"]}
    assert "94772117131" in users
    vol_user = users["94772117131"]
    assert vol_user["display_name"] == "a volunteer"
    assert vol_user["user_role"] == "volunteer"
    assert vol_user["onboarding_completed"] is True
    # Draft should be empty / not active
    assert not vol_user.get("active_draft") or not vol_user["active_draft"].get("food_type")


def test_registered_organization_multi_turn_reassurance():
    """Verify registered recipient organization gets appropriate reassurance without donor drafts."""
    import tools
    org_res = json.loads(tools.register_organization(
        name="Jeya orphanage",
        location="Kegalle",
        service_area="Kegalle",
        accepted_food_types="Meals",
        phone="+94760552483",
        capacity="50 portions"
    ))
    assert org_res["status"] == "success"

    res = client.post("/api/conversations/+94760552483/simulate", json={
        "message": "do you have food available?",
        "is_voice": False
    })
    assert res.status_code == 200
    reply = res.json()["reply"]
    assert "organization" in reply.lower() or "orphanage" in reply.lower() or "priority" in reply.lower() or "surplus" in reply.lower()

    # Verify user directory
    users_res = client.get("/api/users")
    assert users_res.status_code == 200
    users = {u["phone_number"]: u for u in users_res.json()["users"]}
    assert "94760552483" in users
    org_user = users["94760552483"]
    assert org_user["display_name"] == "Jeya orphanage"
    assert org_user["user_role"] == "organization"
    assert org_user["onboarding_completed"] is True

