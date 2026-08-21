import json
import os
import pytest
import database
import tools
from agentkernel.core import Runtime, Session
import app

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path):
    db_file = str(tmp_path / "foodrescue_test.db")
    os.environ["FOODRESCUE_DB_PATH"] = db_file
    database.DB_PATH = db_file
    database.setup_database()
    database.seed_test_data()
    yield
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass

def test_database_initialization_and_seeding():
    """Verify database setup and initial test seed data."""
    conn = database.get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM donors")
    assert cursor.fetchone()[0] >= 2
    
    cursor.execute("SELECT COUNT(*) FROM organizations")
    assert cursor.fetchone()[0] >= 2
    
    cursor.execute("SELECT COUNT(*) FROM volunteers")
    assert cursor.fetchone()[0] >= 2
    conn.close()

def test_database_donation_crud():
    """Verify donation repository CRUD operations in SQLite."""
    rec = database.create_donation_record(
        donation_id="don-test-crud",
        donor_id="d1",
        food_type="Vegetarian Meals",
        quantity=30,
        unit="boxes",
        dietary_info="Vegan, Nut-free",
        location="Colombo 3",
        available_from="10:00",
        deadline="19:00"
    )
    assert rec["id"] == "don-test-crud"
    assert rec["status"] == "AVAILABLE"
    assert rec["quantity"] == 30

    fetched = database.get_donation_record("don-test-crud")
    assert fetched is not None
    assert fetched["food_type"] == "Vegetarian Meals"
    assert fetched["donor_id"] == "d1"

    updated = database.update_donation_status_record("don-test-crud", "MATCHED")
    assert updated is True
    
    fetched_updated = database.get_donation_record("don-test-crud")
    assert fetched_updated["status"] == "MATCHED"

def test_create_donation_validation_missing_or_invalid_data():
    """Verify strict validation on missing or invalid donation data."""
    # 1. Negative quantity
    res1 = json.loads(tools.create_donation("d1", "Rice", -5, "kg", "Vegan", "Colombo", "10:00", "18:00"))
    assert res1["status"] == "error"
    assert "quantity must be greater than 0" in res1["message"]

    # 2. Zero quantity
    res2 = json.loads(tools.create_donation("d1", "Rice", 0, "kg", "Vegan", "Colombo", "10:00", "18:00"))
    assert res2["status"] == "error"
    assert "quantity must be greater than 0" in res2["message"]

    # 3. Non-numeric quantity
    res3 = json.loads(tools.create_donation("d1", "Rice", "invalid_num", "kg", "Vegan", "Colombo", "10:00", "18:00"))
    assert res3["status"] == "error"
    assert "valid positive number" in res3["message"]

    # 4. Missing / empty food_type
    res4 = json.loads(tools.create_donation("d1", "   ", 10, "kg", "Vegan", "Colombo", "10:00", "18:00"))
    assert res4["status"] == "error"
    assert "food_type is required" in res4["message"]

    # 5. Missing / empty location
    res5 = json.loads(tools.create_donation("d1", "Rice", 10, "kg", "Vegan", "", "10:00", "18:00"))
    assert res5["status"] == "error"
    assert "pickup location is required" in res5["message"]

    # 6. Missing / empty donor_id
    res6 = json.loads(tools.create_donation("", "Rice", 10, "kg", "Vegan", "Colombo", "10:00", "18:00"))
    assert res6["status"] == "error"
    assert "donor_id is required" in res6["message"]

    # 7. Missing / empty unit
    res7 = json.loads(tools.create_donation("d1", "Rice", 10, "  ", "Vegan", "Colombo", "10:00", "18:00"))
    assert res7["status"] == "error"
    assert "unit is required" in res7["message"]

    # 8. Missing / empty pickup_deadline
    res8 = json.loads(tools.create_donation("d1", "Rice", 10, "kg", "Vegan", "Colombo", "10:00", "   "))
    assert res8["status"] == "error"
    assert "pickup_deadline is required" in res8["message"]

    # Verify no records created in database after validation failures
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM donations")
    assert cursor.fetchone()[0] == 0
    conn.close()

def test_tools_deterministic_end_to_end_workflow():
    """Verify deterministic 10-step lifecycle and database consistency."""
    # Step 1: Create donation
    create_res = json.loads(tools.create_donation(
        donor_id="d1",
        food_type="Vegetarian Lunch Boxes",
        quantity=40,
        unit="boxes",
        dietary_information="Vegetarian, Halal",
        location="Colombo 3",
        available_from="12:00 PM",
        pickup_deadline="06:00 PM"
    ))
    assert create_res["status"] == "success"
    donation_id = create_res["donation_id"]
    assert donation_id.startswith("don-")
    assert create_res["donation_status"] == "AVAILABLE"

    # Verify SQLite state after creation
    db_don = database.get_donation_record(donation_id)
    assert db_don is not None
    assert db_don["status"] == "AVAILABLE"
    assert db_don["quantity"] == 40.0
    assert db_don["food_type"] == "Vegetarian Lunch Boxes"

    # Step 2: Find matching organizations
    orgs_res = json.loads(tools.find_matching_organizations("Vegetarian Lunch Boxes", "Colombo"))
    assert orgs_res["status"] == "success"
    assert orgs_res["count"] >= 1
    matched_org = orgs_res["organizations"][0]
    org_id = matched_org["id"]

    # Step 3: Accept donation
    accept_res = json.loads(tools.accept_donation(donation_id, org_id))
    assert accept_res["status"] == "success"
    assert accept_res["donation_status"] == "MATCHED"
    assert accept_res["donation_id"] == donation_id
    assert accept_res["organization_id"] == org_id

    # Verify SQLite state after accept
    db_don = database.get_donation_record(donation_id)
    assert db_don["status"] == "MATCHED"

    # Step 4: Find available volunteers
    vols_res = json.loads(tools.find_available_volunteers("Colombo"))
    assert vols_res["status"] == "success"
    assert vols_res["count"] >= 1
    volunteer_id = vols_res["volunteers"][0]["id"]

    # Step 5: Create pickup task
    task_res = json.loads(tools.create_pickup_task(
        donation_id=donation_id,
        organization_id=org_id,
        pickup_location="Colombo 3",
        delivery_location=matched_org["location"],
        scheduled_time="03:00 PM"
    ))
    assert task_res["status"] == "success"
    task_id = task_res["task_id"]
    assert task_id.startswith("task-")
    assert task_res["task_status"] == "PENDING"
    assert task_res["donation_status"] == "PICKUP_PENDING"

    # Verify SQLite task and donation state
    db_task = database.get_pickup_task_record(task_id)
    assert db_task is not None
    assert db_task["status"] == "PENDING"
    assert db_task["donation_id"] == donation_id
    assert database.get_donation_record(donation_id)["status"] == "PICKUP_PENDING"

    # Step 6: Assign volunteer
    assign_res = json.loads(tools.assign_volunteer(task_id, volunteer_id))
    assert assign_res["status"] == "success"
    assert assign_res["task_status"] == "ASSIGNED"
    assert assign_res["donation_status"] == "PICKUP_ASSIGNED"

    # Verify SQLite states after assignment
    db_task = database.get_pickup_task_record(task_id)
    db_don = database.get_donation_record(donation_id)
    assert db_task["status"] == "ASSIGNED"
    assert db_task["volunteer_id"] == volunteer_id
    assert db_don["status"] == "PICKUP_ASSIGNED"

    # Step 7: Update pickup lifecycle: EN_ROUTE -> COLLECTED -> DELIVERED
    update_res1 = json.loads(tools.update_pickup_status(task_id, "EN_ROUTE"))
    assert update_res1["status"] == "success"
    assert database.get_pickup_task_record(task_id)["status"] == "EN_ROUTE"

    update_res2 = json.loads(tools.update_pickup_status(task_id, "COLLECTED"))
    assert update_res2["status"] == "success"
    assert database.get_pickup_task_record(task_id)["status"] == "COLLECTED"
    assert database.get_donation_record(donation_id)["status"] == "COLLECTED"

    update_res3 = json.loads(tools.update_pickup_status(task_id, "DELIVERED"))
    assert update_res3["status"] == "success"
    assert database.get_pickup_task_record(task_id)["status"] == "DELIVERED"
    assert database.get_donation_record(donation_id)["status"] == "DELIVERED"

    # Verify linked tasks query
    linked_tasks = database.get_pickup_tasks_by_donation_id(donation_id)
    assert len(linked_tasks) == 1
    assert linked_tasks[0]["id"] == task_id
    assert linked_tasks[0]["status"] == "DELIVERED"

def test_pickup_cancellation_and_failure_flow():
    """Verify pickup cancellation and failure handling."""
    create_res = json.loads(tools.create_donation("d1", "Bread", 10, "loaves", "Standard", "Colombo 4", "08:00 AM", "12:00 PM"))
    donation_id = create_res["donation_id"]
    
    task_res = json.loads(tools.create_pickup_task(donation_id, "o1", "Colombo 4", "Colombo 7", "09:00 AM"))
    task_id = task_res["task_id"]

    cancel_res = json.loads(tools.update_pickup_status(task_id, "CANCELLED"))
    assert cancel_res["status"] == "success"
    assert database.get_pickup_task_record(task_id)["status"] == "CANCELLED"
    assert database.get_donation_record(donation_id)["status"] == "CANCELLED"

def test_matching_organizations_and_volunteers_criteria():
    """Verify organization and volunteer matching filtering and ranking."""
    orgs_res = json.loads(tools.find_matching_organizations("bakery items", "Colombo 4"))
    assert orgs_res["status"] == "success"
    assert orgs_res["count"] >= 1
    
    vols_res = json.loads(tools.find_available_volunteers("Colombo 3"))
    assert vols_res["status"] == "success"
    assert vols_res["count"] >= 1

def test_notifications_persisted_in_database():
    """Verify notifications are logged into SQLite during operations."""
    create_res = json.loads(tools.create_donation("d1", "Meals", 15, "packets", "Halal", "Colombo", "11:00 AM", "03:00 PM"))
    donation_id = create_res["donation_id"]
    
    donor_notifs = database.get_notifications_for_recipient("d1")
    assert len(donor_notifs) >= 1
    assert donation_id in donor_notifs[0]["message"]

def test_session_context_management():
    """Verify storing, retrieving, and clearing session context memory."""
    session = Session("test-session-1")
    token = Session.current_session.set(session)
    try:
        # Pre-set context
        set_res = json.loads(tools.set_session_context(
            donor_id="d2",
            location="Colombo 4",
            food_type="Pastries",
            quantity=25,
            unit="boxes",
            pickup_deadline="05:00 PM"
        ))
        assert set_res["status"] == "success"
        assert set_res["session_context"]["current_donor_id"] == "d2"
        assert set_res["session_context"]["current_location"] == "Colombo 4"

        # Inspect context
        ctx_res = json.loads(tools.get_session_context())
        assert ctx_res["status"] == "success"
        assert ctx_res["session_context"]["current_food_type"] == "Pastries"
        assert ctx_res["session_context"]["current_quantity"] == 25.0

        # Clear context
        clear_res = json.loads(tools.clear_session_context())
        assert clear_res["status"] == "success"
        
        ctx_after = json.loads(tools.get_session_context())
        assert len(ctx_after["session_context"]) == 0
    finally:
        Session.current_session.reset(token)

@pytest.mark.asyncio
async def test_multi_turn_session_fallback_workflow():
    """Verify multi-turn session workflow where subsequent tools resolve context from session memory."""
    session = Session("session-multi-turn-test")
    async with session:
        # Turn 1: User says "I have 40 vegetarian meal boxes in Colombo"
        t1_res = json.loads(tools.create_donation(
            donor_id="d1",
            food_type="Vegetarian meal boxes",
            quantity=40,
            unit="boxes",
            dietary_information="Vegetarian",
            location="Colombo 3",
            available_from="10:00 AM",
            pickup_deadline="04:00 PM"
        ))
        assert t1_res["status"] == "success"
        don_id = t1_res["donation_id"]

        # Turn 2: User says "They need to be collected before 7 PM"
        # Tool updates active donation without needing donation_id passed explicitly
        t2_res = json.loads(tools.update_donation_details(pickup_deadline="07:00 PM"))
        assert t2_res["status"] == "success"
        assert t2_res["donation_id"] == don_id
        assert t2_res["donation"]["pickup_deadline"] == "07:00 PM"
        # Verify in SQLite database
        db_don = database.get_donation_record(don_id)
        assert db_don["pickup_deadline"] == "07:00 PM"

        # Turn 3: User says "Match an organization"
        # Tool searches matching orgs using current_food_type and current_location from session context
        t3_res = json.loads(tools.find_matching_organizations())
        assert t3_res["status"] == "success"
        assert t3_res["count"] >= 1
        matched_org_id = t3_res["organizations"][0]["id"]

        # Accept donation using matched organization (donation_id inferred from session)
        t3_accept = json.loads(tools.accept_donation(organization_id=matched_org_id))
        assert t3_accept["status"] == "success"
        assert t3_accept["donation_id"] == don_id

        # Turn 4: User says "Find an available volunteer and schedule pickup"
        t4_vols = json.loads(tools.find_available_volunteers())
        assert t4_vols["status"] == "success"
        assert t4_vols["count"] >= 1
        vol_id = t4_vols["volunteers"][0]["id"]

        # Create pickup task using inferred donation, organization, and location
        t4_task = json.loads(tools.create_pickup_task())
        assert t4_task["status"] == "success"
        task_id = t4_task["task_id"]

        # Assign volunteer using inferred task_id
        t4_assign = json.loads(tools.assign_volunteer(volunteer_id=vol_id))
        assert t4_assign["status"] == "success"
        assert t4_assign["task_id"] == task_id
        assert t4_assign["donation_status"] == "PICKUP_ASSIGNED"

        # Turn 5: User says "Mark as delivered"
        t5_deliv = json.loads(tools.update_pickup_status(status="DELIVERED"))
        assert t5_deliv["status"] == "success"
        assert t5_deliv["task_id"] == task_id
        assert t5_deliv["task_status"] == "DELIVERED"

        # Verify final state in SQLite database
        assert database.get_donation_record(don_id)["status"] == "DELIVERED"
        assert database.get_pickup_task_record(task_id)["status"] == "DELIVERED"

def test_update_donation_details_and_validation():
    """Verify update_donation_details validates inputs and modifies SQLite records."""
    session = Session("test-update-session")
    token = Session.current_session.set(session)
    try:
        create_res = json.loads(tools.create_donation("d1", "Rice", 10, "kg", "Vegan", "Colombo", "10:00 AM", "02:00 PM"))
        don_id = create_res["donation_id"]

        # 1. Valid update of quantity and deadline
        up1 = json.loads(tools.update_donation_details(donation_id=don_id, quantity=20, pickup_deadline="06:00 PM"))
        assert up1["status"] == "success"
        assert up1["donation"]["quantity"] == 20.0
        assert up1["donation"]["pickup_deadline"] == "06:00 PM"
        assert database.get_donation_record(don_id)["quantity"] == 20.0

        # 2. Invalid negative quantity
        up2 = json.loads(tools.update_donation_details(donation_id=don_id, quantity=-5))
        assert up2["status"] == "error"
        assert "quantity must be greater than 0" in up2["message"]

        # 3. Non-numeric quantity
        up3 = json.loads(tools.update_donation_details(donation_id=don_id, quantity="invalid"))
        assert up3["status"] == "error"
        assert "valid positive number" in up3["message"]

        # 4. Non-existent donation ID
        up4 = json.loads(tools.update_donation_details(donation_id="don-nonexistent", quantity=15))
        assert up4["status"] == "error"
        assert "not found" in up4["message"]
    finally:
        Session.current_session.reset(token)

def test_session_state_and_sqlite_separation():
    """Verify clear separation between transient session memory and persistent SQLite state."""
    session = Session("test-separation-session")
    token = Session.current_session.set(session)
    try:
        # Create donation in session
        create_res = json.loads(tools.create_donation("d1", "Bread", 30, "loaves", "None", "Colombo 3", "09:00 AM", "03:00 PM"))
        don_id = create_res["donation_id"]
        
        # Verify both session memory and SQLite have the record
        ctx = json.loads(tools.get_session_context())
        assert ctx["active_donation_id"] == don_id
        assert database.get_donation_record(don_id) is not None

        # Clear session memory
        tools.clear_session_context()
        ctx_cleared = json.loads(tools.get_session_context())
        assert ctx_cleared["active_donation_id"] is None
        assert len(ctx_cleared["session_context"]) == 0

        # Verify SQLite business record STILL EXISTS and is intact
        db_record = database.get_donation_record(don_id)
        assert db_record is not None
        assert db_record["id"] == don_id
        assert db_record["food_type"] == "Bread"
        assert db_record["quantity"] == 30.0
    finally:
        Session.current_session.reset(token)

def test_invalid_status_transitions_and_nonexistent_records():
    """Verify robust error handling for invalid statuses and non-existent IDs."""
    # Non-existent donation lookup
    res1 = json.loads(tools.get_donation("don-nonexistent"))
    assert res1["status"] == "error"

    # Invalid donation status
    res2 = json.loads(tools.update_donation_status("don-nonexistent", "FLYING"))
    assert res2["status"] == "error"
    assert "Invalid status" in res2["message"]

    # Invalid pickup status
    res3 = json.loads(tools.update_pickup_status("task-nonexistent", "TELEPORTED"))
    assert res3["status"] == "error"
    assert "Invalid pickup status" in res3["message"]

    # Accept non-existent donation
    res4 = json.loads(tools.accept_donation("don-nonexistent", "o1"))
    assert res4["status"] == "error"

    # Assign volunteer with non-existent task
    res5 = json.loads(tools.assign_volunteer("task-nonexistent", "v1"))
    assert res5["status"] == "error"

    # Assign non-existent volunteer
    create_res = json.loads(tools.create_donation("d1", "Meals", 10, "boxes", "None", "Colombo", "10:00 AM", "02:00 PM"))
    task_res = json.loads(tools.create_pickup_task(create_res["donation_id"], "o1", "Colombo", "Colombo", "11:00 AM"))
    res6 = json.loads(tools.assign_volunteer(task_res["task_id"], "vol-nonexistent"))
    assert res6["status"] == "error"

def test_agentkernel_adk_agent_configured():
    """Verify the Agent Kernel agent and module configuration."""
    assert app.foodrescue_coordinator.name == "foodrescue_coordinator"
    assert "gemini" in app.foodrescue_coordinator.model.lower()
    assert len(app.foodrescue_coordinator.tools) >= 21
    
    # Verify canonical coordinator registered in runtime
    runtime = Runtime.current()
    registered_agents = runtime.agents()
    assert "foodrescue_coordinator" in registered_agents
    assert registered_agents["foodrescue_coordinator"].name == "foodrescue_coordinator"

def test_rest_api_health_endpoint():
    """Verify GET /health returns 200 OK and status ok."""
    from fastapi.testclient import TestClient
    from agentkernel.api import RESTAPI, AgentRESTRequestHandler

    handler = AgentRESTRequestHandler()
    api_app = RESTAPI._create_app(routers=[handler.get_router()])
    client = TestClient(api_app)

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_rest_api_list_agents_endpoint():
    """Verify GET /api/v1/agents lists foodrescue_coordinator."""
    from fastapi.testclient import TestClient
    from agentkernel.api import RESTAPI, AgentRESTRequestHandler

    handler = AgentRESTRequestHandler()
    api_app = RESTAPI._create_app(routers=[handler.get_router()])
    client = TestClient(api_app)

    response = client.get("/api/v1/agents")
    assert response.status_code == 200
    data = response.json()
    assert "agents" in data
    assert "foodrescue_coordinator" in data["agents"]

def test_rest_api_chat_validation_missing_fields():
    """Verify POST /api/v1/chat validates missing session_id and prompt."""
    from fastapi.testclient import TestClient
    from agentkernel.api import RESTAPI, AgentRESTRequestHandler

    handler = AgentRESTRequestHandler()
    api_app = RESTAPI._create_app(routers=[handler.get_router()])
    client = TestClient(api_app)

    # 1. Missing session_id -> 400 Bad Request
    res_no_session = client.post(
        "/api/v1/chat",
        json={"agent": "foodrescue_coordinator", "prompt": "Hello"}
    )
    assert res_no_session.status_code == 400
    assert "session_id" in res_no_session.json()["detail"]["error"]

    # 2. Missing prompt -> 422 Unprocessable Entity (Pydantic validation)
    res_no_prompt = client.post(
        "/api/v1/chat",
        json={"agent": "foodrescue_coordinator", "session_id": "session-test-val"}
    )
    assert res_no_prompt.status_code == 422

def test_rest_api_chat_invalid_or_missing_agent_handling():
    """Verify POST /api/v1/chat handles missing or invalid agent specification gracefully."""
    from fastapi.testclient import TestClient
    from agentkernel.api import RESTAPI, AgentRESTRequestHandler

    handler = AgentRESTRequestHandler()
    api_app = RESTAPI._create_app(routers=[handler.get_router()])
    client = TestClient(api_app)

    # 1. Invalid / Non-existent agent
    res_invalid_agent = client.post(
        "/api/v1/chat",
        json={"agent": "nonexistent_agent", "prompt": "Hello", "session_id": "session-inv-001"}
    )
    assert res_invalid_agent.status_code == 400
    assert "No agent available" in str(res_invalid_agent.json())


def test_rest_api_chat_success_response():
    """Verify POST /api/v1/chat returns 200 with result and session_id."""
    from fastapi.testclient import TestClient
    from agentkernel.api import RESTAPI, AgentRESTRequestHandler
    from agentkernel.core import AgentService
    from agentkernel.core.model import AgentReplyText
    from unittest.mock import AsyncMock, patch

    handler = AgentRESTRequestHandler()
    api_app = RESTAPI._create_app(routers=[handler.get_router()])
    client = TestClient(api_app)

    with patch.object(AgentService, "run_multi", new=AsyncMock(return_value=AgentReplyText(response="Donation don-1234 created successfully."))):
        response = client.post(
            "/api/v1/chat",
            json={
                "agent": "foodrescue_coordinator",
                "prompt": "I have 40 vegetarian lunch boxes in Colombo 3.",
                "session_id": "session-rest-001",
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "session-rest-001"
        assert data["result"] == "Donation don-1234 created successfully."

def test_rest_api_multi_turn_session_continuity():
    """Verify repeated REST chat requests with the same session_id preserve working memory."""
    from fastapi.testclient import TestClient
    from agentkernel.api import RESTAPI, AgentRESTRequestHandler
    from agentkernel.core import Runtime
    from agentkernel.core.model import AgentReplyText
    from unittest.mock import patch

    handler = AgentRESTRequestHandler()
    api_app = RESTAPI._create_app(routers=[handler.get_router()])
    client = TestClient(api_app)

    agent = Runtime.current().agents()["foodrescue_coordinator"]
    sess_id = "session-continuity-101"

    # Turn 1: Coordinator stores active donation ID in session cache
    async def mock_turn_1(ag, sess, reqs):
        cache = sess.get_non_volatile_cache()
        cache.set("current_donation_id", "don-phase3-turn1")
        cache.set("current_location", "Colombo 3")
        return AgentReplyText(response="Created donation don-phase3-turn1 at Colombo 3")

    with patch.object(agent.runner, "run", side_effect=mock_turn_1):
        res1 = client.post(
            "/api/v1/chat",
            json={
                "agent": "foodrescue_coordinator",
                "prompt": "I have 40 vegetarian meals in Colombo 3",
                "session_id": sess_id,
            },
        )
        assert res1.status_code == 200
        assert res1.json()["session_id"] == sess_id
        assert "don-phase3-turn1" in res1.json()["result"]

    # Turn 2: Coordinator retrieves active donation ID from session cache without user providing it
    async def mock_turn_2(ag, sess, reqs):
        cache = sess.get_non_volatile_cache()
        don_id = cache.get("current_donation_id")
        loc = cache.get("current_location")
        cache.set("current_pickup_deadline", "07:00 PM")
        return AgentReplyText(response=f"Updated deadline for donation {don_id} at {loc} to 07:00 PM")

    with patch.object(agent.runner, "run", side_effect=mock_turn_2):
        res2 = client.post(
            "/api/v1/chat",
            json={
                "agent": "foodrescue_coordinator",
                "prompt": "They need to be collected before 7 PM",
                "session_id": sess_id,
            },
        )
        assert res2.status_code == 200
        assert res2.json()["session_id"] == sess_id
        assert "don-phase3-turn1" in res2.json()["result"]
        assert "Colombo 3" in res2.json()["result"]
        assert "07:00 PM" in res2.json()["result"]

def test_rest_api_session_isolation():
    """Verify distinct session_id values maintain isolated conversation contexts."""
    from fastapi.testclient import TestClient
    from agentkernel.api import RESTAPI, AgentRESTRequestHandler
    from agentkernel.core import Runtime
    from agentkernel.core.model import AgentReplyText
    from unittest.mock import patch

    handler = AgentRESTRequestHandler()
    api_app = RESTAPI._create_app(routers=[handler.get_router()])
    client = TestClient(api_app)

    agent = Runtime.current().agents()["foodrescue_coordinator"]

    async def mock_turn(ag, sess, reqs):
        cache = sess.get_non_volatile_cache()
        existing_don = cache.get("current_donation_id")
        if not existing_don:
            new_id = f"don-{sess.id}"
            cache.set("current_donation_id", new_id)
            return AgentReplyText(response=f"New donation {new_id} for session {sess.id}")
        return AgentReplyText(response=f"Existing donation {existing_don} for session {sess.id}")

    with patch.object(agent.runner, "run", side_effect=mock_turn):
        # Session A
        res_a = client.post(
            "/api/v1/chat",
            json={"agent": "foodrescue_coordinator", "prompt": "Init A", "session_id": "session-A"}
        )
        assert res_a.status_code == 200
        assert "don-session-A" in res_a.json()["result"]

        # Session B (must not see Session A's donation)
        res_b = client.post(
            "/api/v1/chat",
            json={"agent": "foodrescue_coordinator", "prompt": "Init B", "session_id": "session-B"}
        )
        assert res_b.status_code == 200
        assert "don-session-B" in res_b.json()["result"]

def test_web_ui_html_endpoint():
    """Verify GET / and GET /ui return the FoodRescue Web Interface HTML."""
    from fastapi.testclient import TestClient
    from agentkernel.api import RESTAPI, AgentRESTRequestHandler
    import api_routes

    handler = AgentRESTRequestHandler()
    api_app = RESTAPI._create_app(routers=[handler.get_router(), api_routes.get_router()])
    client = TestClient(api_app)

    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "FoodRescue" in res_root.text
    assert "app.js" in res_root.text
    assert "styles.css" in res_root.text

    res_ui = client.get("/ui")
    assert res_ui.status_code == 200
    assert "FoodRescue" in res_ui.text

def test_web_api_stats_and_entities():
    """Verify custom API endpoints return dashboard stats, organizations, volunteers, and pickups."""
    from fastapi.testclient import TestClient
    from agentkernel.api import RESTAPI, AgentRESTRequestHandler
    import api_routes

    handler = AgentRESTRequestHandler()
    api_app = RESTAPI._create_app(routers=[handler.get_router(), api_routes.get_router()])
    client = TestClient(api_app)

    # 1. Stats
    res_stats = client.get("/api/stats")
    assert res_stats.status_code == 200
    stats = res_stats.json()["stats"]
    assert "total_donations" in stats
    assert "total_organizations" in stats
    assert "total_volunteers" in stats

    # 2. Organizations
    res_orgs = client.get("/api/organizations")
    assert res_orgs.status_code == 200
    orgs = res_orgs.json()["organizations"]
    assert len(orgs) >= 2
    assert any(o["id"] == "o1" for o in orgs)

    # 3. Volunteers
    res_vols = client.get("/api/volunteers")
    assert res_vols.status_code == 200
    vols = res_vols.json()["volunteers"]
    assert len(vols) >= 2
    assert any(v["id"] == "v1" for v in vols)

    # 4. Pickups
    res_pickups = client.get("/api/pickups")
    assert res_pickups.status_code == 200
    assert "pickup_tasks" in res_pickups.json()

    # 5. Notifications
    res_notifs = client.get("/api/notifications")
    assert res_notifs.status_code == 200
    assert "notifications" in res_notifs.json()

def test_web_api_donation_details_and_filter():
    """Verify /api/donations and /api/donations/{id} endpoints."""
    from fastapi.testclient import TestClient
    from agentkernel.api import RESTAPI, AgentRESTRequestHandler
    import api_routes

    # Create a fresh donation record
    don = database.create_donation_record(
        "don-web-test-01", "d1", "Test Lunch", 15, "boxes", "Veg", "Colombo 3", "10:00 AM", "02:00 PM"
    )

    handler = AgentRESTRequestHandler()
    api_app = RESTAPI._create_app(routers=[handler.get_router(), api_routes.get_router()])
    client = TestClient(api_app)

    # List all
    res_all = client.get("/api/donations")
    assert res_all.status_code == 200
    donations = res_all.json()["donations"]
    assert any(d["id"] == "don-web-test-01" for d in donations)

    # Filter by AVAILABLE
    res_filter = client.get("/api/donations?status=AVAILABLE")
    assert res_filter.status_code == 200
    filtered = res_filter.json()["donations"]
    assert all(d["status"] == "AVAILABLE" for d in filtered)

    # Detail
    res_detail = client.get("/api/donations/don-web-test-01")
    assert res_detail.status_code == 200
    data = res_detail.json()
    assert data["donation"]["id"] == "don-web-test-01"
    assert data["donor"]["id"] == "d1"

    # Non-existent detail
    res_404 = client.get("/api/donations/don-not-existing")
    assert res_404.status_code == 404




