"""Comprehensive Test Suite for FoodRescue AI QR Code Handover Verification Upgrade.

Covers:
1. Pure-Python QR token generation, matrix construction, and zero-dependency PNG byte streaming.
2. Complete Pickup QR lifecycle (generation -> scan -> atomic verification -> status COLLECTED).
3. Replay attacks, duplicate scans, and invalid/expired token protection.
4. Unauthorized courier isolation (Volunteer A cannot claim Volunteer B's handover).
5. Complete Delivery QR lifecycle (pickup prerequisite -> scan -> atomic verification -> status DELIVERED & COMPLETED).
6. Cross-party real-time WhatsApp notifications for Donor, Organization, and Volunteer.
7. System audit trail logging (PICKUP_QR_VERIFIED, DELIVERY_QR_VERIFIED).
8. Agent Kernel tools integration (generate_handover_qr, verify_handover_qr, get_task_qr_verification).
"""

import pytest
import json
from unittest.mock import patch, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

import database
import qr_service
import tools
import whatsapp_handler
from api_routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_clean_db():
    """Ensure database schema exists and wipe data before and after each test."""
    database.setup_database()
    database.reset_database_data(wipe_all=True)
    yield
    database.reset_database_data(wipe_all=True)


# =============================================================================
# 1. PURE-PYTHON QR CODE GENERATION & PNG STREAMING TESTS
# =============================================================================

def test_secure_token_generation_and_hashing():
    """Verify cryptographically secure, opaque token generation without PII leakage."""
    pk_token = qr_service.generate_secure_token("PK")
    dl_token = qr_service.generate_secure_token("DL")

    assert pk_token.startswith("FR-PK-")
    assert dl_token.startswith("FR-DL-")
    assert len(pk_token) >= 20
    assert len(dl_token) >= 20
    assert pk_token != dl_token

    # Token hashing
    h1 = qr_service.hash_token(pk_token)
    h2 = qr_service.hash_token(pk_token)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256


def test_pure_python_qr_png_binary_generation():
    """Verify pure-Python PNG generation produces valid, standard PNG images with zlib compression."""
    verif_url = "https://foodrescue-ai-ten.vercel.app/verify/pickup/FR-PK-1234567890abcdef"
    png_bytes = qr_service.generate_qr_png_bytes(verif_url, box_size=10, border=3)

    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 500
    # Standard PNG magic signature: \x89PNG\r\n\x1a\n
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    # End chunk: IEND (length 4 bytes at -12:-8, tag 4 bytes at -8:-4, crc 4 bytes at -4:)
    assert png_bytes[-8:-4] == b"IEND"


def test_api_qr_png_endpoint():
    """Verify /api/qr/{token}.png streams binary PNG image."""
    token = "FR-PK-testmocktoken123"
    res = client.get(f"/api/qr/{token}.png")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content[:8] == b"\x89PNG\r\n\x1a\n"


# =============================================================================
# 2. PICKUP QR VERIFICATION LIFECYCLE TESTS
# =============================================================================

def test_pickup_qr_creation_and_atomic_verification():
    """Test full Pickup QR generation, verification, and atomic transition to COLLECTED."""
    donor_phone = "94771110001"
    vol_phone = "94771110002"
    org_phone = "94771110003"

    donor = database.create_donor_record("d-qr1", "Afnan Bakeries", donor_phone, "Kegalle Town")
    org = database.create_organization_record("org-qr1", "Kegalle Hope Shelter", org_phone, "Mawanella, Kegalle", "Prepared Meals")
    vol = database.create_volunteer_record("vol-qr1", "Mohammed Courier", vol_phone, "Kegalle", "Motorbike", current_status="available")

    don = database.create_donation_record("don-qr1", "d-qr1", "Rice & Curry", 35, "meal packets", "Halal", "Kegalle Town", "Now", "8 PM")
    task = database.create_pickup_task_record("task-qr1", "don-qr1", "org-qr1", "Kegalle Town", "Mawanella, Kegalle", "8 PM")
    database.assign_volunteer_record("task-qr1", "vol-qr1")

    # Generate Pickup QR
    token = qr_service.generate_secure_token("PK")
    qr_rec = database.create_qr_code_record(
        qr_id="qr-pk-task-qr1",
        task_id="task-qr1",
        donation_id="don-qr1",
        qr_type="PICKUP",
        token=token,
        token_hash=qr_service.hash_token(token),
        donor_id="d-qr1",
        organization_id="org-qr1",
        assigned_volunteer_id="vol-qr1",
        status="ACTIVE"
    )

    # 1. View Pickup Verification HTML page via GET
    get_res = client.get(f"/verify/pickup/{token}")
    assert get_res.status_code == 200
    assert "Pickup Verification" in get_res.text
    assert "Rice &amp; Curry" in get_res.text or "Rice & Curry" in get_res.text
    assert "35 meal packets" in get_res.text
    assert "Afnan Bakeries" in get_res.text

    # 2. Confirm Pickup via POST
    post_res = client.post(f"/verify/pickup/{token}", json={"volunteer_id": "vol-qr1", "gps": {"lat": 7.25, "lng": 80.35}})
    assert post_res.status_code == 200
    data = post_res.json()
    assert data["status"] == "success"

    # 3. Check Task and Donation statuses are now COLLECTED
    updated_task = database.get_pickup_task_record("task-qr1")
    assert updated_task["status"] == "COLLECTED"
    assert updated_task["delivery_status"] == "IN_TRANSIT"

    updated_don = database.get_donation_record("don-qr1")
    assert updated_don["status"] == "COLLECTED"

    # 4. Check QR record is now VERIFIED
    updated_qr = database.get_qr_code_by_token(token)
    assert updated_qr["status"] == "VERIFIED"
    assert updated_qr["verified_at"] is not None
    assert updated_qr["verified_by"] == "vol-qr1"


def test_rejection_of_duplicate_pickup_qr_scan():
    """Verify single-use token protection: second attempt to verify the same QR token fails."""
    donor = database.create_donor_record("d-qr2", "Donor 2", "94772220001", "Colombo 03")
    org = database.create_organization_record("org-qr2", "Org 2", "94772220002", "Colombo 07", "Prepared Meals")
    vol = database.create_volunteer_record("vol-qr2", "Volunteer 2", "94772220003", "Colombo", "Car", current_status="available")

    don = database.create_donation_record("don-qr2", "d-qr2", "Bread & Bakery", 20, "packets", "Veg", "Colombo 03", "Now", "8 PM")
    task = database.create_pickup_task_record("task-qr2", "don-qr2", "org-qr2", "Colombo 03", "Colombo 07", "8 PM")
    database.assign_volunteer_record("task-qr2", "vol-qr2")

    token = qr_service.generate_secure_token("PK")
    database.create_qr_code_record(
        qr_id="qr-pk-task-qr2",
        task_id="task-qr2",
        donation_id="don-qr2",
        qr_type="PICKUP",
        token=token,
        token_hash=qr_service.hash_token(token),
        assigned_volunteer_id="vol-qr2",
        status="ACTIVE"
    )

    # First scan succeeds
    res1 = client.post(f"/verify/pickup/{token}", json={"volunteer_id": "vol-qr2"})
    assert res1.status_code == 200

    # Second scan is rejected
    res2 = client.post(f"/verify/pickup/{token}", json={"volunteer_id": "vol-qr2"})
    assert res2.status_code == 400
    assert res2.json()["error"] == "ALREADY_USED"


def test_rejection_of_unauthorized_volunteer_on_pickup():
    """Verify isolation: Volunteer B cannot scan and confirm Volunteer A's assigned task."""
    volA = database.create_volunteer_record("vol-A", "Volunteer A", "94773330001", "Colombo", "Car", current_status="available")
    volB = database.create_volunteer_record("vol-B", "Volunteer B", "94773330002", "Colombo", "Motorbike", current_status="available")

    don = database.create_donation_record("don-qr3", "d1", "Fried Rice", 15, "packets", "Halal", "Colombo 03", "Now", "8 PM")
    task = database.create_pickup_task_record("task-qr3", "don-qr3", "org1", "Colombo 03", "Colombo 07", "8 PM")
    database.assign_volunteer_record("task-qr3", "vol-A")

    token = qr_service.generate_secure_token("PK")
    database.create_qr_code_record(
        qr_id="qr-pk-task-qr3",
        task_id="task-qr3",
        donation_id="don-qr3",
        qr_type="PICKUP",
        token=token,
        token_hash=qr_service.hash_token(token),
        assigned_volunteer_id="vol-A",
        status="ACTIVE"
    )

    # Volunteer B tries to verify
    res = client.post(f"/verify/pickup/{token}", json={"volunteer_id": "vol-B"})
    assert res.status_code == 400
    assert res.json()["error"] == "UNAUTHORIZED_VOLUNTEER"

    # Task status remains unchanged
    assert database.get_pickup_task_record("task-qr3")["status"] != "COLLECTED"


# =============================================================================
# 3. DELIVERY QR VERIFICATION LIFECYCLE TESTS
# =============================================================================

def test_delivery_qr_verification_lifecycle():
    """Test Delivery QR lifecycle: collection required first, then delivery verification completes task and releases courier."""
    donor_phone = "94774440001"
    vol_phone = "94774440002"
    org_phone = "94774440003"

    donor = database.create_donor_record("d-dl1", "Grand Hotel", donor_phone, "Kandy City")
    org = database.create_organization_record("org-dl1", "Kandy Children Home", org_phone, "Peradeniya, Kandy", "Prepared Meals")
    vol = database.create_volunteer_record("vol-dl1", "Nimal Courier", vol_phone, "Kandy", "Three-Wheeler", current_status="available")

    don = database.create_donation_record("don-dl1", "d-dl1", "Vegetable Biryani", 50, "packets", "Vegetarian", "Kandy City", "Now", "8 PM")
    task = database.create_pickup_task_record("task-dl1", "don-dl1", "org-dl1", "Kandy City", "Peradeniya, Kandy", "8 PM")
    database.assign_volunteer_record("task-dl1", "vol-dl1")

    # Create delivery token
    dl_token = qr_service.generate_secure_token("DL")
    database.create_qr_code_record(
        qr_id="qr-dl-task-dl1",
        task_id="task-dl1",
        donation_id="don-dl1",
        qr_type="DELIVERY",
        token=dl_token,
        token_hash=qr_service.hash_token(dl_token),
        donor_id="d-dl1",
        organization_id="org-dl1",
        assigned_volunteer_id="vol-dl1",
        status="ACTIVE"
    )

    # 1. Delivery scan BEFORE food is collected must fail
    res_early = client.post(f"/verify/delivery/{dl_token}", json={"volunteer_id": "vol-dl1"})
    assert res_early.status_code == 400
    assert res_early.json()["error"] == "NOT_YET_COLLECTED"

    # 2. Mark food as collected
    database.update_pickup_status_record("task-dl1", "COLLECTED")
    database.update_donation_status_record("don-dl1", "COLLECTED")

    # 3. View Delivery Verification HTML page via GET
    get_res = client.get(f"/verify/delivery/{dl_token}")
    assert get_res.status_code == 200
    assert "Delivery Verification" in get_res.text
    assert "Vegetable Biryani" in get_res.text
    assert "Kandy Children Home" in get_res.text

    # 4. Confirm Delivery via POST
    post_res = client.post(f"/verify/delivery/{dl_token}", json={"volunteer_id": "vol-dl1"})
    assert post_res.status_code == 200
    assert post_res.json()["status"] == "success"

    # 5. Verify task is COMPLETED & DELIVERED
    updated_task = database.get_pickup_task_record("task-dl1")
    assert updated_task["status"] == "COMPLETED"
    assert updated_task["delivery_status"] == "DELIVERED"

    # 6. Verify volunteer is back to AVAILABLE
    updated_vol = database.get_volunteer_record("vol-dl1")
    assert updated_vol["current_status"] == "available"


def test_rejection_of_duplicate_delivery_qr_scan():
    """Verify delivery token cannot be reused after delivery is completed."""
    don = database.create_donation_record("don-dl2", "d1", "Curry", 10, "packets", "Standard", "Loc", "Now", "8 PM")
    task = database.create_pickup_task_record("task-dl2", "don-dl2", "org1", "Loc", "Dest", "8 PM")
    database.assign_volunteer_record("task-dl2", "vol1")
    database.update_pickup_status_record("task-dl2", "COLLECTED")

    dl_token = qr_service.generate_secure_token("DL")
    database.create_qr_code_record(
        qr_id="qr-dl-task-dl2",
        task_id="task-dl2",
        donation_id="don-dl2",
        qr_type="DELIVERY",
        token=dl_token,
        token_hash=qr_service.hash_token(dl_token),
        assigned_volunteer_id="vol1",
        status="ACTIVE"
    )

    # First delivery scan succeeds
    r1 = client.post(f"/verify/delivery/{dl_token}", json={"volunteer_id": "vol1"})
    assert r1.status_code == 200

    # Second delivery scan is rejected
    r2 = client.post(f"/verify/delivery/{dl_token}", json={"volunteer_id": "vol1"})
    assert r2.status_code == 400
    assert r2.json()["error"] == "ALREADY_USED"


# =============================================================================
# 4. CROSS-PARTY WHATSAPP NOTIFICATIONS & AUDIT TRAIL TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_cross_party_notifications_on_pickup_verification():
    """Verify real-time WhatsApp messages sent to Donor, Org, and Volunteer on pickup QR verification."""
    donor_phone = "94775550001"
    vol_phone = "94775550002"
    org_phone = "94775550003"

    database.create_or_update_user(donor_phone, display_name="Donor Five", preferred_language="en")
    database.create_or_update_user(vol_phone, display_name="Courier Five", preferred_language="en")
    database.create_or_update_user(org_phone, display_name="Shelter Five", preferred_language="en")

    database.create_donor_record("d-five", "Donor Five", donor_phone, "Kegalle")
    database.create_organization_record("org-five", "Shelter Five", org_phone, "Mawanella", "Prepared Meals")
    database.create_volunteer_record("vol-five", "Courier Five", vol_phone, "Kegalle", "Motorbike")

    don = database.create_donation_record("don-five", "d-five", "Rice & Curry", 40, "meal packets", "Halal", "Kegalle", "Now", "8 PM")
    task = database.create_pickup_task_record("task-five", "don-five", "org-five", "Kegalle", "Mawanella", "8 PM")
    database.assign_volunteer_record("task-five", "vol-five")

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("whatsapp_handler.send_whatsapp_image", new_callable=AsyncMock) as mock_img:
        mock_msg.return_value = {"status": "sent"}
        mock_img.return_value = {"status": "sent"}

        await whatsapp_handler.dispatch_qr_pickup_success_notifications("task-five", volunteer_id="vol-five")

        # 1. Donor notified
        donor_notified = any(call.kwargs.get("to_number") == donor_phone for call in mock_msg.call_args_list)
        assert donor_notified, "Donor was not notified upon food pickup"

        # 2. Organization received Delivery QR image
        org_notified = any(call.kwargs.get("to_number") == org_phone for call in mock_img.call_args_list)
        assert org_notified, "Organization was not sent Delivery QR image upon pickup"

        # 3. Volunteer received destination and route
        vol_notified = any(call.kwargs.get("to_number") == vol_phone for call in mock_msg.call_args_list)
        assert vol_notified, "Volunteer was not sent destination route upon pickup"


@pytest.mark.asyncio
async def test_cross_party_notifications_on_delivery_verification():
    """Verify real-time WhatsApp messages sent to Org, Donor, and Volunteer on delivery QR verification."""
    donor_phone = "94776660001"
    vol_phone = "94776660002"
    org_phone = "94776660003"

    database.create_or_update_user(donor_phone, display_name="Donor Six", preferred_language="en")
    database.create_or_update_user(vol_phone, display_name="Courier Six", preferred_language="en")
    database.create_or_update_user(org_phone, display_name="Shelter Six", preferred_language="en")

    database.create_donor_record("d-six", "Donor Six", donor_phone, "Kegalle")
    database.create_organization_record("org-six", "Shelter Six", org_phone, "Mawanella", "Prepared Meals")
    database.create_volunteer_record("vol-six", "Courier Six", vol_phone, "Kegalle", "Motorbike")

    don = database.create_donation_record("don-six", "d-six", "Fried Rice", 25, "meal packets", "Halal", "Kegalle", "Now", "8 PM")
    task = database.create_pickup_task_record("task-six", "don-six", "org-six", "Kegalle", "Mawanella", "8 PM")
    database.assign_volunteer_record("task-six", "vol-six")

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_msg:
        mock_msg.return_value = {"status": "sent"}

        await whatsapp_handler.dispatch_qr_delivery_success_notifications("task-six", volunteer_id="vol-six")

        # Org, Donor, and Volunteer notified
        notified_phones = [call.kwargs.get("to_number") for call in mock_msg.call_args_list]
        assert org_phone in notified_phones
        assert donor_phone in notified_phones
        assert vol_phone in notified_phones


def test_audit_events_created_on_qr_verification():
    """Verify system audit trail logs created for PICKUP_QR_VERIFIED and DELIVERY_QR_VERIFIED."""
    don = database.create_donation_record("don-aud", "d1", "Rice", 10, "packets", "Halal", "Loc", "Now", "8 PM")
    task = database.create_pickup_task_record("task-aud", "don-aud", "org1", "Loc", "Dest", "8 PM")
    database.assign_volunteer_record("task-aud", "vol-aud")

    pk_token = qr_service.generate_secure_token("PK")
    database.create_qr_code_record("qr-pk-aud", "task-aud", "don-aud", "PICKUP", pk_token, qr_service.hash_token(pk_token), assigned_volunteer_id="vol-aud")

    # Verify pickup
    database.verify_qr_code_record(pk_token, volunteer_id="vol-aud", gps_coords={"lat": 6.9, "lng": 79.8})
    audits = database.get_all_audit_events()
    assert any(a["event_type"] == "PICKUP_QR_VERIFIED" and a["related_id"] == "task-aud" for a in audits)

    # Create and verify delivery
    dl_token = qr_service.generate_secure_token("DL")
    database.create_qr_code_record("qr-dl-aud", "task-aud", "don-aud", "DELIVERY", dl_token, qr_service.hash_token(dl_token), assigned_volunteer_id="vol-aud")
    database.verify_qr_code_record(dl_token, volunteer_id="vol-aud", gps_coords={"lat": 6.91, "lng": 79.85})
    audits_after = database.get_all_audit_events()
    assert any(a["event_type"] == "DELIVERY_QR_VERIFIED" and a["related_id"] == "task-aud" for a in audits_after)


# =============================================================================
# 5. AGENT KERNEL TOOLS INTEGRATION TESTS
# =============================================================================

def test_agent_kernel_qr_tools():
    """Verify generate_handover_qr, verify_handover_qr, and get_task_qr_verification tools."""
    don = database.create_donation_record("don-tl", "d1", "Rice", 10, "portions", "Halal", "Loc", "Now", "8 PM")
    task = database.create_pickup_task_record("task-tl", "don-tl", "org1", "Loc", "Dest", "8 PM")
    database.assign_volunteer_record("task-tl", "vol-tl")

    # 1. generate_handover_qr tool
    gen_raw = tools.generate_handover_qr("task-tl", "PICKUP")
    gen_data = json.loads(gen_raw)
    assert gen_data["status"] == "success"
    token = gen_data["token"]
    assert token.startswith("FR-PK-")
    assert "verification_url" in gen_data
    assert "qr_image_url" in gen_data

    # 2. get_task_qr_verification tool
    stat_raw = tools.get_task_qr_verification("task-tl")
    stat_data = json.loads(stat_raw)
    assert stat_data["status"] == "success"
    assert len(stat_data["qr_codes"]) >= 1

    # 3. verify_handover_qr tool
    ver_raw = tools.verify_handover_qr(token, volunteer_id="vol-tl")
    ver_data = json.loads(ver_raw)
    assert ver_data["success"] is True
    assert ver_data["qr_type"] == "PICKUP"
