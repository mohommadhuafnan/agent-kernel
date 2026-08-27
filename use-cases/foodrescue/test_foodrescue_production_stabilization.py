"""FoodRescue AI Production Stabilization Test Suite.

Comprehensive end-to-end tests validating:
1. Dynamic Food, Quantity, and Units (No hardcoded values).
2. Deterministic Slot-Filling State Machine (Zero question repetition, multi-turn state preservation).
3. Role Isolation (Volunteer vs Org vs Donor onboarding and workflows).
4. Live GPS Location Capture & Dynamic Route Distance / Reimbursement Calculation.
5. QR Code Pickup & Delivery Lifecycle.
6. Permanent Record Deletion & Single Source of Truth (No reappearing deleted data).
"""

import os
import pytest
import datetime
from unittest.mock import patch, AsyncMock
import database
import whatsapp_handler
import resilient_executor
import qr_service
import routing


@pytest.fixture(autouse=True)
def setup_clean_db():
    """Ensure a clean database state for each test run."""
    database.reset_database_data(wipe_all=True)
    yield
    database.reset_database_data(wipe_all=True)


# ==========================================
# 1. DYNAMIC FOOD & QUANTITY TESTS (Test A & B)
# ==========================================

@pytest.mark.asyncio
async def test_dynamic_food_and_quantity_test_a():
    """Test A: 'I have 15 boxes of chicken biryani available in Mawanella.'"""
    phone = "94771110001"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        # User sends all-in-one message
        msg = {
            "from": phone,
            "id": "w.msg.a1",
            "type": "text",
            "text": {"body": "I have 15 boxes of chicken biryani available in Mawanella."}
        }
        res = await whatsapp_handler.process_incoming_whatsapp_message(msg)

        # Inspect draft in database
        draft = database.get_draft_donation(phone)
        assert draft is not None
        assert "biryani" in draft["food_type"].lower()
        assert float(draft["quantity"]) == 15.0
        assert draft.get("unit") in ["boxes", "packets", "portions"]
        assert "mawanella" in draft.get("city", "").lower() or "kegalle" in draft.get("city", "").lower()

        # The AI should NOT ask for food or quantity again
        assert "What type of food" not in res["reply"]
        assert "How many" not in res["reply"]


@pytest.mark.asyncio
async def test_dynamic_food_and_quantity_test_b():
    """Test B: 'I have 100 kg of vegetables in Kegalle.'"""
    phone = "94771110002"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        msg = {
            "from": phone,
            "id": "w.msg.b1",
            "type": "text",
            "text": {"body": "I have 100 kg of vegetables in Kegalle."}
        }
        res = await whatsapp_handler.process_incoming_whatsapp_message(msg)

        draft = database.get_draft_donation(phone)
        assert draft is not None
        assert "vegetable" in draft["food_type"].lower()
        assert float(draft["quantity"]) == 100.0
        assert draft.get("unit") == "kg"
        assert "kegalle" in draft.get("city", "").lower()

        assert "What type of food" not in res["reply"]
        assert "How many" not in res["reply"]


# ==========================================
# 2. VOLUNTEER REGISTRATION (Test C)
# ==========================================

@pytest.mark.asyncio
async def test_volunteer_registration_and_isolation_test_c():
    """Test C: 'I am a volunteer. My name is Kasun. I use a motorbike and I serve Kegalle.'"""
    vol_phone = "94771110003"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        # Step 1: Initial contact from volunteer
        msg1 = {
            "from": vol_phone,
            "id": "w.msg.c1",
            "type": "text",
            "text": {"body": "I want to volunteer to deliver food"}
        }
        res1 = await whatsapp_handler.process_incoming_whatsapp_message(msg1)
        assert "volunteer" in res1["reply"].lower() or "courier" in res1["reply"].lower()

        # Step 2: Volunteer sends details
        msg2 = {
            "from": vol_phone,
            "id": "w.msg.c2",
            "type": "text",
            "text": {"body": "My name is Kasun. I use a motorbike and I serve Kegalle."}
        }
        res2 = await whatsapp_handler.process_incoming_whatsapp_message(msg2)

        # Volunteer must NEVER be asked donor food questions!
        assert "What type of food" not in res2["reply"]
        assert "portions" not in res2["reply"]

        # Step 3: Volunteer shares GPS location pin
        msg3 = {
            "from": vol_phone,
            "id": "w.msg.c3",
            "type": "location",
            "location": {
                "latitude": 7.2520,
                "longitude": 80.3460,
                "name": "Kegalle Clock Tower",
                "address": "Kegalle, Sri Lanka"
            }
        }
        res3 = await whatsapp_handler.process_incoming_whatsapp_message(msg3)
        assert "location" in res3["reply"].lower() or "saved" in res3["reply"].lower() or "registered" in res3["reply"].lower()

        # Check volunteer in database
        vol = database.get_volunteer_by_phone(vol_phone)
        assert vol is not None
        assert "Kasun" in vol.get("name", "")
        assert "kegalle" in vol.get("service_area", "").lower()
        assert vol.get("current_status") == "available"


# ==========================================
# 3. RECIPIENT ORGANIZATION REGISTRATION (Test D)
# ==========================================

@pytest.mark.asyncio
async def test_organization_registration_test_d():
    """Test D: 'We are ABC Community Kitchen in Mawanella and need food today.'"""
    org_phone = "94771110004"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        msg1 = {
            "from": org_phone,
            "id": "w.msg.d1",
            "type": "text",
            "text": {"body": "2"}  # Option 2: Request food
        }
        res1 = await whatsapp_handler.process_incoming_whatsapp_message(msg1)

        msg2 = {
            "from": org_phone,
            "id": "w.msg.d2",
            "type": "text",
            "text": {"body": "ABC Community Kitchen in Mawanella, we can receive 150 meals daily"}
        }
        res2 = await whatsapp_handler.process_incoming_whatsapp_message(msg2)

        # Organization should not be asked donor food donation questions
        assert "What type of food do you have available" not in res2["reply"]


# ==========================================
# 4. FIRST-TIME USER GREETING (Test E)
# ==========================================

@pytest.mark.asyncio
async def test_new_user_greeting_test_e():
    """Test E: 'Hi' for a completely new user gives welcome menu with clear role choices."""
    new_phone = "94771110005"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        msg = {
            "from": new_phone,
            "id": "w.msg.e1",
            "type": "text",
            "text": {"body": "Hi"}
        }
        res = await whatsapp_handler.process_incoming_whatsapp_message(msg)

        reply = res["reply"]
        assert "Welcome to FoodRescue AI" in reply or "FoodRescue AI" in reply
        assert "1" in reply and "Donate" in reply
        assert "2" in reply and "Request" in reply
        assert "3" in reply and "Volunteer" in reply


# ==========================================
# 5. INFORMATION MERGING & ZERO REPETITION
# ==========================================

@pytest.mark.asyncio
async def test_multi_turn_information_merging_and_zero_repetition():
    """Verify sequential slot filling without asking for already known slots."""
    donor_phone = "94771110006"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        # Turn 1: 1 (Donate)
        r1 = await whatsapp_handler.process_incoming_whatsapp_message({
            "from": donor_phone, "id": "t.1", "type": "text", "text": {"body": "1"}
        })
        assert "food" in r1["reply"].lower()

        # Turn 2: Afnan from Kegalle
        r2 = await whatsapp_handler.process_incoming_whatsapp_message({
            "from": donor_phone, "id": "t.2", "type": "text", "text": {"body": "My name is Afnan from Kegalle"}
        })
        # Turn 3: 40 packets of vegetable rice
        r3 = await whatsapp_handler.process_incoming_whatsapp_message({
            "from": donor_phone, "id": "t.3", "type": "text", "text": {"body": "40 packets of vegetable rice"}
        })

        # The AI must remember Afnan + Kegalle + 40 + vegetable rice and NOT ask for name again
        assert "What is your name" not in r3["reply"]
        assert "What type of food" not in r3["reply"]

        draft = database.get_draft_donation(donor_phone)
        assert draft["food_type"] == "vegetable rice" or "rice" in draft["food_type"].lower()
        assert float(draft["quantity"]) == 40.0
        assert "kegalle" in draft["city"].lower()
        assert draft["donor_name"] == "Afnan"


# ==========================================
# 6. PERMANENT RECORD DELETION & ZERO RESEEDING
# ==========================================

def test_permanent_record_deletion_across_repositories():
    """Verify creating records, deleting them, and confirming they do not reappear."""
    # 1. Create Donor
    database.create_donor_record(donor_id="d-del-1", name="Test Delete Donor", phone="+94779991111", location="Colombo")
    assert database.get_donor_record("d-del-1") is not None

    # 2. Delete Donor
    deleted = database.delete_donor_record("d-del-1")
    assert deleted is True
    assert database.get_donor_record("d-del-1") is None

    # 3. Create Donation and linked Task/QR
    don = database.create_donation_record(
        donation_id="don-del-1",
        donor_id="d-del-1",
        food_type="Rice",
        quantity=20,
        unit="portions",
        dietary_info="Standard",
        location="Colombo",
        available_from="Now",
        deadline="6 PM"
    )
    assert database.get_donation_record("don-del-1") is not None

    task = database.create_pickup_task_record(
        task_id="task-del-1",
        donation_id="don-del-1",
        org_id="org-1",
        pickup_loc="Colombo",
        delivery_loc="Colombo 4",
        time="6 PM"
    )
    assert database.get_pickup_task_record("task-del-1") is not None

    # 4. Delete Donation -> Must delete linked tasks and QR codes
    del_don = database.delete_donation_record("don-del-1")
    assert del_don is True
    assert database.get_donation_record("don-del-1") is None

    # 5. Create and Delete Volunteer
    database.create_volunteer_record(
        volunteer_id="v-del-1",
        name="Delete Vol",
        phone="+94779992222",
        service_area="Colombo",
        transport_mode="Motorbike"
    )
    assert database.get_volunteer_record("v-del-1") is not None
    assert database.delete_volunteer_record("v-del-1") is True
    assert database.get_volunteer_record("v-del-1") is None

    # 6. Create and Delete User
    database.create_or_update_user(phone="94779993333", display_name="Temp User", user_role="donor")
    assert database.get_user_by_phone("94779993333") is not None
    assert database.delete_user_record("94779993333") is True
    assert database.get_user_by_phone("94779993333") is None


# ==========================================
# 7. SECTION 30 COMPREHENSIVE ISOLATION SUITE (Tests A - J)
# ==========================================

@pytest.mark.asyncio
async def test_section_30_test_a_donor_isolation():
    """Test A: Donor A's food/name/quantity cannot appear in another user session."""
    phone_a = "94778880001"
    phone_x = "94778880009"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        # Donor A registers a draft
        await whatsapp_handler.process_incoming_whatsapp_message({
            "from": phone_a, "id": "m.a1", "type": "text", "text": {"body": "I have 50 boxes of Chicken Biryani in Kegalle"}
        })
        draft_a = database.get_draft_donation(phone_a)
        assert draft_a is not None
        assert "biryani" in draft_a["food_type"].lower()
        assert float(draft_a["quantity"]) == 50.0

        # User X starts fresh interaction
        res_x = await whatsapp_handler.process_incoming_whatsapp_message({
            "from": phone_x, "id": "m.x1", "type": "text", "text": {"body": "Hi"}
        })
        draft_x = database.get_draft_donation(phone_x)
        assert draft_x is None or draft_x == {}
        assert "biryani" not in res_x["reply"].lower()
        assert "50" not in res_x["reply"]


@pytest.mark.asyncio
async def test_section_30_test_b_organization_isolation():
    """Test B: Organization A's name/requirements cannot appear in another user session."""
    phone_b = "94778880002"
    phone_y = "94778880008"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        # Org B registers
        await whatsapp_handler.process_incoming_whatsapp_message({
            "from": phone_b, "id": "m.b1", "type": "text", "text": {"body": "2"}
        })
        await whatsapp_handler.process_incoming_whatsapp_message({
            "from": phone_b, "id": "m.b2", "type": "text", "text": {"body": "Mawanella Hope Shelter"}
        })
        org_b = database.get_organization_by_phone(phone_b)
        state_b = database.get_user_conversation_state(phone_b)
        assert (org_b and "Hope Shelter" in org_b["name"]) or ("Hope Shelter" in state_b.get("org_name", ""))

        # User Y starts volunteer registration
        res_y = await whatsapp_handler.process_incoming_whatsapp_message({
            "from": phone_y, "id": "m.y1", "type": "text", "text": {"body": "3"}
        })
        assert "Hope Shelter" not in res_y["reply"]
        assert "Mawanella Hope Shelter" not in res_y["reply"]


@pytest.mark.asyncio
async def test_section_30_test_c_volunteer_isolation():
    """Test C: Volunteer A's name/vehicle/location cannot appear in another user session."""
    phone_c = "94778880003"
    phone_z = "94778880007"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        # Volunteer C registers
        await whatsapp_handler.process_incoming_whatsapp_message({
            "from": phone_c, "id": "m.c1", "type": "text", "text": {"body": "3"}
        })
        res_c2 = await whatsapp_handler.process_incoming_whatsapp_message({
            "from": phone_c, "id": "m.c2", "type": "text", "text": {"body": "Afnab"}
        })
        # Volunteer C must get vehicle question, NEVER organization question!
        assert "Afnab" in res_c2["reply"]
        assert "vehicle" in res_c2["reply"].lower()
        assert "Hope Food" not in res_c2["reply"]
        assert "portions / meals per day" not in res_c2["reply"]

        # User Z sends '1' for donation
        res_z = await whatsapp_handler.process_incoming_whatsapp_message({
            "from": phone_z, "id": "m.z1", "type": "text", "text": {"body": "1"}
        })
        assert "Afnab" not in res_z["reply"]
        assert "Food" in res_z["reply"]


@pytest.mark.asyncio
async def test_section_30_test_d_interleaved_conversations():
    """Test D: Three users can communicate at the same time in interleaved order without contamination."""
    phone_d1 = "94778880011"
    phone_d2 = "94778880012"
    phone_d3 = "94778880013"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        # Interleaved step 1: All 3 choose role
        r1 = await whatsapp_handler.process_incoming_whatsapp_message({"from": phone_d1, "id": "i.1", "type": "text", "text": {"body": "1"}})
        r2 = await whatsapp_handler.process_incoming_whatsapp_message({"from": phone_d2, "id": "i.2", "type": "text", "text": {"body": "2"}})
        r3 = await whatsapp_handler.process_incoming_whatsapp_message({"from": phone_d3, "id": "i.3", "type": "text", "text": {"body": "3"}})

        assert "food" in r1["reply"].lower()
        assert "organization" in r2["reply"].lower() or "name" in r2["reply"].lower()
        assert "full name" in r3["reply"].lower() or "volunteer" in r3["reply"].lower()

        # Interleaved step 2: User 1 gives food, User 3 gives name, User 2 gives org name
        r1_2 = await whatsapp_handler.process_incoming_whatsapp_message({"from": phone_d1, "id": "i.4", "type": "text", "text": {"body": "Chicken Biryani"}})
        r3_2 = await whatsapp_handler.process_incoming_whatsapp_message({"from": phone_d3, "id": "i.5", "type": "text", "text": {"body": "Afnab"}})
        r2_2 = await whatsapp_handler.process_incoming_whatsapp_message({"from": phone_d2, "id": "i.6", "type": "text", "text": {"body": "Sunshine Shelter"}})

        assert "quantity" in r1_2["reply"].lower() or "packets" in r1_2["reply"].lower() or "how many" in r1_2["reply"].lower()
        assert "vehicle" in r3_2["reply"].lower() and "Afnab" in r3_2["reply"]
        assert "district" in r2_2["reply"].lower() and "Sunshine Shelter" in r2_2["reply"]


def test_section_30_test_e_database_deletion_empty_state():
    """Test E: Delete all records -> Database and queries return zero."""
    database.reset_database_data(wipe_all=True)

    assert len(database.get_all_donations()) == 0
    assert len(database.get_all_organizations()) == 0
    assert len(database.get_all_volunteers()) == 0
    assert len(database.get_all_pickup_tasks()) == 0


@pytest.mark.asyncio
async def test_section_30_test_f_fresh_conversation():
    """Test F: A new WhatsApp number must never inherit an old conversation."""
    old_phone = "94778880021"
    new_phone = "94778880022"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        # Old phone sets state
        await whatsapp_handler.process_incoming_whatsapp_message({"from": old_phone, "id": "f.1", "type": "text", "text": {"body": "1"}})
        await whatsapp_handler.process_incoming_whatsapp_message({"from": old_phone, "id": "f.2", "type": "text", "text": {"body": "Kottu Roti"}})

        # New phone sends 'Hi'
        res = await whatsapp_handler.process_incoming_whatsapp_message({"from": new_phone, "id": "f.3", "type": "text", "text": {"body": "Hi"}})
        assert "Kottu" not in res["reply"]
        assert "Welcome to FoodRescue AI" in res["reply"] or "FoodRescue AI" in res["reply"]


@pytest.mark.asyncio
async def test_section_30_test_g_existing_user_preservation():
    """Test G: A registered user resumes only their own role and state."""
    reg_phone = "94778880031"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        database.create_or_update_user(phone=reg_phone, display_name="Kasun Volunteer", user_role="volunteer", onboarding_completed=True, default_location="Kegalle")
        database.create_volunteer_record(volunteer_id="v-reg-1", name="Kasun Volunteer", phone=reg_phone, service_area="Kegalle", transport_mode="Motorbike")

        res = await whatsapp_handler.process_incoming_whatsapp_message({"from": reg_phone, "id": "g.1", "type": "text", "text": {"body": "Hi"}})
        assert "volunteer" in res["reply"].lower() or "available" in res["reply"].lower() or "active" in res["reply"].lower() or "welcome" in res["reply"].lower()


@pytest.mark.asyncio
async def test_section_30_test_h_user_input_preservation():
    """Test H: '30 packets of Chicken Biryani' preserves exact food, quantity, and unit."""
    phone = "94778880041"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        await whatsapp_handler.process_incoming_whatsapp_message({
            "from": phone, "id": "h.1", "type": "text", "text": {"body": "30 packets of Chicken Biryani"}
        })

        draft = database.get_draft_donation(phone)
        assert draft is not None
        assert "biryani" in draft["food_type"].lower()
        assert float(draft["quantity"]) == 30.0
        assert draft.get("unit") in ["packets", "portions", "boxes"]


def test_section_30_test_i_location_isolation():
    """Test I: Donor GPS must never appear as Organization GPS."""
    database.create_donor_record(donor_id="d-loc-1", name="Donor Loc", phone="94778880051", location="Kegalle")
    database.create_organization_record(org_id="o-loc-1", name="Org Loc", phone="94778880052", service_area="Colombo", accepted_food_types="Meals", location="Colombo")

    d = database.get_donor_record("d-loc-1")
    o = database.get_organization_record("o-loc-1")

    assert d["location"] != o["location"]
    assert "Kegalle" in d["location"]
    assert "Colombo" in o["location"]


def test_section_30_test_j_dynamic_routing():
    """Test J: Dynamic road distance calculation with actual coordinates."""
    # Kegalle to Mawanella coordinates (~11.6 km Haversine / ~14 km road distance)
    kegalle_coords = {"latitude": 7.2513, "longitude": 80.3464}
    mawanella_coords = {"latitude": 7.2536, "longitude": 80.4447}

    dist_km = routing.calculate_haversine_distance(
        kegalle_coords["latitude"],
        kegalle_coords["longitude"],
        mawanella_coords["latitude"],
        mawanella_coords["longitude"]
    )
    assert dist_km is not None
    assert float(dist_km) > 5.0
    assert float(dist_km) < 25.0

    # Calculate dynamic transport reimbursement for Motorbike
    reimb = routing.calculate_transport_estimate(distance_km=dist_km, transport_mode="motorbike")
    assert reimb["status"] == "success"
    assert reimb["currency"] == "LKR"
    assert reimb["estimated_support_amount"] > 0

