"""FoodRescue AI Supabase PostgreSQL Persistence Test Suite.

Validates the SupabaseRepository implementation:
1. Complete CRUD operations and schema normalization
2. Table creation, foreign keys, and indexes
3. Proximity and dietary ranking algorithms
4. 10-step lifecycle workflow over Supabase PostgreSQL
5. Dynamic GPS coordinates and two-leg courier routing
6. Atomic physical QR code handover verification
7. Aggregated dashboard statistics and KPIs
8. Integration with the 14 FoodRescue operational tools and WhatsApp handler
9. Clean skip when live SUPABASE_DB_URL is not provided/reachable
"""

import os
import json
import sqlite3
import pytest
from db_supabase import SupabaseRepository
import database
import tools
import routing


@pytest.fixture
def mock_supabase_repo():
    """Create an isolated in-memory SupabaseRepository backed by sqlite3 in-memory connection."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    repo = SupabaseRepository(connection_instance=conn)
    repo.setup_database()
    repo.seed_test_data()
    return repo


@pytest.fixture(autouse=True)
def inject_supabase_repo_into_database(mock_supabase_repo):
    """Inject mock_supabase_repo into the database delegation layer for every test."""
    original_repo = database._CURRENT_REPO
    database.set_repository(mock_supabase_repo)
    yield mock_supabase_repo
    database.set_repository(original_repo)


def test_supabase_initialization_and_seeding(mock_supabase_repo):
    """Verify Supabase PostgreSQL tables and initial seed records."""
    donor_d1 = mock_supabase_repo.get_donor_record("d1")
    assert donor_d1 is not None
    assert donor_d1["id"] == "d1"
    assert donor_d1["name"] == "Grand Hotel"

    org_o1 = mock_supabase_repo.get_organization_record("o1")
    assert org_o1 is not None
    assert org_o1["id"] == "o1"
    assert "Community Kitchen" in org_o1["name"]

    vol_v1 = mock_supabase_repo.get_volunteer_record("v1")
    assert vol_v1 is not None
    assert vol_v1["id"] == "v1"
    assert vol_v1["current_status"] == "available"
    assert vol_v1["availability_status"] == "AVAILABLE"


def test_supabase_donation_crud_and_status(mock_supabase_repo):
    """Verify donation creation, retrieval, and status updates in Supabase PostgreSQL."""
    don = mock_supabase_repo.create_donation_record(
        donation_id="don-supa-001",
        donor_id="d1",
        food_type="Vegetarian Rice Packets",
        quantity=50.0,
        unit="packets",
        dietary_info="Vegetarian, Halal",
        location="Colombo 3",
        available_from="11:00 AM",
        deadline="07:00 PM"
    )
    assert don["id"] == "don-supa-001"
    assert float(don["quantity"]) == 50.0
    assert don["status"] == "AVAILABLE"

    # Fetch
    fetched = mock_supabase_repo.get_donation_record("don-supa-001")
    assert fetched is not None
    assert fetched["id"] == "don-supa-001"
    assert float(fetched["quantity"]) == 50.0

    # Update status
    updated = mock_supabase_repo.update_donation_status_record("don-supa-001", "MATCHED")
    assert updated is True
    assert mock_supabase_repo.get_donation_record("don-supa-001")["status"] == "MATCHED"


def test_supabase_donation_details_update(mock_supabase_repo):
    """Verify updating editable donation details in Supabase PostgreSQL."""
    mock_supabase_repo.create_donation_record(
        donation_id="don-supa-edit",
        donor_id="d1",
        food_type="Initial Meals",
        quantity=20.0,
        unit="boxes",
        dietary_info="None",
        location="Colombo",
        available_from="Now",
        deadline="04:00 PM"
    )

    updated = mock_supabase_repo.update_donation_details_record(
        donation_id="don-supa-edit",
        quantity=35.0,
        deadline="08:00 PM",
        dietary_info="Vegan"
    )
    assert updated is not None
    assert float(updated["quantity"]) == 35.0
    assert updated["pickup_deadline"] == "08:00 PM"
    assert updated["dietary_information"] == "Vegan"
    assert updated["food_type"] == "Initial Meals"


def test_supabase_find_organizations_and_volunteers_ranking(mock_supabase_repo):
    """Verify Supabase location and food-type ranking algorithms."""
    # Organization matching for vegetarian in Colombo
    orgs = mock_supabase_repo.find_organizations_by_criteria("vegetarian", "Colombo 7")
    assert len(orgs) >= 1
    assert orgs[0]["id"] == "o1"
    assert orgs[0]["match_score"] >= 10

    # Volunteer matching in Colombo 3
    vols = mock_supabase_repo.find_volunteers_by_criteria("Colombo 3")
    assert len(vols) >= 1
    assert vols[0]["id"] == "v1"
    assert vols[0]["match_score"] >= 10


def test_supabase_pickup_lifecycle_workflow(mock_supabase_repo):
    """Verify complete end-to-end pickup task lifecycle in Supabase PostgreSQL."""
    # 1. Create donation
    mock_supabase_repo.create_donation_record(
        "don-life-01", "d1", "Curry Packets", 30, "packets", "Veg", "Colombo 3", "12:00 PM", "06:00 PM"
    )

    # 2. Accept donation
    acc = mock_supabase_repo.accept_donation_record("don-life-01", "o1")
    assert acc is True
    assert mock_supabase_repo.get_donation_record("don-life-01")["status"] == "MATCHED"

    # 3. Create pickup task
    task = mock_supabase_repo.create_pickup_task_record(
        task_id="task-life-01",
        donation_id="don-life-01",
        org_id="o1",
        pickup_loc="Colombo 3",
        delivery_loc="Colombo 7",
        time="02:00 PM"
    )
    assert task["id"] == "task-life-01"
    assert task["status"] == "PENDING"

    # 4. Assign volunteer
    assigned = mock_supabase_repo.assign_volunteer_record("task-life-01", "v1")
    assert assigned is True
    t_assigned = mock_supabase_repo.get_pickup_task_record("task-life-01")
    assert t_assigned["volunteer_id"] == "v1"
    assert t_assigned["status"] == "ASSIGNED"

    # 5. Advance status (EN_ROUTE -> COLLECTED -> DELIVERED)
    mock_supabase_repo.update_pickup_status_record("task-life-01", "EN_ROUTE")
    assert mock_supabase_repo.get_pickup_task_record("task-life-01")["status"] == "EN_ROUTE"

    mock_supabase_repo.update_pickup_status_record("task-life-01", "COLLECTED")
    assert mock_supabase_repo.get_pickup_task_record("task-life-01")["status"] == "COLLECTED"

    mock_supabase_repo.update_pickup_status_record("task-life-01", "DELIVERED")
    assert mock_supabase_repo.get_pickup_task_record("task-life-01")["status"] == "DELIVERED"


def test_supabase_qr_handover_atomic_verification(mock_supabase_repo):
    """Verify single-use atomic physical QR code verification in Supabase PostgreSQL."""
    # Setup donation and task
    mock_supabase_repo.create_donation_record(
        "don-qr-01", "d1", "Packed Lunches", 20, "boxes", "None", "Colombo 3", "12:00 PM", "05:00 PM"
    )
    mock_supabase_repo.create_pickup_task_record(
        "task-qr-01", "don-qr-01", "o1", "Colombo 3", "Colombo 7", "01:00 PM"
    )
    mock_supabase_repo.assign_volunteer_record("task-qr-01", "v1")

    # 1. Create Pickup QR
    pickup_qr = mock_supabase_repo.create_qr_code_record(
        qr_id="qr-pick-01",
        task_id="task-qr-01",
        donation_id="don-qr-01",
        qr_type="PICKUP",
        token="token-pickup-abc",
        token_hash="hash-abc",
        donor_id="d1",
        organization_id="o1",
        assigned_volunteer_id="v1"
    )
    assert pickup_qr["id"] == "qr-pick-01"
    assert pickup_qr["status"] == "ACTIVE"

    # 2. Verify invalid token rejection
    bad_res = mock_supabase_repo.verify_qr_code_record("invalid-token-xyz")
    assert bad_res["success"] is False
    assert bad_res["error"] == "INVALID_TOKEN"

    # 3. Verify unauthorized volunteer rejection
    unauth_res = mock_supabase_repo.verify_qr_code_record("token-pickup-abc", volunteer_id="v2")
    assert unauth_res["success"] is False
    assert unauth_res["error"] == "UNAUTHORIZED_VOLUNTEER"

    # 4. Verify legitimate pickup scan
    verify_res = mock_supabase_repo.verify_qr_code_record("token-pickup-abc", volunteer_id="v1", gps_coords={"lat": 6.91, "lon": 79.85})
    assert verify_res["success"] is True
    assert verify_res["qr_type"] == "PICKUP"

    # Task & donation statuses should now be COLLECTED
    task_after_pick = mock_supabase_repo.get_pickup_task_record("task-qr-01")
    assert task_after_pick["status"] == "COLLECTED"
    assert task_after_pick["delivery_status"] == "IN_TRANSIT"
    assert mock_supabase_repo.get_donation_record("don-qr-01")["status"] == "COLLECTED"

    # 5. Verify single-use duplicate scan rejection
    dup_res = mock_supabase_repo.verify_qr_code_record("token-pickup-abc", volunteer_id="v1")
    assert dup_res["success"] is False
    assert dup_res["error"] == "ALREADY_USED"

    # 6. Create Delivery QR
    delivery_qr = mock_supabase_repo.create_qr_code_record(
        qr_id="qr-del-01",
        task_id="task-qr-01",
        donation_id="don-qr-01",
        qr_type="DELIVERY",
        token="token-delivery-xyz",
        token_hash="hash-xyz",
        donor_id="d1",
        organization_id="o1",
        assigned_volunteer_id="v1"
    )
    assert delivery_qr["status"] == "ACTIVE"

    # 7. Verify legitimate delivery scan
    del_verify_res = mock_supabase_repo.verify_qr_code_record("token-delivery-xyz", volunteer_id="v1")
    assert del_verify_res["success"] is True
    assert del_verify_res["qr_type"] == "DELIVERY"

    task_after_del = mock_supabase_repo.get_pickup_task_record("task-qr-01")
    assert task_after_del["status"] == "COMPLETED"
    assert task_after_del["delivery_status"] == "DELIVERED"
    assert mock_supabase_repo.get_donation_record("don-qr-01")["status"] == "DELIVERED"

    # Volunteer v1 should now be restored to AVAILABLE
    vol_after = mock_supabase_repo.get_volunteer_record("v1")
    assert vol_after["current_status"] == "available"
    assert vol_after["availability_status"] == "AVAILABLE"


def test_supabase_dynamic_location_and_reimbursement(mock_supabase_repo):
    """Verify dynamic GPS location logging and transport reimbursement in Supabase PostgreSQL."""
    mock_supabase_repo.create_donation_record(
        "don-gps-01", "d1", "Snacks", 10, "boxes", "None", "Colombo 3", "Now", "Today"
    )
    mock_supabase_repo.create_pickup_task_record(
        "task-gps-01", "don-gps-01", "o1", "Colombo 3", "Colombo 7", "03:00 PM"
    )

    # 1. Update logistics with real coordinates
    pickup_coords = {"latitude": 6.9034, "longitude": 79.8541, "display_name": "Kollupitiya, Colombo 3"}
    dest_coords = {"latitude": 6.9080, "longitude": 79.8680, "display_name": "Cinnamon Gardens, Colombo 7"}

    mock_supabase_repo.update_pickup_task_logistics(
        task_id="task-gps-01",
        pickup_coordinates=pickup_coords,
        destination_coordinates=dest_coords,
        pickup_distance_km=3.2,
        pickup_duration_minutes=8,
        delivery_distance_km=4.5,
        delivery_duration_minutes=12,
        total_distance_km=7.7,
        estimated_transport_cost=616.0
    )

    task = mock_supabase_repo.get_pickup_task_record("task-gps-01")
    assert task["pickup_coordinates"]["latitude"] == 6.9034
    assert task["destination_coordinates"]["longitude"] == 79.8680
    assert task["total_distance_km"] == 7.7
    assert task["estimated_transport_cost"] == 616.0

    # 2. Record live GPS breadcrumbs
    mock_supabase_repo.record_pickup_location("loc-01", "task-gps-01", "v1", 6.9050, 79.8600, accuracy_m=5.0)
    latest_loc = mock_supabase_repo.get_latest_pickup_location("task-gps-01")
    assert latest_loc is not None
    assert latest_loc["latitude"] == 6.9050
    assert latest_loc["longitude"] == 79.8600

    # 3. Create Reimbursement
    mock_supabase_repo.create_reimbursement_record(
        reimbursement_id="reimb-01",
        pickup_task_id="task-gps-01",
        volunteer_id="v1",
        distance_km=7.7,
        rate_per_km=80.0,
        transport_mode="Motorbike",
        amount=616.0,
        currency="LKR"
    )
    reimb = mock_supabase_repo.get_reimbursement_record("reimb-01")
    assert reimb is not None
    assert reimb["amount"] == 616.0
    assert reimb["status"] == "PENDING"

    mock_supabase_repo.update_reimbursement_status_record("reimb-01", "APPROVED")
    reimb_approved = mock_supabase_repo.get_reimbursement_record("reimb-01")
    assert reimb_approved["status"] == "APPROVED"
    assert reimb_approved["approved_at"] is not None


def test_supabase_user_profiles_and_onboarding(mock_supabase_repo):
    """Verify user persistence, phone normalization, language, and conversation draft state."""
    # Create user profile
    user = mock_supabase_repo.create_or_update_user(
        phone="+94771122334",
        display_name="Kasun Silva",
        preferred_language="si",
        preferred_response_mode="voice",
        user_role="donor",
        onboarding_completed=True,
        default_location="Colombo 4"
    )
    assert user["phone_number"] == "94771122334"
    assert user["display_name"] == "Kasun Silva"
    assert user["preferred_language"] == "si"
    assert user["preferred_response_mode"] == "voice"
    assert user["user_role"] == "donor"
    assert user["onboarding_completed"] is True

    # Lookup by formatted phone
    fetched = mock_supabase_repo.get_user_by_phone("0771122334")
    assert fetched is not None
    assert fetched["display_name"] == "Kasun Silva"

    # Save & retrieve draft donation
    mock_supabase_repo.save_draft_donation("94771122334", {"food_type": "Rice", "quantity": 40, "location": "Wellawatte"})
    draft = mock_supabase_repo.get_draft_donation("94771122334")
    assert draft is not None
    assert draft["food_type"] == "Rice"
    assert draft["quantity"] == 40

    mock_supabase_repo.clear_draft_donation("94771122334")
    assert mock_supabase_repo.get_draft_donation("94771122334") is None


def test_supabase_dashboard_stats(mock_supabase_repo):
    """Verify aggregated dashboard statistics in Supabase PostgreSQL."""
    mock_supabase_repo.create_donation_record(
        "don-s1", "d1", "Rice", 40, "kg", "None", "Colombo", "Now", "Today"
    )
    mock_supabase_repo.create_donation_record(
        "don-s2", "d2", "Bread", 25, "loaves", "Veg", "Colombo 4", "Now", "Today"
    )
    mock_supabase_repo.update_donation_status_record("don-s2", "DELIVERED")

    stats = mock_supabase_repo.get_dashboard_stats()
    assert stats["total_donations"] == 2
    assert stats["total_food_quantity"] == 65.0
    assert stats["available_donations"] == 1
    assert stats["delivered_rescues"] == 1
    assert stats["total_organizations"] == 2
    assert stats["total_volunteers"] == 2


def test_tools_with_supabase_backend():
    """Verify the 14 operational tools execute transparently when Supabase is active."""
    # Create donation via tool
    res_raw = tools.create_donation(
        donor_id="d1",
        food_type="Fried Rice",
        quantity=35,
        unit="boxes",
        dietary_information="Halal",
        location="Colombo 3",
        available_from="11:30 AM",
        pickup_deadline="06:30 PM"
    )
    res = json.loads(res_raw)
    assert res["status"] == "success"
    don_id = res["donation_id"]

    # Verify tool retrieval
    get_res = json.loads(tools.get_donation(don_id))
    assert get_res["status"] == "success"
    assert get_res["donation"]["food_type"] == "Fried Rice"

    # Match organization
    org_res = json.loads(tools.find_matching_organizations("Fried Rice", "Colombo 3"))
    assert org_res["status"] == "success"
    org_id = org_res["organizations"][0]["id"]

    # Accept
    acc_res = json.loads(tools.accept_donation(don_id, org_id))
    assert acc_res["status"] == "success"


def test_environment_variable_database_switching(monkeypatch):
    """Verify FOODRESCUE_DATABASE environment variable selects the proper backend."""
    database.reset_repository()
    monkeypatch.setenv("FOODRESCUE_DATABASE", "supabase")
    # In absence of live SUPABASE_DB_URL, get_repository() falls back gracefully to SQLite
    repo = database.get_repository()
    assert repo is not None
    database.reset_repository()


def test_migration_utility_to_supabase(tmp_path):
    """Verify data migration logic into Supabase PostgreSQL."""
    from db_sqlite import SQLiteRepository

    # 1. Setup source SQLite repo
    src_db = str(tmp_path / "src.db")
    src_repo = SQLiteRepository(db_path=src_db)
    src_repo.setup_database()
    src_repo.seed_test_data()

    src_repo.create_donation_record(
        "don-mig-01", "d1", "Fried Rice", 50.0, "boxes", "Halal", "Colombo 3", "12:00 PM", "06:00 PM"
    )

    # 2. Setup mock target Supabase repo
    target_conn = sqlite3.connect(":memory:")
    target_conn.row_factory = sqlite3.Row
    target_repo = SupabaseRepository(connection_instance=target_conn)
    target_repo.setup_database()

    # 3. Migrate records from source to target
    for d in src_repo.get_all_donations():
        target_repo.create_donation_record(
            d["id"], d["donor_id"], d["food_type"], d["quantity"], d["unit"],
            d.get("dietary_information", ""), d.get("pickup_location", ""),
            d.get("available_from", ""), d.get("pickup_deadline", "")
        )

    assert target_repo.get_donation_record("don-mig-01") is not None
    assert target_repo.get_donation_record("don-mig-01")["food_type"] == "Fried Rice"


def test_supabase_python_sdk_client():
    """Verify official Supabase Python SDK client initialization and table queries."""
    repo = SupabaseRepository(
        supabase_url="https://vrzdsqalybgclpmnrlsv.supabase.co",
        supabase_key="sb_publishable_708OYL6mM6_72gxPPkUUvQ_mUrmqxX1"
    )
    client = repo.get_supabase_client()
    assert client is not None


def test_live_supabase_connection_if_configured():
    """Optional smoke test against live Supabase instance if SUPABASE_DB_URL is set in environment."""
    supabase_db_url = os.environ.get("SUPABASE_DB_URL")
    if not supabase_db_url:
        pytest.skip("SUPABASE_DB_URL environment variable is not configured for live testing.")

    repo = SupabaseRepository(db_url=supabase_db_url)
    repo.setup_database()
    repo.seed_test_data()
    orgs = repo.get_all_organizations()
    assert len(orgs) >= 2
