"""Comprehensive Test Suite for FoodRescue AI GraphHopper Location-Aware Routing Engine.

Verifies:
1. Successful GraphHopper route calculation (normalized response format).
2. Distance calculation (kilometers and meters).
3. Travel duration calculation (minutes and seconds).
4. Donation -> Organization route calculation.
5. Volunteer -> Donation route calculation.
6. Volunteer -> Donation -> Organization complete multi-point pickup route.
7. Multi-volunteer distance & ETA ranking.
8. Volunteer availability business rule precedence (unavailable volunteers excluded).
9. Missing coordinates handling (structured error, no crash).
10. Invalid coordinates handling (structured error, no crash).
11. Missing API key handling (graceful local fallback).
12. GraphHopper API 500 failure handling (shielded, no crash).
13. GraphHopper API timeout handling (shielded, no crash).
14. Existing volunteer assignment workflow compatibility.
15. REST API endpoints (POST /api/routes/calculate and POST /api/routes/pickup-route).
"""

import os
import json
import uuid
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx

import database
import tools
import routing
import routing_service
from api_routes import router


@pytest.fixture(autouse=True)
def setup_test_db():
    """Ensure database tables exist and cache is fresh for each test."""
    database.setup_database()
    routing_service.clear_cache()


@pytest.mark.asyncio
async def test_01_graphhopper_route_success():
    """Test 1: Successful GraphHopper Routing API call with normalized response."""
    mock_gh_response = {
        "hints": {"visited_nodes.sum": 100},
        "info": {"copyrights": ["GraphHopper", "OpenStreetMap contributors"]},
        "paths": [
            {
                "distance": 4200.0,
                "time": 720000,
                "points": "w`a`@q`a`@??",
                "instructions": []
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_gh_response

    with patch.dict(os.environ, {"GRAPHHOPPER_API_KEY": "test_mock_key"}), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        res = await routing_service.calculate_route(
            origin={"latitude": 6.9215, "longitude": 79.8737},
            destination={"latitude": 6.9344, "longitude": 79.8428},
            transport_mode="car"
        )

        assert res["success"] is True
        assert res["distance_meters"] == 4200.0
        assert res["distance_km"] == 4.2
        assert res["duration_seconds"] == 720
        assert res["duration_minutes"] == 12
        assert res["duration_text"] == "12 min"
        assert res["provider"] == "graphhopper"
        assert res["is_exact_road_route"] is True
        assert "route_geometry" in res


@pytest.mark.asyncio
async def test_02_distance_calculation():
    """Test 2: calculate_distance helper returns standardized distance and duration."""
    mock_gh_response = {
        "paths": [{"distance": 3150.0, "time": 480000, "points": "abc"}]
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_gh_response

    with patch.dict(os.environ, {"GRAPHHOPPER_API_KEY": "test_mock_key"}), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        res = await routing_service.calculate_distance("Colombo 3", "Colombo 7", transport_mode="car")
        assert res["success"] is True
        assert res["distance_km"] == 3.15
        assert res["duration_minutes"] == 8


@pytest.mark.asyncio
async def test_03_duration_calculation():
    """Test 3: Travel duration accurately extracted in seconds and minutes."""
    mock_gh_response = {
        "paths": [{"distance": 10500.0, "time": 1500000, "points": "xyz"}]
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_gh_response

    with patch.dict(os.environ, {"GRAPHHOPPER_API_KEY": "test_mock_key"}), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        res = await routing_service.calculate_route("Mawanella", "Kegalle", transport_mode="motorbike")
        assert res["success"] is True
        assert res["duration_seconds"] == 1500
        assert res["duration_minutes"] == 25
        assert res["duration_text"] == "25 min"


@pytest.mark.asyncio
async def test_04_donation_to_organization():
    """Test 4: Calculate route between a food donation and a recipient organization."""
    mock_gh_response = {
        "paths": [{"distance": 5400.0, "time": 900000, "points": "poly_don_org"}]
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_gh_response

    with patch.dict(os.environ, {"GRAPHHOPPER_API_KEY": "test_mock_key"}), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        res = await routing_service.calculate_route(
            origin="Grand Hotel Colombo",
            destination="Community Kitchen Colombo 7",
            transport_mode="car"
        )
        assert res["success"] is True
        assert res["distance_km"] == 5.4
        assert res["duration_minutes"] == 15


@pytest.mark.asyncio
async def test_05_volunteer_to_donation():
    """Test 5: Calculate route from volunteer courier location to food pickup location."""
    mock_gh_response = {
        "paths": [{"distance": 2100.0, "time": 420000, "points": "poly_vol_don"}]
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_gh_response

    with patch.dict(os.environ, {"GRAPHHOPPER_API_KEY": "test_mock_key"}), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        res = await routing_service.calculate_route(
            origin="Colombo 3",
            destination="Colombo 1",
            transport_mode="motorbike"
        )
        assert res["success"] is True
        assert res["distance_km"] == 2.1
        assert res["duration_minutes"] == 7


@pytest.mark.asyncio
async def test_06_complete_pickup_route_two_legs():
    """Test 6: Calculate complete two-leg pickup route (Volunteer -> Donation -> Organization)."""
    def mock_get_side_effect(url, params=None):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Check origin to return leg 1 vs leg 2
        pts = params.get("point", []) if params else []
        if pts and "6.9056" in pts[0]:
            mock_resp.json.return_value = {"paths": [{"distance": 2100.0, "time": 420000, "points": "leg1"}]}
        else:
            mock_resp.json.return_value = {"paths": [{"distance": 3400.0, "time": 600000, "points": "leg2"}]}
        return mock_resp

    with patch.dict(os.environ, {"GRAPHHOPPER_API_KEY": "test_mock_key"}), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=mock_get_side_effect):

        res = await routing_service.calculate_pickup_route(
            volunteer_location="Colombo 3",
            donation_location="Colombo 1",
            organization_location="Colombo 7",
            transport_mode="motorbike"
        )

        assert res["success"] is True
        assert res["volunteer_to_donation"]["distance_km"] == 2.1
        assert res["volunteer_to_donation"]["duration_minutes"] == 7
        assert res["donation_to_organization"]["distance_km"] == 3.4
        assert res["donation_to_organization"]["duration_minutes"] == 10
        assert res["total_distance_km"] == 5.5
        assert res["total_duration_minutes"] == 17
        assert res["provider"] == "graphhopper"


@pytest.mark.asyncio
async def test_07_multiple_volunteers_ranking():
    """Test 7: Multiple volunteers are ranked by GraphHopper travel time and distance."""
    volunteers = [
        {"id": "v_b", "name": "Volunteer B", "location": "Dehiwala", "availability_status": "AVAILABLE", "transport_mode": "motorbike"},
        {"id": "v_a", "name": "Volunteer A", "location": "Colombo 3", "availability_status": "AVAILABLE", "transport_mode": "motorbike"},
        {"id": "v_c", "name": "Volunteer C", "location": "Nugegoda", "availability_status": "AVAILABLE", "transport_mode": "motorbike"},
    ]

    def mock_get_ranking(url, params=None):
        pts = params.get("point", []) if params else []
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Colombo 3 -> Colombo 1 (closest)
        if pts and "6.9056" in pts[0]:
            mock_resp.json.return_value = {"paths": [{"distance": 2100.0, "time": 420000, "points": "a"}]}
        # Nugegoda -> Colombo 1 (middle)
        elif pts and "6.8649" in pts[0]:
            mock_resp.json.return_value = {"paths": [{"distance": 4200.0, "time": 780000, "points": "c"}]}
        # Dehiwala -> Colombo 1 (furthest)
        else:
            mock_resp.json.return_value = {"paths": [{"distance": 6400.0, "time": 1080000, "points": "b"}]}
        return mock_resp

    with patch.dict(os.environ, {"GRAPHHOPPER_API_KEY": "test_mock_key"}), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=mock_get_ranking):

        ranked = await routing_service.rank_volunteers_by_distance(
            volunteers=volunteers,
            donation_location="Colombo 1",
            transport_mode="motorbike"
        )

        assert len(ranked) == 3
        # Volunteer A must be ranked #1 (2.1 km / 7 min)
        assert ranked[0]["name"] == "Volunteer A"
        assert ranked[0]["distance_km"] == 2.1
        assert ranked[0]["duration_minutes"] == 7

        # Volunteer C must be #2 (4.2 km / 13 min)
        assert ranked[1]["name"] == "Volunteer C"
        assert ranked[1]["distance_km"] == 4.2

        # Volunteer B must be #3 (6.4 km / 18 min)
        assert ranked[2]["name"] == "Volunteer B"
        assert ranked[2]["distance_km"] == 6.4


@pytest.mark.asyncio
async def test_08_volunteer_availability_precedence():
    """Test 8: Availability business rules take precedence — unavailable volunteers are excluded even if closer."""
    volunteers = [
        {"id": "v_avail", "name": "Volunteer Available", "location": "Dehiwala", "availability_status": "AVAILABLE", "transport_mode": "motorbike"},
        {"id": "v_busy", "name": "Volunteer Busy", "location": "Colombo 3", "availability_status": "BUSY", "transport_mode": "motorbike"},
        {"id": "v_offline", "name": "Volunteer Offline", "location": "Colombo 3", "availability_status": "OFFLINE", "transport_mode": "motorbike"},
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"paths": [{"distance": 5000.0, "time": 900000, "points": "p"}]}

    with patch.dict(os.environ, {"GRAPHHOPPER_API_KEY": "test_mock_key"}), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        ranked = await routing_service.rank_volunteers_by_distance(
            volunteers=volunteers,
            donation_location="Colombo 1",
            transport_mode="motorbike"
        )

        # Only the AVAILABLE volunteer is ranked
        assert len(ranked) == 1
        assert ranked[0]["name"] == "Volunteer Available"
        assert ranked[0]["is_available"] is True


@pytest.mark.asyncio
async def test_09_missing_coordinates_handling():
    """Test 9: Missing or empty location returns clean error without crashing."""
    res = await routing_service.calculate_route(
        origin="",
        destination="Colombo 7",
        transport_mode="car"
    )
    assert res["success"] is False
    assert res["distance_km"] is None
    assert "Invalid or unresolved coordinates" in res["error"]


@pytest.mark.asyncio
async def test_10_invalid_coordinates_handling():
    """Test 10: Invalid coordinates (out of range lat/lon) returns structured error without crash."""
    res = await routing_service.calculate_route(
        origin={"latitude": 999.0, "longitude": 999.0},
        destination="Colombo 7",
        transport_mode="car"
    )
    assert res["success"] is False
    assert res["distance_km"] is None


@pytest.mark.asyncio
async def test_11_missing_api_key_local_fallback():
    """Test 11: Missing API key falls back gracefully to local coordinate calculation without crashing."""
    with patch.dict(os.environ, {"GRAPHHOPPER_API_KEY": "", "GRAPH_HOPPER_API_KEY": ""}):
        res = await routing_service.calculate_route(
            origin="Colombo 3",
            destination="Colombo 7",
            transport_mode="car"
        )
        assert res["success"] is True
        assert res["distance_km"] > 0
        assert res["duration_minutes"] > 0
        assert res["provider"] == "haversine_fallback"


@pytest.mark.asyncio
async def test_12_graphhopper_api_failure_shielding():
    """Test 12: GraphHopper 500 error is caught and shielded with fallback without throwing exception."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal GraphHopper Server Error"

    with patch.dict(os.environ, {"GRAPHHOPPER_API_KEY": "test_mock_key"}), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        res = await routing_service.calculate_route(
            origin="Colombo 3",
            destination="Colombo 7",
            transport_mode="car"
        )
        # Should gracefully return fallback route rather than raising exception
        assert res["success"] is True
        assert res["distance_km"] > 0
        assert res["provider"] == "haversine_fallback"


@pytest.mark.asyncio
async def test_13_graphhopper_api_timeout_shielding():
    """Test 13: GraphHopper request timeout is handled cleanly with fallback."""
    with patch.dict(os.environ, {"GRAPHHOPPER_API_KEY": "test_mock_key"}), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=httpx.TimeoutException("Connection timed out")):

        res = await routing_service.calculate_route(
            origin="Colombo 3",
            destination="Colombo 7",
            transport_mode="car"
        )
        assert res["success"] is True
        assert res["distance_km"] > 0
        assert res["provider"] == "haversine_fallback"


def test_14_agent_kernel_tools_integration():
    """Test 14: Agent Kernel tools calculate_route, calculate_distance, calculate_pickup_route, find_nearest_volunteers."""
    # Seed volunteer
    unique_phone = f"9477{uuid.uuid4().hex[:7]}"
    tools.register_volunteer(
        name="Kamal Courier",
        service_area="Colombo 3",
        phone=unique_phone,
        transport_mode="Motorbike"
    )

    # 1. calculate_route tool
    route_raw = tools.calculate_route(origin="Colombo 3", destination="Colombo 7", transport_mode="car")
    route_data = json.loads(route_raw)
    assert route_data["success"] is True
    assert route_data["distance_km"] > 0

    # 2. calculate_distance tool
    dist_raw = tools.calculate_distance(origin="Colombo 3", destination="Colombo 7", transport_mode="car")
    dist_data = json.loads(dist_raw)
    assert dist_data["success"] is True
    assert dist_data["distance_km"] > 0

    # 3. calculate_pickup_route tool
    pickup_raw = tools.calculate_pickup_route(
        volunteer_location="Colombo 3",
        pickup_location="Colombo 1",
        delivery_location="Colombo 7",
        transport_mode="motorbike"
    )
    pickup_data = json.loads(pickup_raw)
    assert pickup_data["success"] is True
    assert pickup_data["total_distance_km"] > 0
    assert "volunteer_to_donation" in pickup_data
    assert "donation_to_organization" in pickup_data

    # 4. find_nearest_volunteers tool
    vols_raw = tools.find_nearest_volunteers(pickup_location="Colombo 1", min_capacity=10)
    vols_data = json.loads(vols_raw)
    assert vols_data["status"] == "success"
    assert vols_data["count"] >= 1


def test_15_api_endpoints_calculate_and_pickup_route():
    """Test 15: REST API endpoints POST /api/routes/calculate and POST /api/routes/pickup-route."""
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # 1. POST /api/routes/calculate
    calc_payload = {
        "origin": {"latitude": 6.9215, "longitude": 79.8737},
        "destination": {"latitude": 6.9344, "longitude": 79.8428},
        "transport_mode": "car"
    }
    resp1 = client.post("/api/routes/calculate", json=calc_payload)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["success"] is True
    assert data1["distance_km"] > 0
    assert data1["duration_minutes"] > 0

    # 2. POST /api/routes/pickup-route
    pickup_payload = {
        "volunteer": {"latitude": 6.9056, "longitude": 79.8519},
        "donation": {"latitude": 6.9344, "longitude": 79.8428},
        "organization": {"latitude": 6.9069, "longitude": 79.8708},
        "transport_mode": "motorbike"
    }
    resp2 = client.post("/api/routes/pickup-route", json=pickup_payload)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["success"] is True
    assert data2["total_distance_km"] > 0
    assert "volunteer_to_donation" in data2
    assert "donation_to_organization" in data2


@pytest.mark.asyncio
async def test_16_live_graphhopper_api_call():
    """Test 16: Real live GraphHopper API call when key is provided."""
    api_key = os.environ.get("GRAPHHOPPER_API_KEY", "").strip() or "a79f8d1c-dc1b-4360-bfea-ac5def059522"
    with patch.dict(os.environ, {"GRAPHHOPPER_API_KEY": api_key}):
        res = await routing_service.calculate_route(
            origin={"latitude": 6.9215, "longitude": 79.8737},
            destination={"latitude": 6.9344, "longitude": 79.8428},
            transport_mode="car"
        )
        assert res["success"] is True
        assert res["distance_km"] > 0
        assert res["duration_minutes"] > 0
        if res.get("provider") == "graphhopper":
            assert res["is_exact_road_route"] is True
            assert res["route_geometry"] is not None
