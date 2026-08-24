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


def test_safe_template_formatting_no_unrendered_braces():
    """Verify that get_localized_message never returns unrendered {placeholder} strings."""
    import translation_service

    # Test with partial kwargs
    msg = translation_service.get_localized_message(
        "org_matched_notify_donor",
        lang="en",
        donation_id="don-12345",
        district="Kegalle",
        org_name="Sara Food Home",
        org_location="Zahira Rd, Hinguloya",
    )
    assert "don-12345" in msg
    assert "Sara Food Home" in msg
    assert "Kegalle" in msg
    assert "Zahira Rd, Hinguloya" in msg
    assert "{" not in msg, f"Found unrendered brace in: {msg}"
    assert "}" not in msg, f"Found unrendered brace in: {msg}"


def test_district_and_town_resolution_kegalle_hinguloya():
    """Verify that Hinguloya and Sabaragamuwa addresses correctly resolve to Kegalle district."""
    assert routing.resolve_district("Zahira Rd, Hinguloya, 71500, Sabaragamuwa, LK") == "Kegalle"
    assert routing.resolve_district("Hinguloya") == "Kegalle"
    assert routing.resolve_district("Mawanella, Kegalle") == "Kegalle"

    coords = routing.geocode_location("Zahira Rd, Hinguloya, 71500, Sabaragamuwa, LK")
    assert coords is not None
    assert round(coords[0], 2) == 7.24
    assert round(coords[1], 2) == 80.46


@pytest.mark.asyncio
async def test_volunteer_auto_dispatch_in_kegalle_district():
    """Verify that when a donation connects with an organization in Kegalle, volunteers in Kegalle receive task offers."""
    from unittest.mock import patch, AsyncMock

    donor_phone = "94770006666"
    org_phone = "94770007777"
    vol_phone = "94770008888"

    database.create_or_update_user(phone=donor_phone, display_name="Test Donor", preferred_language="en", onboarding_completed=True)
    database.create_donor_record("donor-keg", "Test Donor", donor_phone, "Zahira Rd, Hinguloya, 71500, Sabaragamuwa, LK")
    database.create_organization_record("org-keg", "Sara Food Kitchen", org_phone, "Mawanella, Kegalle", "Prepared Meals")
    database.create_volunteer_record("vol-keg", "Mushan Courier", vol_phone, "Kegalle", "Motorbike", current_status="available")

    don = database.create_donation_record("don-keg-1", "donor-keg", "Rice & Curry", 20, "portions", "Standard", "Zahira Rd, Hinguloya, 71500, Sabaragamuwa, LK", "Now", "8 PM")
    task = database.create_pickup_task_record("task-keg-1", "don-keg-1", "org-keg", "Zahira Rd, Hinguloya, 71500, Sabaragamuwa, LK", "Mawanella, Kegalle", "8 PM")

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        reply = "✅ **Connected with Sara Food Kitchen!**\n\nWe have sent your donation details to Sara Food Kitchen."
        await whatsapp_handler.dispatch_lifecycle_cross_notifications("Accept", reply, from_number=donor_phone)

        # Ensure volunteer was dispatched notification
        vol_notified = any(call.kwargs.get("to_number") == vol_phone for call in mock_send.call_args_list)
        assert vol_notified, "Volunteer in Kegalle was not dispatched notification"


def test_api_locations_kegalle_markers_and_center():
    """Verify /api/locations endpoint properly resolves Kegalle locations without defaulting to Colombo."""
    database.create_organization_record("org-keg-map", "Sara Food Kitchen", "94770007777", "Mawanella, Kegalle", "Prepared Meals")
    database.create_volunteer_record("vol-keg-map", "Mushan Courier", "94770008888", "Kegalle", "Motorbike", current_status="available")

    res = client.get("/api/locations")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert len(data["markers"]) >= 2
    # Check that center is around Kegalle (lat ~7.25, lng ~80.35 or 80.44), not Colombo (6.92)
    assert data["center"]["lat"] > 7.0
    assert data["center"]["lng"] > 80.0
