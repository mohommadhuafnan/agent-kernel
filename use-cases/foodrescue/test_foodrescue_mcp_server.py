"""Tests for FoodRescue AI Custom MCP Server.

Validates tool discovery, location lookups, proximity matching, dynamic road routing,
transport reimbursement calculations, QR handover generation & verification lifecycle,
task querying, system health checks, zero-mock data integrity, and MCP client tool invocation.
"""

import json
import uuid
import pytest
import pytest_asyncio
import database
import tools
from mcp_server import (
    create_mcp_server,
    get_mcp_server,
    get_live_location,
    find_nearby_organizations,
    find_nearby_volunteers,
    match_donation,
    calculate_route,
    calculate_transport_support,
    calculate_task_metrics,
    generate_handover_qr,
    verify_handover_qr,
    get_task_status,
    get_donation,
    get_foodrescue_system_status
)


@pytest.fixture(autouse=True)
def setup_test_db():
    """Ensure a clean database setup before each test."""
    database.setup_database()


@pytest.mark.asyncio
async def test_mcp_server_initialization_and_tool_discovery():
    """Verify MCP Server instantiates and registers all 12 operational tools."""
    server = create_mcp_server("foodrescue-test")
    assert server.name == "foodrescue-test"

    tool_list = await server.list_tools()
    tool_names = {t.name for t in tool_list}

    expected_tools = {
        "get_live_location",
        "find_nearby_organizations",
        "find_nearby_volunteers",
        "match_donation",
        "calculate_route",
        "calculate_transport_support",
        "calculate_task_metrics",
        "generate_handover_qr",
        "verify_handover_qr",
        "get_task_status",
        "get_donation",
        "get_foodrescue_system_status"
    }

    assert expected_tools.issubset(tool_names), f"Missing tools: {expected_tools - tool_names}"
    for tool in tool_list:
        assert tool.description, f"Tool '{tool.name}' is missing description"


@pytest.mark.asyncio
async def test_mcp_get_live_location_existing_and_missing():
    """Test retrieving real GPS coordinates and handling non-existent records without mock data."""
    phone = f"9477{uuid.uuid4().hex[:7]}"

    # Missing location should return not_found, never fabricated coordinates
    res_missing = await get_live_location(user_id=phone, role="donor")
    assert res_missing["status"] == "not_found"

    # Store user profile with live coordinates
    database.create_or_update_user(
        phone=phone,
        display_name="Kegalle Donor",
        user_role="donor",
        onboarding_completed=True,
        default_location="Kegalle",
        metadata={"latitude": 7.2512, "longitude": 80.3464, "district": "Kegalle"}
    )

    res_found = await get_live_location(user_id=phone, role="donor")
    assert res_found["status"] == "success"
    assert res_found["latitude"] == 7.2512
    assert res_found["longitude"] == 80.3464
    assert res_found["district"] == "Kegalle"
    assert "https://www.google.com/maps" in res_found["map_link"]


@pytest.mark.asyncio
async def test_mcp_matching_tools_real_data():
    """Test finding real nearby organizations and volunteers, and empty states."""
    test_id = uuid.uuid4().hex[:6]
    org_phone = f"947700{test_id}"
    vol_phone = f"947711{test_id}"

    # Register real records
    tools.register_organization(
        name="Kegalle Community Kitchen",
        location="Kegalle",
        service_area="Kegalle",
        accepted_food_types="All",
        phone=org_phone
    )
    tools.register_volunteer(
        name="Kamal Courier",
        service_area="Kegalle",
        phone=vol_phone,
        transport_mode="Motorbike"
    )

    # 1. Organizations matching
    orgs = await find_nearby_organizations(latitude=7.2512, longitude=80.3464, district="Kegalle")
    assert len(orgs) >= 1
    assert any(o.get("name") == "Kegalle Community Kitchen" or "Kegalle" in str(o) for o in orgs)

    # 2. Volunteers matching
    vols = await find_nearby_volunteers(latitude=7.2512, longitude=80.3464, district="Kegalle")
    assert len(vols) >= 1
    assert any(v.get("name") == "Kamal Courier" or v.get("phone") == vol_phone for v in vols)


@pytest.mark.asyncio
async def test_mcp_match_donation():
    """Test match_donation tool with real donation record."""
    donor_id = f"donor_{uuid.uuid4().hex[:6]}"
    don_raw = tools.create_donation(
        donor_id=donor_id,
        food_type="Vegetable Fried Rice",
        quantity=35,
        location="Kegalle"
    )
    don = json.loads(don_raw)
    don_id = don["donation_id"]

    match_res = await match_donation(don_id)
    assert match_res["status"] == "success"
    assert match_res["donation"]["id"] == don_id
    assert match_res["donation"]["food_type"] == "Vegetable Fried Rice"
    assert "matched_organizations" in match_res

    # Test invalid donation id
    invalid_res = await match_donation("invalid-donation-id-999")
    assert invalid_res["status"] == "not_found"


@pytest.mark.asyncio
async def test_mcp_calculate_route():
    """Test dynamic road routing tool between real Sri Lankan coordinates."""
    # Kegalle to Mawanella coordinates
    route = await calculate_route(
        pickup_latitude=7.2512,
        pickup_longitude=80.3464,
        delivery_latitude=7.2533,
        delivery_longitude=80.4467,
        vehicle_type="Motorbike"
    )

    assert route["status"] == "success"
    assert route["distance_km"] > 5.0
    assert route["duration_minutes"] > 0
    assert route["vehicle_type"] == "Motorbike"
    assert "https://www.google.com/maps" in route["route_url"]


@pytest.mark.asyncio
async def test_mcp_calculate_transport_support():
    """Test dynamic transport reimbursement calculation reading from configured settings."""
    res_bike = await calculate_transport_support(distance_km=10.0, vehicle_type="Motorbike")
    assert res_bike["status"] == "success"
    assert res_bike["currency"] == "LKR"
    assert res_bike["transport_support"] > 0
    assert res_bike["distance_km"] == 10.0

    res_car = await calculate_transport_support(distance_km=10.0, vehicle_type="Car")
    assert res_car["transport_support"] >= res_bike["transport_support"]


@pytest.mark.asyncio
async def test_mcp_calculate_task_metrics():
    """Test combined logistics metrics calculation."""
    donor_id = f"donor_{uuid.uuid4().hex[:6]}"
    don_raw = tools.create_donation(donor_id=donor_id, food_type="Bun & Pastry Boxes", quantity=40, location="Kegalle")
    don = json.loads(don_raw)

    org_phone = f"947733{uuid.uuid4().hex[:6]}"
    tools.register_organization(name="Mawanella Orphanage", location="Mawanella", service_area="Mawanella", accepted_food_types="All", phone=org_phone)
    org = database.get_organization_by_phone(org_phone)

    vol_phone = f"947744{uuid.uuid4().hex[:6]}"
    tools.register_volunteer(name="Sunil Courier", service_area="Kegalle", phone=vol_phone, transport_mode="Three-Wheeler")
    vol = database.get_volunteer_by_phone(vol_phone)

    metrics = await calculate_task_metrics(
        donation_id=don["donation_id"],
        organization_id=org["id"],
        volunteer_id=vol["id"]
    )

    assert metrics["status"] == "success"
    assert metrics["donation_id"] == don["donation_id"]
    assert metrics["distance_km"] > 0
    assert metrics["transport_support"] > 0
    assert metrics["currency"] == "LKR"
    assert metrics["pickup"]["location"] is not None
    assert metrics["delivery"]["location"] is not None


@pytest.mark.asyncio
async def test_mcp_qr_generation_and_verification_lifecycle():
    """Test full physical handover lifecycle (Pickup QR -> Verify -> Delivery QR -> Verify) through MCP tools."""
    donor_id = f"donor_{uuid.uuid4().hex[:6]}"
    don_raw = tools.create_donation(donor_id=donor_id, food_type="Biryani", quantity=25, location="Kegalle")
    don = json.loads(don_raw)

    org_phone = f"947755{uuid.uuid4().hex[:6]}"
    tools.register_organization(name="Kegalle Elders Home", location="Kegalle", service_area="Kegalle", accepted_food_types="All", phone=org_phone)
    org = database.get_organization_by_phone(org_phone)

    vol_phone = f"947766{uuid.uuid4().hex[:6]}"
    tools.register_volunteer(name="Nuwan Courier", service_area="Kegalle", phone=vol_phone, transport_mode="Motorbike")
    vol = database.get_volunteer_by_phone(vol_phone)

    task_raw = tools.create_pickup_task(
        donation_id=don["donation_id"],
        organization_id=org["id"],
        pickup_location="Kegalle",
        delivery_location="Kegalle"
    )
    task = json.loads(task_raw)
    task_id = task["task_id"]
    tools.assign_volunteer(task_id=task_id, volunteer_id=vol["id"])

    # 1. Generate Pickup QR
    pk_res = await generate_handover_qr(task_id=task_id, qr_type="pickup")
    assert pk_res["status"] == "success"
    pk_token = pk_res["token"]
    assert pk_token.startswith("FR-PK-")
    assert "https://" in pk_res["verification_url"]

    # 2. Verify Pickup QR (Doorstep scan)
    verif_pk = await verify_handover_qr(token=pk_token, volunteer_id=vol["id"], latitude=7.2512, longitude=80.3464)
    assert verif_pk["status"] == "success"
    assert verif_pk["new_status"] == "COLLECTED"

    # 3. Generate Delivery QR
    dl_res = await generate_handover_qr(task_id=task_id, qr_type="delivery")
    assert dl_res["status"] == "success"
    dl_token = dl_res["token"]
    assert dl_token.startswith("FR-DL-")

    # 4. Verify Delivery QR (Dropoff scan)
    verif_dl = await verify_handover_qr(token=dl_token, volunteer_id=vol["id"], latitude=7.2512, longitude=80.3464)
    assert verif_dl["status"] == "success"
    assert verif_dl["new_status"] in ["DELIVERED", "COMPLETED"]

    # 5. Re-verifying consumed token should fail
    fail_res = await verify_handover_qr(token=dl_token, volunteer_id=vol["id"])
    assert fail_res["status"] == "error"
    assert "already" in fail_res["message"].lower() or "expired" in fail_res["message"].lower() or "consumed" in fail_res["message"].lower() or "not active" in fail_res["message"].lower()


@pytest.mark.asyncio
async def test_mcp_task_status_and_donation_lookup():
    """Test get_task_status and get_donation MCP tools."""
    donor_id = f"donor_{uuid.uuid4().hex[:6]}"
    don_raw = tools.create_donation(donor_id=donor_id, food_type="Kottu Roti", quantity=15, location="Kegalle")
    don = json.loads(don_raw)
    don_id = don["donation_id"]

    # Test get_donation
    don_res = await get_donation(don_id)
    assert don_res["status"] == "success"
    assert don_res["donation"]["food_type"] == "Kottu Roti"
    assert don_res["donation"]["quantity"] == 15

    # Test missing donation
    assert (await get_donation("missing-id-123"))["status"] == "not_found"

    # Test missing task status
    assert (await get_task_status("missing-task-123"))["status"] == "not_found"


@pytest.mark.asyncio
async def test_mcp_system_status():
    """Test get_foodrescue_system_status reporting real subsystem states."""
    status = await get_foodrescue_system_status()
    assert status["status"] == "success"
    assert status["mcp_server"] == "active"
    assert "database" in status
    assert "routing_service" in status
    assert "qr_service" in status
    assert "whatsapp_integration" in status
    assert status["database"]["connected"] is True


@pytest.mark.asyncio
async def test_mcp_call_tool_client_interface():
    """Test invoking MCP tools directly through the MCPServer call_tool interface."""
    server = get_mcp_server()

    # Call calculate_transport_support via MCP protocol call_tool
    res = await server.call_tool("calculate_transport_support", {"distance_km": 12.5, "vehicle_type": "Motorbike"})
    assert not res.is_error
    data = None
    if res.content and len(res.content) > 0:
        try:
            data = json.loads(res.content[0].text)
        except Exception:
            data = res.structured_content
    else:
        data = res.structured_content

    assert data is not None
    assert data.get("status") == "success"
    assert data.get("distance_km") == 12.5
    assert data.get("transport_support") > 0
