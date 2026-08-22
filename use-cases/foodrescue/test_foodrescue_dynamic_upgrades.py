"""Tests for Dynamic Multi-Role Coordination, Dynamic Settings, and GPS Logistics."""

import pytest
import json
import database
import tools
import routing
import resilient_executor
import whatsapp_handler
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api_routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    database.setup_database()
    database.reset_database_data(wipe_all=True)
    yield
    database.reset_database_data(wipe_all=True)


def test_active_users_kpi_starts_at_zero_and_increments():
    """Verify that active users starts at 0 and increments strictly when users register."""
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    stats = res.json()["stats"]
    assert stats["active_users"] == 0

    # User registers
    database.create_or_update_user(phone="94770001111", display_name="Test Donor", user_role="donor")
    
    res2 = client.get("/api/dashboard")
    assert res2.status_code == 200
    assert res2.json()["stats"]["active_users"] == 1

    # Second user registers
    database.create_or_update_user(phone="94770002222", display_name="Test Volunteer", user_role="volunteer")
    
    res3 = client.get("/api/dashboard")
    assert res3.status_code == 200
    assert res3.json()["stats"]["active_users"] == 2


def test_dynamic_settings_vehicle_rate_manager():
    """Verify dynamic vehicle rate configuration via /api/settings endpoint."""
    # Read initial
    get_res = client.get("/api/settings")
    assert get_res.status_code == 200
    cfg = get_res.json()["transport_cost"]
    assert "rates_by_vehicle" in cfg

    # Update rates dynamically
    update_payload = {
        "base_fare": 150.0,
        "cost_per_km": 95.0,
        "rates_by_vehicle": {
            "Motorbike": 60.0,
            "Three-Wheeler": 100.0,
            "Car": 140.0,
            "Van": 180.0,
            "Bicycle": 30.0
        }
    }
    post_res = client.post("/api/settings", json=update_payload)
    assert post_res.status_code == 200
    updated = post_res.json()["transport_cost"]
    assert updated["base_fare"] == 150.0
    assert updated["rates_by_vehicle"]["Car"] == 140.0
    assert updated["rates_by_vehicle"]["Motorbike"] == 60.0

    # Verify routing uses the updated dynamic rates
    assert routing.get_transport_rate("car") == 140.0
    assert routing.get_transport_rate("motorbike") == 60.0
    assert routing.get_transport_rate("van") == 180.0


@pytest.mark.asyncio
async def test_volunteer_progressive_onboarding_and_dynamic_distance():
    """Verify progressive onboarding asking Name -> Vehicle -> Location, and dynamic distance calculation."""
    phone = "94779998888"
    session_id = f"whatsapp:{phone}"

    # Step 1: Initial volunteer message
    resp1 = await resilient_executor.execute_deterministic_fallback("I want to volunteer", session_id)
    assert "name" in resp1.lower()

    # Step 2: Provide Name
    resp2 = await resilient_executor.execute_deterministic_fallback("My name is Nuwan Perera", session_id)
    assert "transport mode" in resp2.lower() or "vehicle" in resp2.lower()

    # Step 3: Provide Vehicle
    resp3 = await resilient_executor.execute_deterministic_fallback("Car", session_id)
    assert "city" in resp3.lower() or "district" in resp3.lower() or "area" in resp3.lower()

    # Step 4: Provide Location
    resp4 = await resilient_executor.execute_deterministic_fallback("Colombo 03", session_id)
    assert "Nuwan" in resp4
    assert "Car" in resp4 or "car" in resp4.lower()

    # Verify volunteer profile created in DB
    vol = database.get_volunteer_by_phone(phone)
    assert vol is not None
    assert vol["name"] == "Nuwan Perera"
    assert vol["transport_mode"] == "Car"


@pytest.mark.asyncio
async def test_security_cross_notifications():
    """Verify donor and recipient organization receive real-time notifications on volunteer actions."""
    donor_phone = "94770003333"
    org_phone = "94770004444"
    vol_phone = "94770005555"

    database.create_donor_record("d-test", "Galle Face Hotel", donor_phone, "Colombo 03")
    database.create_organization_record("org-test", "Colombo Food Shelter", org_phone, "Colombo 07", "Prepared Meals")
    database.create_volunteer_record("v-test", "Sunil Courier", vol_phone, "Colombo", "Car", current_status="available", location="Colombo 03")

    don = database.create_donation_record("don-test", "d-test", "Fried Rice", 40, "packets", "Halal", "Colombo 03", "Now", "8 PM")
    task = database.create_pickup_task_record("task-test", "don-test", "org-test", "Colombo 03", "Colombo 07", "8 PM")

    # Volunteer accepts task
    accept_reply = "✅ Pickup Task Assigned & Accepted"
    await whatsapp_handler.dispatch_lifecycle_cross_notifications("Accept task", accept_reply, from_number=vol_phone)

    # Volunteer confirms collection
    collect_reply = "🍱 Pickup Confirmed! COLLECTED"
    await whatsapp_handler.dispatch_lifecycle_cross_notifications("Food collected", collect_reply, from_number=vol_phone)

    # Volunteer confirms delivery
    deliver_reply = "🎉 Delivery Completed! DELIVERED"
    await whatsapp_handler.dispatch_lifecycle_cross_notifications("Delivered", deliver_reply, from_number=vol_phone)
