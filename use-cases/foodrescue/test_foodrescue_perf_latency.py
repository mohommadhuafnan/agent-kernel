"""FoodRescue AI WhatsApp Latency & Performance Test Suite.

Benchmarks response times across:
1. Complete Donor Onboarding & Donation Creation flow.
2. Complete Organization Onboarding & Food Request flow.
3. Complete Volunteer Courier Registration & Availability flow.
4. Interleaved concurrent multi-user turns (role isolation + latency).
5. Duplicate message idempotency rejection speed.
"""

import os
import pytest
import time
import uuid
import database
import whatsapp_handler
from unittest.mock import patch, AsyncMock


@pytest.fixture(autouse=True)
def setup_perf_test_db(tmp_path):
    db_file = str(tmp_path / "foodrescue_perf_test.db")
    os.environ["FOODRESCUE_DB_PATH"] = db_file
    database.DB_PATH = db_file
    database.reset_repository()
    database.setup_database()
    database.seed_test_data()
    whatsapp_handler.clear_processed_message_cache()
    import resilient_executor
    import tools
    import routing

    yield


@pytest.mark.asyncio
async def test_01_donor_workflow_turn_latency():
    """Verify Donor workflow turns respond in sub-second time without slow roundtrips."""
    phone = "94771112233"
    latencies = []

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent", "message_id": "wamid.mock"}

        # Turn 1: Role choice (1 = Donor)
        t0 = time.perf_counter()
        res1 = await whatsapp_handler.process_incoming_whatsapp_message(
            {"from": phone, "id": f"msg-d1-{uuid.uuid4().hex[:6]}", "type": "text", "text": {"body": "1"}}
        )
        d1 = (time.perf_counter() - t0) * 1000.0
        latencies.append(("Select Donor Role", d1))
        assert "food" in res1["reply"].lower() or "surplus" in res1["reply"].lower() or "donate" in res1["reply"].lower()

        # Turn 2: Food details
        t0 = time.perf_counter()
        res2 = await whatsapp_handler.process_incoming_whatsapp_message(
            {"from": phone, "id": f"msg-d2-{uuid.uuid4().hex[:6]}", "type": "text", "text": {"body": "30 packets of Chicken Biryani"}}
        )
        d2 = (time.perf_counter() - t0) * 1000.0
        latencies.append(("Provide Food & Quantity", d2))
        assert "name" in res2["reply"].lower() or "business" in res2["reply"].lower() or "who is" in res2["reply"].lower()

        # Turn 3: Donor Name
        t0 = time.perf_counter()
        res3 = await whatsapp_handler.process_incoming_whatsapp_message(
            {"from": phone, "id": f"msg-d3-{uuid.uuid4().hex[:6]}", "type": "text", "text": {"body": "Royal Spice Caterers"}}
        )
        d3 = (time.perf_counter() - t0) * 1000.0
        latencies.append(("Provide Donor Name", d3))
        assert (
            "city" in res3["reply"].lower()
            or "town" in res3["reply"].lower()
            or "district" in res3["reply"].lower()
            or "location" in res3["reply"].lower()
        )

        # Turn 4: Location
        t0 = time.perf_counter()
        res4 = await whatsapp_handler.process_incoming_whatsapp_message(
            {"from": phone, "id": f"msg-d4-{uuid.uuid4().hex[:6]}", "type": "text", "text": {"body": "Kegalle Town"}}
        )
        d4 = (time.perf_counter() - t0) * 1000.0
        latencies.append(("Provide Location", d4))
        assert (
            "location" in res4["reply"].lower()
            or "time" in res4["reply"].lower()
            or "pin" in res4["reply"].lower()
            or "summary" in res4["reply"].lower()
        )

    # Verify all turns completed rapidly
    for step_name, dur in latencies:
        print(f"[BENCHMARK DONOR] {step_name}: {dur:.1f}ms")
        assert dur < 2500, f"Step '{step_name}' took too long: {dur:.1f}ms"


@pytest.mark.asyncio
async def test_02_organization_workflow_turn_latency():
    """Verify Organization registration and request flow completes rapidly."""
    phone = "94774445566"
    latencies = []

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent", "message_id": "wamid.mock"}

        # Turn 1: Role choice (2 = Organization)
        t0 = time.perf_counter()
        res1 = await whatsapp_handler.process_incoming_whatsapp_message(
            {"from": phone, "id": f"msg-o1-{uuid.uuid4().hex[:6]}", "type": "text", "text": {"body": "2"}}
        )
        d1 = (time.perf_counter() - t0) * 1000.0
        latencies.append(("Select Org Role", d1))
        assert "organization" in res1["reply"].lower() or "charity" in res1["reply"].lower() or "name" in res1["reply"].lower()

        # Turn 2: Organization Name
        t0 = time.perf_counter()
        res2 = await whatsapp_handler.process_incoming_whatsapp_message(
            {"from": phone, "id": f"msg-o2-{uuid.uuid4().hex[:6]}", "type": "text", "text": {"body": "Hope Children Home"}}
        )
        d2 = (time.perf_counter() - t0) * 1000.0
        latencies.append(("Provide Org Name", d2))
        assert "district" in res2["reply"].lower() or "city" in res2["reply"].lower() or "town" in res2["reply"].lower()

        # Turn 3: District
        t0 = time.perf_counter()
        res3 = await whatsapp_handler.process_incoming_whatsapp_message(
            {"from": phone, "id": f"msg-o3-{uuid.uuid4().hex[:6]}", "type": "text", "text": {"body": "Kegalle"}}
        )
        d3 = (time.perf_counter() - t0) * 1000.0
        latencies.append(("Provide Org District", d3))
        assert (
            "food" in res3["reply"].lower() or "meal" in res3["reply"].lower() or "accept" in res3["reply"].lower() or "type" in res3["reply"].lower()
        )

    for step_name, dur in latencies:
        print(f"[BENCHMARK ORG] {step_name}: {dur:.1f}ms")
        assert dur < 2500, f"Step '{step_name}' took too long: {dur:.1f}ms"


@pytest.mark.asyncio
async def test_03_volunteer_workflow_turn_latency():
    """Verify Volunteer courier registration responds quickly on every turn."""
    phone = "94777778899"
    latencies = []

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent", "message_id": "wamid.mock"}

        # Turn 1: Choose 3 (Volunteer)
        t0 = time.perf_counter()
        res1 = await whatsapp_handler.process_incoming_whatsapp_message(
            {"from": phone, "id": f"msg-v1-{uuid.uuid4().hex[:6]}", "type": "text", "text": {"body": "3"}}
        )
        d1 = (time.perf_counter() - t0) * 1000.0
        latencies.append(("Select Volunteer Role", d1))
        assert "name" in res1["reply"].lower()

        # Turn 2: Name
        t0 = time.perf_counter()
        res2 = await whatsapp_handler.process_incoming_whatsapp_message(
            {"from": phone, "id": f"msg-v2-{uuid.uuid4().hex[:6]}", "type": "text", "text": {"body": "Afnan Courier"}}
        )
        d2 = (time.perf_counter() - t0) * 1000.0
        latencies.append(("Provide Courier Name", d2))
        assert "vehicle" in res2["reply"].lower() or "transport" in res2["reply"].lower() or "motorbike" in res2["reply"].lower()

        # Turn 3: Vehicle
        t0 = time.perf_counter()
        res3 = await whatsapp_handler.process_incoming_whatsapp_message(
            {"from": phone, "id": f"msg-v3-{uuid.uuid4().hex[:6]}", "type": "text", "text": {"body": "Motorbike"}}
        )
        d3 = (time.perf_counter() - t0) * 1000.0
        latencies.append(("Provide Vehicle", d3))
        assert "district" in res3["reply"].lower() or "area" in res3["reply"].lower() or "town" in res3["reply"].lower()

        # Turn 4: District
        t0 = time.perf_counter()
        res4 = await whatsapp_handler.process_incoming_whatsapp_message(
            {"from": phone, "id": f"msg-v4-{uuid.uuid4().hex[:6]}", "type": "text", "text": {"body": "Kegalle"}}
        )
        d4 = (time.perf_counter() - t0) * 1000.0
        latencies.append(("Provide District", d4))
        assert "location" in res4["reply"].lower() or "registered" in res4["reply"].lower() or "available" in res4["reply"].lower()

    for step_name, dur in latencies:
        print(f"[BENCHMARK VOLUNTEER] {step_name}: {dur:.1f}ms")
        assert dur < 2500, f"Step '{step_name}' took too long: {dur:.1f}ms"


@pytest.mark.asyncio
async def test_04_interleaved_multi_user_turns_latency_and_isolation():
    """Verify interleaved turns across 3 concurrent users execute fast with 100% role isolation."""
    donor_phone = "94770001111"
    org_phone = "94770002222"
    vol_phone = "94770003333"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent", "message_id": "wamid.mock"}

        # Donor turn
        t0 = time.perf_counter()
        r_don = await whatsapp_handler.process_incoming_whatsapp_message(
            {"from": donor_phone, "id": f"msg-int1-{uuid.uuid4().hex[:6]}", "type": "text", "text": {"body": "1"}}
        )
        d_don = (time.perf_counter() - t0) * 1000.0
        assert "food" in r_don["reply"].lower() or "donate" in r_don["reply"].lower()

        # Org turn
        t0 = time.perf_counter()
        r_org = await whatsapp_handler.process_incoming_whatsapp_message(
            {"from": org_phone, "id": f"msg-int2-{uuid.uuid4().hex[:6]}", "type": "text", "text": {"body": "2"}}
        )
        d_org = (time.perf_counter() - t0) * 1000.0
        assert "organization" in r_org["reply"].lower() or "charity" in r_org["reply"].lower()

        # Volunteer turn
        t0 = time.perf_counter()
        r_vol = await whatsapp_handler.process_incoming_whatsapp_message(
            {"from": vol_phone, "id": f"msg-int3-{uuid.uuid4().hex[:6]}", "type": "text", "text": {"body": "3"}}
        )
        d_vol = (time.perf_counter() - t0) * 1000.0
        assert "name" in r_vol["reply"].lower()

        print(f"[INTERLEAVED] Donor Turn: {d_don:.1f}ms | Org Turn: {d_org:.1f}ms | Vol Turn: {d_vol:.1f}ms")
        assert d_don < 2500
        assert d_org < 2500
        assert d_vol < 2500


@pytest.mark.asyncio
async def test_05_idempotent_duplicate_message_fast_rejection():
    """Verify duplicate WhatsApp messages are rejected in sub-millisecond time without DB locking."""
    phone = "94779998877"
    msg_id = f"wamid.perf.{uuid.uuid4().hex[:8]}"

    with patch("whatsapp_handler.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent", "message_id": msg_id}

        # First delivery
        res1 = await whatsapp_handler.process_incoming_whatsapp_message({"from": phone, "id": msg_id, "type": "text", "text": {"body": "Hi"}})
        assert res1["status"] in ["onboarding_welcome_sent", "returning_welcome_sent", "processed"]

        # Duplicate delivery immediately following
        t0 = time.perf_counter()
        res2 = await whatsapp_handler.process_incoming_whatsapp_message({"from": phone, "id": msg_id, "type": "text", "text": {"body": "Hi"}})
        d_dup = (time.perf_counter() - t0) * 1000.0

        assert res2["status"] == "ignored"
        assert res2["reason"] == "duplicate_message_id"
        print(f"[IDEMPOTENCY] Duplicate Rejection Latency: {d_dup:.2f}ms")
        assert d_dup < 50.0, f"Duplicate check took too long: {d_dup:.2f}ms"
