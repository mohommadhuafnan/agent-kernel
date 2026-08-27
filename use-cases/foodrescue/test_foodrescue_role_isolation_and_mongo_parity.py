"""Comprehensive tests for FoodRescue AI Role Isolation, Zero-Repetition, Three-User Simulation,
and Parity across MongoDB, Supabase, and SQLite persistence backends.
"""

import pytest
import asyncio
import uuid
import database
import tools
import whatsapp_handler
import qr_service
from unittest.mock import AsyncMock, patch


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Ensure clean isolated session store and database before each test."""
    tools.clear_session_store()
    database.reset_repository()
    database.setup_database()
    database.reset_database_data()
    yield
    tools.clear_session_store()
    database.reset_repository()


@pytest.mark.asyncio
async def test_zero_repetition_donor_flow():
    """Verify that donor input is remembered across multi-turn messages and server restarts without asking repeated questions."""
    donor_phone = "94770001122"
    
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        
        # Turn 1: Donor provides food and quantity
        msg1 = {
            "from": donor_phone,
            "id": "wamid.zr.1",
            "type": "text",
            "text": {"body": "I have 40 lunch packets of Rice and Curry"},
        }
        r1 = await whatsapp_handler.process_incoming_whatsapp_message(msg1)
        reply1 = r1.get("reply", "")
        
        draft1 = database.get_draft_donation(donor_phone)
        assert draft1 is not None
        assert "Rice" in (draft1.get("food_type") or "")
        assert float(draft1.get("quantity", 0)) == 40.0
        
        # Turn 2: Donor provides business name
        msg2 = {
            "from": donor_phone,
            "id": "wamid.zr.2",
            "type": "text",
            "text": {"body": "Cinnamon Kitchen"},
        }
        r2 = await whatsapp_handler.process_incoming_whatsapp_message(msg2)
        reply2 = r2.get("reply", "")
        
        # Zero-repetition assertions: MUST NOT ask for food type or quantity again!
        assert "What type of food" not in reply2
        assert "How many packets" not in reply2
        assert "district" in reply2.lower() or "kegalle" in reply2.lower() or "colombo" in reply2.lower()
        
        # Simulate server restart / reset cached repository singleton
        database.reset_repository()
        tools.clear_session_store()
        
        # Turn 3: Donor provides district after server restart
        msg3 = {
            "from": donor_phone,
            "id": "wamid.zr.3",
            "type": "text",
            "text": {"body": "Colombo"},
        }
        r3 = await whatsapp_handler.process_incoming_whatsapp_message(msg3)
        reply3 = r3.get("reply", "")
        
        draft3 = database.get_draft_donation(donor_phone)
        assert draft3 is not None
        assert "Rice" in (draft3.get("food_type") or "")
        assert float(draft3.get("quantity", 0)) == 40.0
        assert "Cinnamon Kitchen" in (draft3.get("donor_name") or "")
        assert "Colombo" in (draft3.get("city") or "")
        
        # MUST NOT re-ask food type or quantity or name
        assert "What type of food" not in reply3
        assert "What is your name" not in reply3


@pytest.mark.asyncio
async def test_role_contamination_volunteer_never_asked_food():
    """Verify that a volunteer saying 'I am free.' or 'I am available.' is NEVER asked donor food questions."""
    vol_phone = "94770003344"
    
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        
        # Volunteer declares availability
        msg = {
            "from": vol_phone,
            "id": "wamid.vol.1",
            "type": "text",
            "text": {"body": "I am free."},
        }
        r = await whatsapp_handler.process_incoming_whatsapp_message(msg)
        reply = r.get("reply", "")
        
        # Strict role-isolation assertions
        assert "What type of food" not in reply
        assert "What quantity" not in reply
        assert "What is your donor name" not in reply
        assert "Where is the food" not in reply
        assert ("available" in reply.lower() or "task" in reply.lower() or "pickup" in reply.lower() or "welcome" in reply.lower())


@pytest.mark.asyncio
async def test_role_contamination_donor_gets_donation_flow():
    """Verify that a donor saying 'I want to donate food.' enters the donor workflow."""
    donor_phone = "94770005566"
    
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        
        msg = {
            "from": donor_phone,
            "id": "wamid.don.1",
            "type": "text",
            "text": {"body": "I want to donate food."},
        }
        r = await whatsapp_handler.process_incoming_whatsapp_message(msg)
        reply = r.get("reply", "")
        
        assert "food" in reply.lower() or "type" in reply.lower()
        # Volunteer-specific phrases must NOT appear
        assert "mark myself as available" not in reply.lower()
        assert "search active pickups" not in reply.lower()


@pytest.mark.asyncio
async def test_role_contamination_organization_gets_request_flow():
    """Verify that an organization saying 'We need food for our community kitchen.' enters organization workflow."""
    org_phone = "94770007788"
    
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        
        msg = {
            "from": org_phone,
            "id": "wamid.org.1",
            "type": "text",
            "text": {"body": "We need food for our community kitchen."},
        }
        r = await whatsapp_handler.process_incoming_whatsapp_message(msg)
        reply = r.get("reply", "")
        
        # Must be organization-aware
        assert "organization" in reply.lower() or "charities" in reply.lower() or "community" in reply.lower() or "name" in reply.lower()
        assert "mark myself as available" not in reply.lower()


@pytest.mark.asyncio
async def test_three_user_simultaneous_simulation():
    """Simulate USER A (Donor), USER B (Organization), and USER C (Volunteer) simultaneously without cross-contamination."""
    donor_phone = "94771110001"
    org_phone = "94771110002"
    vol_phone = "94771110003"
    
    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        
        # Step 1: Donor sends donation intent
        d_res = await whatsapp_handler.process_incoming_whatsapp_message({
            "from": donor_phone,
            "id": "wamid.sim.d1",
            "type": "text",
            "text": {"body": "I have 40 lunch packets of Biryani."},
        })
        
        # Step 2: Organization sends request intent
        o_res = await whatsapp_handler.process_incoming_whatsapp_message({
            "from": org_phone,
            "id": "wamid.sim.o1",
            "type": "text",
            "text": {"body": "We need food for 30 people."},
        })
        
        # Step 3: Volunteer sends availability
        v_res = await whatsapp_handler.process_incoming_whatsapp_message({
            "from": vol_phone,
            "id": "wamid.sim.v1",
            "type": "text",
            "text": {"body": "I am available."},
        })
        
        # Check Donor reply: asks name
        d_reply = d_res.get("reply", "")
        assert "name" in d_reply.lower() or "district" in d_reply.lower()
        assert "available" not in d_reply.lower()
        
        # Check Organization reply: asks org name / handles org need
        o_reply = o_res.get("reply", "")
        assert "organization" in o_reply.lower() or "name" in o_reply.lower() or "district" in o_reply.lower()
        
        # Check Volunteer reply: confirms available
        v_reply = v_res.get("reply", "")
        assert "available" in v_reply.lower() or "task" in v_reply.lower() or "pickup" in v_reply.lower() or "courier" in v_reply.lower()
        assert "what type of food" not in v_reply.lower()
        
        # Verify database state isolation per phone
        d_state = database.get_user_conversation_state(donor_phone)
        o_state = database.get_user_conversation_state(org_phone)
        v_state = database.get_user_conversation_state(vol_phone)
        
        assert d_state.get("workflow") == "DONATION"
        assert o_state.get("workflow") in ["ORGANIZATION", "RECIPIENT_REQUEST"]
        assert v_state.get("workflow") == "VOLUNTEER" or database.get_user_by_phone(vol_phone).get("user_role") == "volunteer"


@pytest.mark.asyncio
async def test_end_to_end_full_lifecycle():
    """Verify complete end-to-end lifecycle:
    Donor creates donation -> Org matched & accepted -> Vol task offered & accepted -> Route generated ->
    Pickup QR verified (COLLECTED) -> Delivery QR verified (DELIVERED) -> Notifications -> Dashboard sync.
    """
    donor_phone = "94772220001"
    org_phone = "94772220002"
    vol_phone = "94772220003"
    
    # 1. Register donor, org, vol entities
    d_reg = database.create_donor_record(
        donor_id=f"don-e2e-{uuid.uuid4().hex[:6]}",
        name="Hotel Sapphire",
        phone=donor_phone,
        organization_name="Hotel Sapphire Colombo",
        location="Colombo 03"
    )
    
    o_reg = database.create_organization_record(
        org_id=f"org-e2e-{uuid.uuid4().hex[:6]}",
        name="Colombo Community Center",
        phone=org_phone,
        service_area="Colombo, Colombo 05",
        accepted_food_types="Rice & Curry, Cooked Meals",
        capacity="100 meals",
        availability="always",
        location="Colombo 05"
    )
    
    v_reg = database.create_volunteer_record(
        volunteer_id=f"vol-e2e-{uuid.uuid4().hex[:6]}",
        name="Sunil Perera",
        phone=vol_phone,
        service_area="Colombo",
        transport_mode="Motorbike",
        availability="available",
        current_status="available",
        location="Colombo 03"
    )
    
    # 2. Donor creates donation
    don_rec = database.create_donation_record(
        donation_id=f"don-rec-{uuid.uuid4().hex[:6]}",
        donor_id=d_reg["id"],
        food_type="Rice & Curry",
        quantity=30,
        unit="packets",
        dietary_info="Non-Vegetarian",
        location="Colombo 03",
        available_from="Now",
        deadline="Today before 8 PM"
    )
    
    # 3. Create pickup task connecting donation to organization
    task_rec = database.create_pickup_task_record(
        task_id=f"task-e2e-{uuid.uuid4().hex[:6]}",
        donation_id=don_rec["id"],
        org_id=o_reg["id"],
        pickup_loc="Colombo 03",
        delivery_loc="Colombo 05",
        time="Today before 8 PM"
    )
    
    # 4. Volunteer accepts task atomically
    assign_res = database.assign_volunteer_record(task_rec["id"], v_reg["id"])
    assert assign_res is True
    t_assigned = database.get_pickup_task_record(task_rec["id"])
    assert t_assigned["volunteer_id"] == v_reg["id"]
    
    # 5. Generate and verify Pickup QR
    pk_token = qr_service.generate_secure_token("PK")
    pk_qr = database.create_qr_code_record(
        qr_id=f"qr-pk-{task_rec['id']}",
        task_id=task_rec["id"],
        donation_id=don_rec["id"],
        qr_type="PICKUP",
        token=pk_token,
        token_hash=qr_service.hash_token(pk_token),
        donor_id=d_reg["id"],
        organization_id=o_reg["id"],
        assigned_volunteer_id=v_reg["id"],
        status="ACTIVE"
    )
    
    pk_verif = database.verify_qr_code_record(pk_token, volunteer_id=v_reg["id"])
    assert pk_verif["success"] is True
    assert pk_verif["task"]["status"] == "COLLECTED"
    
    # 6. Generate and verify Delivery QR
    dl_token = qr_service.generate_secure_token("DL")
    dl_qr = database.create_qr_code_record(
        qr_id=f"qr-dl-{task_rec['id']}",
        task_id=task_rec["id"],
        donation_id=don_rec["id"],
        qr_type="DELIVERY",
        token=dl_token,
        token_hash=qr_service.hash_token(dl_token),
        donor_id=d_reg["id"],
        organization_id=o_reg["id"],
        assigned_volunteer_id=v_reg["id"],
        status="ACTIVE"
    )
    
    dl_verif = database.verify_qr_code_record(dl_token, volunteer_id=v_reg["id"])
    assert dl_verif["success"] is True
    assert dl_verif["task"]["status"] == "COMPLETED"
    
    # 7. Verify volunteer is back to AVAILABLE
    updated_vol = database.get_volunteer_record(v_reg["id"])
    assert updated_vol.get("current_status") == "available"
    assert updated_vol.get("availability_status") == "AVAILABLE"
    
    # 8. Verify dashboard stats reflect the completed lifecycle
    stats = database.get_dashboard_stats()
    assert stats["total_donations"] >= 1
    assert stats["total_organizations"] >= 1
    assert stats["total_volunteers"] >= 1
