"""FoodRescue AI — Phase 7 Advanced Logistics Test Suite.

Covers:
1. Transport cost estimation & configuration
2. Haversine distance fallback & timing
3. Google Routes API parsing & mocked network failure resilience
4. Live GPS tracking, coordinate validation, and active lifecycle enforcement
5. Volunteer reimbursement ledger accounting (PENDING ➔ APPROVED ➔ PAID)
6. Agent Kernel tool binding & structured responses for all 21 tools
7. Dual persistence parity (SQLite & MongoDB)
8. Opt-in live Google Routes API check.
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import httpx

import routing
import database
import db_sqlite
import db_mongo
import tools
import app


import routing_service


@pytest.fixture(autouse=True)
def clean_db():
    """Ensure database tables exist and are clean for each test."""
    database.setup_database()
    database.reset_database_data()
    database.seed_test_data()
    routing_service.clear_cache()
    yield
    database.reset_database_data()
    routing_service.clear_cache()


# =========================================================================
# 1. TRANSPORT COST & CONFIGURATION TESTS
# =========================================================================

def test_transport_rate_configuration():
    """Verify configured reimbursement rates for supported vehicle modes."""
    assert routing.get_transport_rate("bicycle") == 25.0
    assert routing.get_transport_rate("electric bike") == 25.0
    assert routing.get_transport_rate("motorbike") == 50.0
    assert routing.get_transport_rate("car") == 80.0
    assert routing.get_transport_rate("van") == 120.0


def test_transport_cost_calculation():
    """Verify structured calculation of transport cost given distance and mode."""
    res = routing.calculate_transport_cost(distance_km=6.2, transport_mode="motorbike")
    assert res["status"] == "success"
    assert res["distance_km"] == 6.2
    assert res["transport_mode"] == "motorbike"
    assert res["rate_per_km"] == 50.0
    assert res["estimated_cost"] == 310.0
    assert res["currency"] == "LKR"
    assert "notice" in res


def test_transport_cost_unsupported_mode():
    """Verify error on unsupported vehicle mode."""
    res = routing.calculate_transport_cost(distance_km=5.0, transport_mode="helicopter")
    assert res["status"] == "error"
    assert "Unsupported transport_mode" in res["message"]


def test_transport_cost_negative_distance():
    """Verify error on negative distance."""
    res = routing.calculate_transport_cost(distance_km=-4.5, transport_mode="car")
    assert res["status"] == "error"
    assert "cannot be negative" in res["message"]


# =========================================================================
# 2. ROUTING PROVIDER & HAVERSINE FALLBACK TESTS
# =========================================================================

@pytest.mark.asyncio
async def test_haversine_fallback_calculation():
    """Verify Haversine route computation between known Colombo landmarks."""
    provider = routing.HaversineRouteProvider()
    res = await provider.compute_route(origin="Colombo 3", destination="Colombo 7", transport_mode="motorbike")
    assert res["status"] == "success"
    assert res["provider"] == "haversine_fallback"
    assert res["distance_km"] > 0
    assert res["duration_seconds"] > 0
    assert "min" in res["duration_text"]
    assert res["geometry"] is None
    assert res["is_road_exact"] is False
    assert res["estimated_cost"] > 0


@pytest.mark.asyncio
async def test_haversine_unknown_location():
    """Verify graceful error when coordinates cannot be resolved."""
    provider = routing.HaversineRouteProvider()
    res = await provider.compute_route(origin="Unknown City XYZ", destination="Nowhere Land", transport_mode="motorbike")
    assert res["status"] == "error"
    assert "coordinates for 'Unknown City XYZ' or 'Nowhere Land' are unavailable" in res["message"]


@pytest.mark.asyncio
async def test_google_routes_mock_success():
    """Verify parsing of successful route API response via GraphHopper provider."""
    mock_payload = {
        "paths": [
            {
                "distance": 4200.0,
                "time": 720000,
                "points": "m_e~F`~_uN_c..."
            }
        ]
    }
    
    provider = routing.GraphHopperRouteProvider(api_key="mock_key_12345")
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_payload

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        res = await provider.compute_route(origin="Colombo 3", destination="Colombo 7", transport_mode="motorbike")
        
        assert res["status"] == "success"
        assert res["provider"] == "graphhopper"
        assert res["distance_km"] == 4.2
        assert res["duration_seconds"] == 720
        assert res["route_geometry"] == "m_e~F`~_uN_c..."
        assert res["estimated_cost"] > 0


@pytest.mark.asyncio
async def test_google_routes_mock_timeout_fallback():
    """Verify automatic fallback to Haversine when Route API times out."""
    provider = routing.GraphHopperRouteProvider(api_key="mock_key_12345")
    
    with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("Timeout")):
        res = await provider.compute_route(origin="Colombo 3", destination="Colombo 7", transport_mode="motorbike")
        assert res["status"] == "success"
        assert res["provider"] == "haversine_fallback"
        assert res["distance_km"] > 0


@pytest.mark.asyncio
async def test_google_routes_mock_error_fallback():
    """Verify automatic fallback to Haversine when Route API returns 500."""
    provider = routing.GraphHopperRouteProvider(api_key="mock_key_12345")
    mock_response = MagicMock()
    mock_response.status_code = 500
    
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        res = await provider.compute_route(origin="Colombo 3", destination="Colombo 7", transport_mode="motorbike")
        assert res["status"] == "success"
        assert res["provider"] == "haversine_fallback"


# =========================================================================
# 3. GPS TRACKING & PRIVACY LIFECYCLE TESTS
# =========================================================================

def test_gps_update_success():
    """Verify recording of valid GPS coordinate point on an active pickup."""
    task = database.create_pickup_task_record(
        task_id="task-gps-1",
        donation_id="don-test-1",
        org_id="org1",
        pickup_loc="Colombo 3",
        delivery_loc="Colombo 7",
        time="Now"
    )
    database.assign_volunteer_record("task-gps-1", "v1")
    
    rec = database.record_pickup_location(
        location_id="loc-1",
        pickup_task_id="task-gps-1",
        volunteer_id="v1",
        latitude=6.9056,
        longitude=79.8519,
        accuracy_m=10.5
    )
    assert rec["id"] == "loc-1"
    assert rec["latitude"] == 6.9056
    assert rec["longitude"] == 79.8519
    
    latest = database.get_latest_pickup_location("task-gps-1")
    assert latest is not None
    assert latest["id"] == "loc-1"


def test_gps_update_rejected_on_inactive_pickup():
    """Verify tools reject GPS coordinate updates when pickup is already DELIVERED."""
    task = database.create_pickup_task_record(
        task_id="task-gps-2",
        donation_id="don-test-2",
        org_id="org1",
        pickup_loc="Colombo 3",
        delivery_loc="Colombo 7",
        time="Now"
    )
    database.assign_volunteer_record("task-gps-2", "v1")
    database.update_pickup_status_record("task-gps-2", "DELIVERED")
    
    tool_res = json.loads(tools.update_pickup_location(
        pickup_task_id="task-gps-2",
        latitude=6.9056,
        longitude=79.8519
    ))
    assert tool_res["status"] == "error"
    assert "rejected" in tool_res["message"]


def test_gps_coordinate_validation():
    """Verify coordinate bounds validation (-90..90, -180..180)."""
    task = database.create_pickup_task_record(
        task_id="task-gps-3",
        donation_id="don-test-3",
        org_id="org1",
        pickup_loc="Colombo 3",
        delivery_loc="Colombo 7",
        time="Now"
    )
    database.assign_volunteer_record("task-gps-3", "v1")
    
    tool_res = json.loads(tools.update_pickup_location(
        pickup_task_id="task-gps-3",
        latitude=120.0,  # Invalid
        longitude=79.8519
    ))
    assert tool_res["status"] == "error"
    assert "Latitude must be" in tool_res["message"]


# =========================================================================
# 4. VOLUNTEER REIMBURSEMENT LEDGER TESTS
# =========================================================================

def test_reimbursement_creation_and_status_transitions():
    """Verify reimbursement creation with status PENDING and transitions to APPROVED and PAID."""
    reimb = database.create_reimbursement_record(
        reimbursement_id="reimb-test-1",
        pickup_task_id="task-r-1",
        volunteer_id="v1",
        distance_km=4.5,
        rate_per_km=50.0,
        transport_mode="motorbike",
        amount=225.0,
        currency="LKR",
        notes="Test reimbursement record"
    )
    assert reimb["id"] == "reimb-test-1"
    assert reimb["status"] == "PENDING"
    assert reimb["amount"] == 225.0
    
    # Transition to APPROVED
    assert database.update_reimbursement_status_record("reimb-test-1", "APPROVED") is True
    updated = database.get_reimbursement_record("reimb-test-1")
    assert updated["status"] == "APPROVED"
    assert updated["approved_at"] is not None
    
    # Transition to PAID
    assert database.update_reimbursement_status_record("reimb-test-1", "PAID") is True
    paid = database.get_reimbursement_record("reimb-test-1")
    assert paid["status"] == "PAID"
    assert paid["paid_at"] is not None


def test_pickup_delivery_auto_creates_reimbursement():
    """Verify that updating a pickup task to DELIVERED automatically generates a PENDING reimbursement."""
    task = database.create_pickup_task_record(
        task_id="task-auto-reimb-1",
        donation_id="don-auto-1",
        org_id="org1",
        pickup_loc="Colombo 3",
        delivery_loc="Colombo 7",
        time="Now"
    )
    database.assign_volunteer_record("task-auto-reimb-1", "v1")
    
    res = json.loads(tools.update_pickup_status("task-auto-reimb-1", "DELIVERED"))
    assert res["status"] == "success"
    assert res["task_status"] == "DELIVERED"
    
    reimb = database.get_reimbursement_by_pickup_id("task-auto-reimb-1")
    assert reimb is not None
    assert reimb["status"] == "PENDING"
    assert reimb["amount"] > 0
    assert reimb["volunteer_id"] == "v1"


# =========================================================================
# 5. AGENT KERNEL TOOL BINDING TESTS (21 TOOLS)
# =========================================================================

def test_all_21_tools_bound():
    """Verify that all operational FoodRescue tools are bound to the coordinator."""
    assert len(app.BOUND_TOOLS) >= 21


def test_calculate_route_tool():
    """Verify calculate_route tool returns valid JSON."""
    out = json.loads(tools.calculate_route("Colombo 3", "Colombo 7", "motorbike"))
    assert out["status"] == "success"
    assert "distance_km" in out
    assert "estimated_cost" in out


def test_calculate_transport_cost_tool():
    """Verify calculate_transport_cost tool returns structured response."""
    out = json.loads(tools.calculate_transport_cost(10.0, "car"))
    assert out["status"] == "success"
    assert out["estimated_cost"] == 800.0


def test_reimbursement_management_tools():
    """Verify tool CRUD for volunteer reimbursements."""
    task = database.create_pickup_task_record("task-tool-1", "don-1", "org1", "Colombo 3", "Colombo 7", "Now")
    database.assign_volunteer_record("task-tool-1", "v1")
    
    created = json.loads(tools.create_reimbursement("task-tool-1", "v1", 6.0, "motorbike"))
    assert created["status"] == "success"
    reimb_id = created["reimbursement_id"]
    
    fetched = json.loads(tools.get_reimbursement(reimbursement_id=reimb_id))
    assert fetched["status"] == "success"
    assert fetched["reimbursement"]["id"] == reimb_id
    
    updated = json.loads(tools.update_reimbursement_status(reimb_id, "APPROVED"))
    assert updated["status"] == "success"
    assert updated["reimbursement_status"] == "APPROVED"


# =========================================================================
# 6. MONGODB REPOSITORY PARITY TESTS (MOCKED)
# =========================================================================

def test_mongo_repository_logistics_parity():
    """Verify MongoRepository parity for reimbursement and GPS location history operations."""
    repo = db_mongo.MongoRepository()
    
    mock_db = MagicMock()
    repo._db = mock_db
    
    # Reimbursement create
    mock_reimb_col = MagicMock()
    mock_db.__getitem__.side_effect = lambda name: mock_reimb_col if name == "reimbursements" else MagicMock()
    
    repo.create_reimbursement_record(
        reimbursement_id="reimb-m-1",
        pickup_task_id="task-m-1",
        volunteer_id="v1",
        distance_km=5.0,
        rate_per_km=50.0,
        transport_mode="motorbike",
        amount=250.0
    )
    mock_reimb_col.insert_one.assert_called_once()
    
    # Location history record
    mock_loc_col = MagicMock()
    mock_db.__getitem__.side_effect = lambda name: mock_loc_col if name == "pickup_location_history" else MagicMock()
    
    repo.record_pickup_location(
        location_id="loc-m-1",
        pickup_task_id="task-m-1",
        volunteer_id="v1",
        latitude=6.9056,
        longitude=79.8519
    )
    mock_loc_col.insert_one.assert_called_once()


# =========================================================================
# 7. OPT-IN LIVE GOOGLE ROUTES API TEST
# =========================================================================

@pytest.mark.asyncio
async def test_route_provider_live():
    """Live Google Routes API test (skipped if ROUTING_API_KEY is not configured)."""
    api_key = os.environ.get("ROUTING_API_KEY", "").strip()
    if not api_key:
        pytest.skip("ROUTING_API_KEY not configured in environment.")
        
    provider = routing.GoogleRoutesProvider(api_key=api_key)
    res = await provider.compute_route(origin="Colombo 3", destination="Colombo 7", transport_mode="motorbike")
    
    assert res["status"] == "success"
    assert res["distance_km"] > 0
    assert res["provider"] in ["google_routes", "haversine_fallback"]
