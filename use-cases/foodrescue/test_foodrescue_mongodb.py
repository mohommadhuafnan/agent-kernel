"""FoodRescue AI MongoDB Persistence Test Suite.

Validates the MongoRepository implementation:
1. Complete CRUD operations and schema normalization
2. Indexing and collections
3. Proximity and dietary ranking algorithms
4. 10-step lifecycle workflow over MongoDB
5. Aggregated dashboard KPIs
6. Integration with the 14 FoodRescue operational tools
7. Clean skip when live MONGODB_URI is not provided/reachable
"""

import os
import json
import pytest
import mongomock
from db_mongo import MongoRepository
import database
import tools
from agentkernel.core import Session, Runtime


@pytest.fixture
def mock_mongo_repo():
    """Create an isolated in-memory MongoRepository backed by mongomock."""
    client = mongomock.MongoClient()
    db = client["foodrescue_test"]
    repo = MongoRepository(db_instance=db)
    repo.setup_database()
    repo.seed_test_data()
    return repo


@pytest.fixture(autouse=True)
def inject_mongo_repo_into_database(mock_mongo_repo):
    """Inject mock_mongo_repo into the database delegation layer for every test."""
    original_repo = database._CURRENT_REPO
    database.set_repository(mock_mongo_repo)
    yield mock_mongo_repo
    database.set_repository(original_repo)


def test_mongodb_initialization_and_seeding(mock_mongo_repo):
    """Verify MongoDB collections and initial seed records."""
    donor_d1 = mock_mongo_repo.get_donor_record("d1")
    assert donor_d1 is not None
    assert donor_d1["id"] == "d1"
    assert donor_d1["name"] == "Grand Hotel"
    assert "_id" not in donor_d1

    org_o1 = mock_mongo_repo.get_organization_record("o1")
    assert org_o1 is not None
    assert org_o1["id"] == "o1"
    assert "Community Kitchen" in org_o1["name"]

    vol_v1 = mock_mongo_repo.get_volunteer_record("v1")
    assert vol_v1 is not None
    assert vol_v1["id"] == "v1"
    assert vol_v1["current_status"] == "available"


def test_mongodb_donation_crud_and_status(mock_mongo_repo):
    """Verify donation creation, retrieval, and status updates in MongoDB."""
    don = mock_mongo_repo.create_donation_record(
        donation_id="don-mongo-001",
        donor_id="d1",
        food_type="Vegetarian Rice Packets",
        quantity=50.0,
        unit="packets",
        dietary_info="Vegetarian, Halal",
        location="Colombo 3",
        available_from="11:00 AM",
        deadline="07:00 PM"
    )
    assert don["id"] == "don-mongo-001"
    assert don["quantity"] == 50.0
    assert don["status"] == "AVAILABLE"
    assert "_id" not in don

    # Fetch
    fetched = mock_mongo_repo.get_donation_record("don-mongo-001")
    assert fetched is not None
    assert fetched["id"] == "don-mongo-001"

    # Update status
    updated = mock_mongo_repo.update_donation_status_record("don-mongo-001", "MATCHED")
    assert updated is True
    assert mock_mongo_repo.get_donation_record("don-mongo-001")["status"] == "MATCHED"


def test_mongodb_donation_details_update(mock_mongo_repo):
    """Verify updating editable donation details in MongoDB."""
    mock_mongo_repo.create_donation_record(
        donation_id="don-mongo-edit",
        donor_id="d1",
        food_type="Initial Meals",
        quantity=20.0,
        unit="boxes",
        dietary_info="None",
        location="Colombo",
        available_from="Now",
        deadline="04:00 PM"
    )

    updated = mock_mongo_repo.update_donation_details_record(
        donation_id="don-mongo-edit",
        quantity=35.0,
        deadline="08:00 PM",
        dietary_info="Vegan"
    )
    assert updated is not None
    assert updated["quantity"] == 35.0
    assert updated["pickup_deadline"] == "08:00 PM"
    assert updated["dietary_information"] == "Vegan"
    assert updated["food_type"] == "Initial Meals"


def test_mongodb_find_organizations_and_volunteers_ranking(mock_mongo_repo):
    """Verify MongoDB location and food-type ranking algorithms."""
    # Organization matching for vegetarian in Colombo
    orgs = mock_mongo_repo.find_organizations_by_criteria("vegetarian", "Colombo 7")
    assert len(orgs) >= 1
    assert orgs[0]["id"] == "o1"
    assert orgs[0]["match_score"] >= 10

    # Volunteer matching in Colombo 3
    vols = mock_mongo_repo.find_volunteers_by_criteria("Colombo 3")
    assert len(vols) >= 1
    assert vols[0]["id"] == "v1"
    assert vols[0]["match_score"] >= 10


def test_mongodb_pickup_lifecycle_workflow(mock_mongo_repo):
    """Verify complete end-to-end pickup task lifecycle in MongoDB."""
    # 1. Create donation
    mock_mongo_repo.create_donation_record(
        "don-life-01", "d1", "Curry Packets", 30, "packets", "Veg", "Colombo 3", "12:00 PM", "06:00 PM"
    )

    # 2. Accept donation
    acc = mock_mongo_repo.accept_donation_record("don-life-01", "o1")
    assert acc is True
    assert mock_mongo_repo.get_donation_record("don-life-01")["status"] == "MATCHED"

    # 3. Create pickup task
    task = mock_mongo_repo.create_pickup_task_record(
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
    assigned = mock_mongo_repo.assign_volunteer_record("task-life-01", "v1")
    assert assigned is True
    t_assigned = mock_mongo_repo.get_pickup_task_record("task-life-01")
    assert t_assigned["volunteer_id"] == "v1"
    assert t_assigned["status"] == "ASSIGNED"

    # 5. Advance status (EN_ROUTE -> COLLECTED -> DELIVERED)
    mock_mongo_repo.update_pickup_status_record("task-life-01", "EN_ROUTE")
    assert mock_mongo_repo.get_pickup_task_record("task-life-01")["status"] == "EN_ROUTE"

    mock_mongo_repo.update_pickup_status_record("task-life-01", "COLLECTED")
    assert mock_mongo_repo.get_pickup_task_record("task-life-01")["status"] == "COLLECTED"

    mock_mongo_repo.update_pickup_status_record("task-life-01", "DELIVERED")
    assert mock_mongo_repo.get_pickup_task_record("task-life-01")["status"] == "DELIVERED"


def test_mongodb_notifications_persistence(mock_mongo_repo):
    """Verify notifications logging and retrieval in MongoDB."""
    mock_mongo_repo.create_notification_record(
        "notif-m1", "donor", "d1", "Donation created successfully.", "console"
    )
    mock_mongo_repo.create_notification_record(
        "notif-m2", "donor", "d1", "Volunteer assigned to pickup.", "console"
    )

    notifs = mock_mongo_repo.get_notifications_for_recipient("d1")
    assert len(notifs) == 2
    assert any(n["id"] == "notif-m1" for n in notifs)
    assert any(n["id"] == "notif-m2" for n in notifs)


def test_mongodb_dashboard_stats(mock_mongo_repo):
    """Verify aggregated dashboard statistics in MongoDB."""
    mock_mongo_repo.create_donation_record(
        "don-s1", "d1", "Rice", 40, "kg", "None", "Colombo", "Now", "Today"
    )
    mock_mongo_repo.create_donation_record(
        "don-s2", "d2", "Bread", 25, "loaves", "Veg", "Colombo 4", "Now", "Today"
    )
    mock_mongo_repo.update_donation_status_record("don-s2", "DELIVERED")

    stats = mock_mongo_repo.get_dashboard_stats()
    assert stats["total_donations"] == 2
    assert stats["total_food_quantity"] == 65.0
    assert stats["available_donations"] == 1
    assert stats["delivered_rescues"] == 1
    assert stats["total_organizations"] == 2
    assert stats["total_volunteers"] == 2


def test_mongodb_reset_data(mock_mongo_repo):
    """Verify resetting dynamic data preserves seeded master organizations and volunteers."""
    mock_mongo_repo.create_donation_record("don-r1", "d1", "Food", 10, "boxes", "None", "Loc", "Now", "Today")
    assert mock_mongo_repo.get_all_donations() != []

    mock_mongo_repo.reset_database_data()
    assert len(mock_mongo_repo.get_all_donations()) == 0
    assert len(mock_mongo_repo.get_all_organizations()) >= 2
    assert len(mock_mongo_repo.get_all_volunteers()) >= 2


def test_tools_with_mongodb_backend():
    """Verify the 14 operational tools execute transparently when MongoDB is active."""
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

    # Create task & assign volunteer
    task_res = json.loads(tools.create_pickup_task(don_id, org_id, "Colombo 3", "Colombo 7", "01:00 PM"))
    task_id = task_res["task_id"]

    vol_res = json.loads(tools.find_available_volunteers("Colombo 3"))
    vol_id = vol_res["volunteers"][0]["id"]

    assign_res = json.loads(tools.assign_volunteer(task_id, vol_id))
    assert assign_res["status"] == "success"
    assert assign_res["donation_status"] == "PICKUP_ASSIGNED"


def test_live_mongodb_connection_if_configured():
    """Live MongoDB Atlas / Server test (runs only when MONGODB_URI is provided and reachable)."""
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        pytest.skip("MONGODB_URI environment variable not set. Skipping live MongoDB integration test.")

    import pymongo
    try:
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=2500)
        client.admin.command("ping")
    except Exception as e:
        pytest.skip(f"Could not connect to live MongoDB at {uri}: {e}. Skipping.")

    # Live repository operations
    live_repo = MongoRepository(uri=uri, db_name="foodrescue_live_test")
    live_repo.setup_database()
    live_repo.seed_test_data()

    don = live_repo.create_donation_record(
        "don-live-mongo-01", "d1", "Live Mongo Test Food", 10, "boxes", "None", "Colombo", "Now", "End of Day"
    )
    assert don["id"] == "don-live-mongo-01"

    # Clean up test record
    live_repo.donations_col.delete_one({"id": "don-live-mongo-01"})
    client.close()
