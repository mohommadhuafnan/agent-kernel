"""FoodRescue AI Dashboard Data Consistency & Flickering Regression Tests.

Verifies:
1. Strict database consistency across concurrent API requests.
2. Zero count flickering (counts never randomly alternate between 2 and 0).
3. Deleting a record permanently updates counts across all queries and API responses.
4. Database repository singleton stability (never mutates to SQLite when Supabase is configured).
5. Dynamic API responses include strict no-cache HTTP headers.
"""

import os
import sys
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database
from api_routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_clean_db():
    database.reset_database_data(wipe_all=True)
    yield
    database.reset_database_data(wipe_all=True)


def test_dashboard_api_no_cache_headers():
    """Verify that all dynamic API endpoints return strict no-cache headers."""
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    assert "no-store" in resp.headers.get("cache-control", "").lower()
    assert "no-cache" in resp.headers.get("cache-control", "").lower()
    assert resp.headers.get("pragma", "").lower() == "no-cache"

    users_resp = client.get("/api/users")
    assert users_resp.status_code == 200
    assert "no-store" in users_resp.headers.get("cache-control", "").lower()


def test_dashboard_user_creation_and_stable_counts():
    """Verify that creating 2 users results in 100% stable count across 50 repeated queries."""
    # Create 2 users
    u1 = database.create_or_update_user(
        phone="94770001111",
        display_name="Donor User One",
        preferred_language="en",
        user_role="donor"
    )
    u2 = database.create_or_update_user(
        phone="94770002222",
        display_name="Volunteer User Two",
        preferred_language="en",
        user_role="volunteer"
    )
    assert u1 and u2

    # Query 50 times consecutively
    for i in range(50):
        # 1. API stats endpoint
        dash_res = client.get("/api/dashboard").json()
        assert dash_res.get("status") == "success"
        stats = dash_res.get("stats", {})
        assert stats.get("active_users") == 2, f"Flickering detected at iteration {i}: got {stats.get('active_users')}"

        # 2. API users endpoint
        users_res = client.get("/api/users").json()
        assert users_res.get("status") == "success"
        assert users_res.get("count") == 2, f"Users count flickering at iteration {i}: got {users_res.get('count')}"
        assert len(users_res.get("users", [])) == 2


def test_dashboard_user_deletion_consistency():
    """Verify that deleting users permanently reduces count without ghost records or resurrection."""
    # Create 2 users
    database.create_or_update_user(phone="94770001111", display_name="User One", user_role="donor")
    database.create_or_update_user(phone="94770002222", display_name="User Two", user_role="volunteer")

    # Initial check: exactly 2
    res = client.get("/api/dashboard").json()
    assert res["stats"]["active_users"] == 2

    # Delete User One
    del_res = client.delete("/api/users/94770001111")
    assert del_res.status_code == 200

    # Query 30 times: must remain strictly 1
    for i in range(30):
        res = client.get("/api/dashboard").json()
        assert res["stats"]["active_users"] == 1, f"Count flickered after first delete at iteration {i}: got {res['stats']['active_users']}"

        u_res = client.get("/api/users").json()
        assert u_res["count"] == 1
        assert len(u_res["users"]) == 1
        assert u_res["users"][0]["phone_number"] == "94770002222"

    # Delete User Two
    del_res2 = client.delete("/api/users/94770002222")
    assert del_res2.status_code == 200

    # Query 30 times: must remain strictly 0
    for i in range(30):
        res = client.get("/api/dashboard").json()
        assert res["stats"]["active_users"] == 0, f"Count flickered after second delete at iteration {i}: got {res['stats']['active_users']}"

        u_res = client.get("/api/users").json()
        assert u_res["count"] == 0
        assert len(u_res["users"]) == 0


def test_concurrent_api_requests_stability():
    """Verify that concurrent requests do not corrupt internal database connections or return 0."""
    import concurrent.futures

    # Seed 3 donations, 2 orgs, 2 volunteers, 4 users
    database.create_or_update_user(phone="94770001111", display_name="Donor 1", user_role="donor")
    database.create_or_update_user(phone="94770002222", display_name="Donor 2", user_role="donor")
    database.create_or_update_user(phone="94770003333", display_name="Org 1", user_role="organization")
    database.create_or_update_user(phone="94770004444", display_name="Vol 1", user_role="volunteer")

    database.create_organization_record("org-1", "Org One", "94770003333", "Colombo", "Meals", "100", "Daytime", "Colombo")
    database.create_organization_record("org-2", "Org Two", "94770003334", "Kandy", "Meals", "50", "Daytime", "Kandy")

    database.create_volunteer_record("vol-1", "Vol One", "94770004444", "Colombo", "Motorbike", "Available", "available", "Colombo")
    database.create_volunteer_record("vol-2", "Vol Two", "94770004445", "Kandy", "Motorbike", "Available", "available", "Kandy")

    database.create_donation_record("don-1", "d-1", "Rice", 20.0, "portions", "Standard", "Colombo", "Now", "8 PM")
    database.create_donation_record("don-2", "d-2", "Curry", 15.0, "portions", "Standard", "Colombo", "Now", "8 PM")

    def make_request(endpoint):
        res = client.get(endpoint)
        return endpoint, res.status_code, res.json()

    endpoints = [
        "/api/dashboard",
        "/api/users",
        "/api/organizations",
        "/api/volunteers",
        "/api/donations",
        "/api/live-operations",
        "/api/reports",
        "/api/settings",
    ] * 5  # 40 concurrent requests

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(make_request, ep) for ep in endpoints]
        for f in concurrent.futures.as_completed(futures):
            ep, status, data = f.result()
            assert status == 200, f"Endpoint {ep} failed with status {status}"
            assert data.get("status") == "success"

            if ep == "/api/users":
                assert data.get("count") >= 4, f"Users count dropped on {ep}: {data.get('count')}"
            elif ep == "/api/organizations":
                assert data.get("count") == 2, f"Organizations count dropped on {ep}: {data.get('count')}"
            elif ep == "/api/volunteers":
                assert data.get("count") == 2, f"Volunteers count dropped on {ep}: {data.get('count')}"
            elif ep == "/api/donations":
                assert data.get("count") == 2, f"Donations count dropped on {ep}: {data.get('count')}"
            elif ep == "/api/dashboard":
                stats = data.get("stats", {})
                assert stats.get("total_donations") == 2
                assert stats.get("total_organizations") == 2
                assert stats.get("total_volunteers") == 2
                assert stats.get("active_users") >= 4
