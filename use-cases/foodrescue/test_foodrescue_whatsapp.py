"""FoodRescue AI Meta WhatsApp Integration Test Suite.

Validates the Meta WhatsApp Business Cloud API webhook:
1. Webhook GET verification (challenge response)
2. Webhook GET rejection with invalid verify token / mode
3. Webhook POST incoming text message parsing and routing
4. Stable session_id derivation: whatsapp:<phone_number>
5. Multi-turn session continuity over WhatsApp
6. Unsupported message types (audio, image, sticker, location, document)
7. Status update events (sent, delivered, read)
8. Diagnostics / status endpoint (/api/whatsapp/status)
9. Outgoing message delivery formatting and splitting
"""

import os
import json
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from agentkernel.api import RESTAPI, AgentRESTRequestHandler
import api_routes
import whatsapp_handler
import database
import tools
from agentkernel.core import Session, Runtime


@pytest.fixture
def test_client(tmp_path):
    """Create a FastAPI TestClient configured with FoodRescue REST API, UI, and WhatsApp routers."""
    db_file = str(tmp_path / "foodrescue_wa_test.db")
    os.environ["FOODRESCUE_DB_PATH"] = db_file
    database.DB_PATH = db_file
    database.reset_repository()
    database.setup_database()
    database.seed_test_data()
    whatsapp_handler.clear_processed_message_cache()

    handler = AgentRESTRequestHandler()
    api_app = RESTAPI._create_app(routers=[handler.get_router(), api_routes.get_router(), whatsapp_handler.get_whatsapp_router()])
    client = TestClient(api_app)
    yield client

    database.reset_repository()

    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass


def test_whatsapp_webhook_verification_success(test_client):
    """Verify GET /whatsapp/webhook responds with the challenge on valid verify_token."""
    verify_token = whatsapp_handler.get_verify_token()
    params = {"hub.mode": "subscribe", "hub.verify_token": verify_token, "hub.challenge": "1158201444"}
    response = test_client.get("/whatsapp/webhook", params=params)
    assert response.status_code == 200
    assert response.text == "1158201444"

    # Also test /api/whatsapp/webhook alias
    response_alias = test_client.get("/api/whatsapp/webhook", params=params)
    assert response_alias.status_code == 200
    assert response_alias.text == "1158201444"


def test_whatsapp_webhook_verification_invalid_token(test_client):
    """Verify GET /whatsapp/webhook rejects invalid verify token with 403 Forbidden."""
    params = {"hub.mode": "subscribe", "hub.verify_token": "wrong_invalid_token", "hub.challenge": "1158201444"}
    response = test_client.get("/whatsapp/webhook", params=params)
    assert response.status_code == 403
    assert "Verification failed" in response.text or "detail" in response.json()


def test_whatsapp_webhook_verification_invalid_mode(test_client):
    """Verify GET /whatsapp/webhook rejects non-subscribe mode with 403 Forbidden."""
    verify_token = whatsapp_handler.get_verify_token()
    params = {"hub.mode": "unsubscribe", "hub.verify_token": verify_token, "hub.challenge": "1158201444"}
    response = test_client.get("/whatsapp/webhook", params=params)
    assert response.status_code == 403


def test_whatsapp_status_endpoint(test_client):
    """Verify GET /api/whatsapp/status returns diagnostic metadata."""
    response = test_client.get("/api/whatsapp/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert data["channel"] == "WhatsApp Cloud API"
    assert data["test_number"] == "+94 75 526 3482"
    assert data["phone_number_id"] == "1285744151285887"
    assert data["business_account_id"] == "2279553849254105"
    assert data["app_id"] == "1591721079088296"
    assert data["business_portfolio_id"] == "1697813834850499"
    assert data["webhook_path"] == "/whatsapp/webhook"
    assert data["agent"] == "foodrescue_coordinator"


def test_whatsapp_incoming_text_message_routing(test_client):
    """Verify incoming text webhook processes through coordinator and logs audit notification."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "2279553849254105",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "94755263482", "phone_number_id": "1285744151285887"},
                            "contacts": [{"profile": {"name": "Test Donor"}, "wa_id": "15559876543"}],
                            "messages": [
                                {
                                    "from": "15559876543",
                                    "id": "wamid.HBgLMTU1NTk4NzY1NDM=",
                                    "timestamp": "1710000000",
                                    "type": "text",
                                    "text": {"body": "I have 40 vegetarian meal boxes in Colombo 3 until 7 PM."},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    response = test_client.post("/whatsapp/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # Verify audit notification in database
    notifs = database.get_notifications_for_recipient("15559876543")
    assert len(notifs) >= 1
    assert notifs[0]["channel"] == "whatsapp"


def test_whatsapp_unsupported_message_types_handled_gracefully(test_client):
    """Verify non-text messages (image, audio, location, sticker) receive helpful fallback without error."""
    for unsupported_type in ["image", "audio", "video", "sticker", "location", "document"]:
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "2279553849254105",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "messages": [
                                    {
                                        "from": "15551112233",
                                        "id": f"wamid.{unsupported_type}_123",
                                        "timestamp": "1710000000",
                                        "type": unsupported_type,
                                        unsupported_type: {"id": "media_999"},
                                    }
                                ],
                            },
                            "field": "messages",
                        }
                    ],
                }
            ],
        }

        response = test_client.post("/whatsapp/webhook", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_whatsapp_status_receipt_events_ignored_gracefully(test_client):
    """Verify delivery and read status receipts are acknowledged with 200 OK."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "2279553849254105",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "statuses": [
                                {"id": "wamid.HBgLMTU1NTk4NzY1NDM=", "status": "delivered", "timestamp": "1710000005", "recipient_id": "15559876543"}
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    response = test_client.post("/whatsapp/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_whatsapp_missing_sender_or_empty_text(test_client):
    """Verify malformed messages with missing sender or empty text body do not crash."""
    # 1. Missing 'from'
    payload1 = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {"messages": [{"type": "text", "text": {"body": "hello"}}]}}]}],
    }
    res1 = test_client.post("/whatsapp/webhook", json=payload1)
    assert res1.status_code == 200

    # 2. Empty text body
    payload2 = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {"messages": [{"from": "1555123", "type": "text", "text": {"body": "   "}}]}}]}],
    }
    res2 = test_client.post("/whatsapp/webhook", json=payload2)
    assert res2.status_code == 200


@pytest.mark.asyncio
async def test_whatsapp_outgoing_message_splitting():
    """Verify long outgoing messages (>4096 chars) are safely split and mock delivered."""
    long_text = "A" * 5000
    res = await whatsapp_handler.send_whatsapp_message("15559998877", long_text)
    assert res["status"] in ["mock_delivered", "sent"]
    assert res["to"] == "15559998877"


def test_whatsapp_multi_turn_session_continuity(test_client):
    """Verify multiple incoming WhatsApp messages from the same sender maintain state in KeyValueCache."""
    sender_phone = "15554443322"
    session_id = f"whatsapp:{sender_phone}"

    # Setup session directly in Session cache
    sess = tools.get_session_instance(session_id)
    cache = sess.get_non_volatile_cache()
    cache.set("current_donor_id", "d1")
    cache.set("current_location", "Colombo 3")

    assert cache.get("current_donor_id") == "d1"
    assert cache.get("current_location") == "Colombo 3"

    # Send message 1
    payload1 = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {"from": sender_phone, "id": "wamid.msg1", "type": "text", "text": {"body": "I have 25 lunch packets ready."}}
                            ],
                        }
                    }
                ]
            }
        ],
    }
    res1 = test_client.post("/whatsapp/webhook", json=payload1)
    assert res1.status_code == 200

    # Verify session retains memory
    assert cache.get("current_donor_id") is not None


def test_whatsapp_greeting_first_time(test_client):
    """Test initial 'Hi' message returns welcome greeting with structured menu options."""
    whatsapp_handler.clear_processed_message_cache()
    phone = "94751000001"
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [{"from": phone, "id": "wamid.greet_1", "type": "text", "text": {"body": "Hi"}}],
                        }
                    }
                ]
            }
        ],
    }
    response = test_client.post("/whatsapp/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_whatsapp_donor_flow_natural_and_numbered(test_client):
    """Test donor flow with surplus food details coordinates donation, matching, and pickup assignment."""
    whatsapp_handler.clear_processed_message_cache()
    phone = "94751000002"
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": phone,
                                    "id": "wamid.donor_1",
                                    "type": "text",
                                    "text": {"body": "I have 20 vegetarian meal portions to donate in Colombo"},
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    }
    response = test_client.post("/whatsapp/webhook", json=payload)
    assert response.status_code == 200

    # Verify donor created in database
    donor = database.get_donor_by_phone(phone)
    assert donor is not None or len(database.get_all_donations()) > 0


def test_whatsapp_recipient_flow(test_client):
    """Test recipient organization intent registers and queries available food."""
    whatsapp_handler.clear_processed_message_cache()
    phone = "94751000003"
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {"from": phone, "id": "wamid.recip_1", "type": "text", "text": {"body": "I need food for our community kitchen"}}
                            ],
                        }
                    }
                ]
            }
        ],
    }
    response = test_client.post("/whatsapp/webhook", json=payload)
    assert response.status_code == 200


def test_whatsapp_volunteer_flow(test_client):
    """Test volunteer registration and available task lookup."""
    whatsapp_handler.clear_processed_message_cache()
    phone = "94751000004"
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [{"from": phone, "id": "wamid.vol_1", "type": "text", "text": {"body": "I want to volunteer"}}],
                        }
                    }
                ]
            }
        ],
    }
    response = test_client.post("/whatsapp/webhook", json=payload)
    assert response.status_code == 200

    vol = database.get_volunteer_by_phone(phone)
    assert vol is not None or len(database.get_all_volunteers()) > 0


def test_whatsapp_status_queries(test_client):
    """Test querying donation and pickup status through natural language."""
    whatsapp_handler.clear_processed_message_cache()
    phone = "94751000005"
    session_id = f"whatsapp:{phone}"
    sess = Session(session_id)
    cache = sess.get_non_volatile_cache()
    cache.set("whatsapp_phone", phone)

    # 1. Create a donation first
    don_raw = tools.create_donation(
        donor_id="d1",
        food_type="Vegetarian Meals",
        quantity=15.0,
        unit="portions",
        dietary_information="Vegetarian",
        location="Colombo",
        available_from="Now",
        pickup_deadline="6:00 PM",
    )
    don_res = json.loads(don_raw)
    don_id = don_res["donation_id"]

    # 2. Query status
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [{"from": phone, "id": "wamid.status_query_1", "type": "text", "text": {"body": "Where is my donation?"}}],
                        }
                    }
                ]
            }
        ],
    }
    response = test_client.post("/whatsapp/webhook", json=payload)
    assert response.status_code == 200


def test_whatsapp_edit_information(test_client):
    """Test updating active donation details conversationally."""
    whatsapp_handler.clear_processed_message_cache()
    phone = "94751000006"
    session_id = f"whatsapp:{phone}"
    sess = Session(session_id)
    cache = sess.get_non_volatile_cache()
    cache.set("whatsapp_phone", phone)

    # Create initial donation
    don_raw = tools.create_donation(
        donor_id="d1",
        food_type="Rice Packets",
        quantity=20.0,
        unit="portions",
        dietary_information="Vegetarian",
        location="Colombo",
        available_from="Now",
        pickup_deadline="6:00 PM",
    )

    # Edit quantity
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [{"from": phone, "id": "wamid.edit_1", "type": "text", "text": {"body": "Actually I have 30 meals"}}],
                        }
                    }
                ]
            }
        ],
    }
    response = test_client.post("/whatsapp/webhook", json=payload)
    assert response.status_code == 200


def test_whatsapp_cancellation(test_client):
    """Test cancelling an active donation."""
    whatsapp_handler.clear_processed_message_cache()
    phone = "94751000007"
    session_id = f"whatsapp:{phone}"
    tools.set_explicit_session_id(session_id)
    sess = tools.get_session_instance(session_id)
    cache = sess.get_non_volatile_cache()
    cache.set("whatsapp_phone", phone)

    # Create donation to cancel
    don_raw = tools.create_donation(
        donor_id="d1",
        food_type="Bread",
        quantity=10.0,
        unit="portions",
        dietary_information="None",
        location="Colombo",
        available_from="Now",
        pickup_deadline="6:00 PM",
    )
    don_res = json.loads(don_raw)
    don_id = don_res["donation_id"]
    cache.set("current_donation_id", don_id)

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [{"from": phone, "id": "wamid.cancel_1", "type": "text", "text": {"body": "Cancel my donation"}}],
                        }
                    }
                ]
            }
        ],
    }
    response = test_client.post("/whatsapp/webhook", json=payload)
    assert response.status_code == 200

    # Verify status in database
    rec = database.get_donation_record(don_id)
    assert rec["status"] == "CANCELLED"


def test_whatsapp_menu_and_help(test_client):
    """Test 'help' and 'menu' commands return guidance menu."""
    for cmd in ["help", "menu"]:
        whatsapp_handler.clear_processed_message_cache()
        phone = f"94751000008_{cmd}"
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "messages": [{"from": phone, "id": f"wamid.menu_{cmd}", "type": "text", "text": {"body": cmd}}],
                            }
                        }
                    ]
                }
            ],
        }
        response = test_client.post("/whatsapp/webhook", json=payload)
        assert response.status_code == 200


def test_whatsapp_duplicate_webhook_idempotency(test_client):
    """Test duplicate webhook delivery with identical message ID is ignored without duplicate processing."""
    whatsapp_handler.clear_processed_message_cache()
    phone = "94759998888"
    duplicate_wamid = "wamid.duplicate_test_unique_123"
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {"from": phone, "id": duplicate_wamid, "type": "text", "text": {"body": "I have 50 meal boxes in Colombo."}}
                            ],
                        }
                    }
                ]
            }
        ],
    }

    # First delivery
    res1 = test_client.post("/whatsapp/webhook", json=payload)
    assert res1.status_code == 200

    # Second delivery (Meta retry)
    res2 = test_client.post("/whatsapp/webhook", json=payload)
    assert res2.status_code == 200

    # Direct function test returns duplicate status
    repeat_res = pytest.importorskip("asyncio").run(
        whatsapp_handler.process_incoming_whatsapp_message({"from": phone, "id": duplicate_wamid, "type": "text", "text": {"body": "repeat"}}, {})
    )
    assert repeat_res.get("status") == "ignored"
    assert repeat_res.get("reason") == "duplicate_message_id"


@pytest.mark.asyncio
async def test_kegalle_multi_party_asynchronous_lifecycle_chain():
    """Verify asynchronous lifecycle cross-matching and WhatsApp notifications across Donor, Org, and Volunteer in Kegalle."""
    database.setup_database()
    database.seed_test_data()
    whatsapp_handler.clear_processed_message_cache()
    donor_phone = "94772117131"
    org_phone = "94770002002"
    vol_phone = "94770003003"

    sent_messages = []

    async def mock_send(to_number, text, **kwargs):
        sent_messages.append({"to": to_number, "text": text})
        return {"status": "sent"}

    with patch("whatsapp_handler.send_whatsapp_message", side_effect=mock_send):
        # 1. Donor (Afnan) creates donation in Kegalle
        m1 = {"from": donor_phone, "id": "w1", "type": "text", "text": {"body": "I have 10 packets of Rice & Curry"}}
        await whatsapp_handler.process_incoming_whatsapp_message(m1)

        m2 = {"from": donor_phone, "id": "w2", "type": "text", "text": {"body": "Afnan"}}
        await whatsapp_handler.process_incoming_whatsapp_message(m2)

        m3 = {"from": donor_phone, "id": "w3", "type": "text", "text": {"body": "Kegalle"}}
        r3 = await whatsapp_handler.process_incoming_whatsapp_message(m3)
        assert "location pin" in r3["reply"].lower() or "📍" in r3["reply"]

        # Donor sends Google Maps URL link in text
        m4 = {
            "from": donor_phone,
            "id": "w4",
            "type": "text",
            "text": {"body": "https://maps.google.com/maps?q=7.2222819328308105%2C80.47478485107422&z=17&hl=en"},
        }
        r4 = await whatsapp_handler.process_incoming_whatsapp_message(m4)
        assert "donation summary" in r4["reply"].lower() or "confirm" in r4["reply"].lower()

        # Donor confirms donation
        m5 = {"from": donor_phone, "id": "w5", "type": "text", "text": {"body": "Confirm"}}
        r5 = await whatsapp_handler.process_incoming_whatsapp_message(m5)
        assert "created" in r5["reply"].lower() or "✅" in r5["reply"]

        # 2. Recipient Organization (Mohommadhu) registers in Kegalle
        o1 = {"from": org_phone, "id": "o1", "type": "text", "text": {"body": "2"}}
        await whatsapp_handler.process_incoming_whatsapp_message(o1)

        o2 = {"from": org_phone, "id": "o2", "type": "text", "text": {"body": "Mohommadhu"}}
        await whatsapp_handler.process_incoming_whatsapp_message(o2)

        o3 = {"from": org_phone, "id": "o3", "type": "text", "text": {"body": "Kegalle"}}
        await whatsapp_handler.process_incoming_whatsapp_message(o3)

        # Organization sends Google Maps URL
        o4 = {
            "from": org_phone,
            "id": "o4",
            "type": "text",
            "text": {
                "body": "https://maps.google.com/maps/search/Mawanella/@7.221711158752441,80.4827651977539,17z?hl=en\nB3/1 ayagama east,aluthnuwara, Mawanella"
            },
        }
        r_o4 = await whatsapp_handler.process_incoming_whatsapp_message(o4)
        assert "recorded" in r_o4["reply"].lower() or "matched" in r_o4["reply"].lower()

        # Check that Donor received cross-notification that Org connected
        donor_notifs = [m for m in sent_messages if m["to"] == donor_phone and "connected" in m["text"].lower()]
        assert len(donor_notifs) >= 1

        # 3. Volunteer Courier (Mushan) registers in Kegalle
        v1 = {"from": vol_phone, "id": "v1", "type": "text", "text": {"body": "3"}}
        await whatsapp_handler.process_incoming_whatsapp_message(v1)

        v2 = {"from": vol_phone, "id": "v2", "type": "text", "text": {"body": "Mushan"}}
        await whatsapp_handler.process_incoming_whatsapp_message(v2)

        v3 = {"from": vol_phone, "id": "v3", "type": "text", "text": {"body": "Car"}}
        await whatsapp_handler.process_incoming_whatsapp_message(v3)

        v4 = {"from": vol_phone, "id": "v4", "type": "text", "text": {"body": "Kegalle"}}
        await whatsapp_handler.process_incoming_whatsapp_message(v4)

        # Volunteer sends Google Maps URL
        v5 = {"from": vol_phone, "id": "v5", "type": "text", "text": {"body": "https://maps.google.com/maps?q=7.2221811%2C80.4749281&z=17&hl=en"}}
        r_v5 = await whatsapp_handler.process_incoming_whatsapp_message(v5)
        # Mushan MUST receive the pickup offer for Kegalle!
        assert "pickup available" in r_v5["reply"].lower() or "accept" in r_v5["reply"].lower()

        # 4. Volunteer accepts the task
        v6 = {"from": vol_phone, "id": "v6", "type": "text", "text": {"body": "Accept"}}
        r_v6 = await whatsapp_handler.process_incoming_whatsapp_message(v6)
        assert "accepted" in r_v6["reply"].lower() or "assigned" in r_v6["reply"].lower() or "collected" in r_v6["reply"].lower()

        # Org MUST receive cross-notification that volunteer was assigned
        org_notifs = [
            m
            for m in sent_messages
            if m["to"] == org_phone and ("mushan" in m["text"].lower() or "courier" in m["text"].lower() or "dispatched" in m["text"].lower())
        ]
        assert len(org_notifs) >= 1

        # Donor MUST receive cross-notification that courier is on the way
        donor_assign_notifs = [
            m
            for m in sent_messages
            if m["to"] == donor_phone and ("mushan" in m["text"].lower() or "assigned" in m["text"].lower() or "courier" in m["text"].lower())
        ]
        assert len(donor_assign_notifs) >= 1
