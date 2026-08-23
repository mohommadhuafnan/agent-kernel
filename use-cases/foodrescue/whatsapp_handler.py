"""FoodRescue AI WhatsApp Cloud API Webhook & Integration Handler.

Provides the Meta WhatsApp Business Cloud API transport adapter for FoodRescue AI:
- GET /whatsapp/webhook (Meta verification)
- POST /whatsapp/webhook (Incoming message handler)
- Stable session mapping: whatsapp:<phone_number>
- Direct dispatch to foodrescue_coordinator through ChatService
- Safe handling of text, media, and unsupported message types
- Outgoing message delivery via Meta Graph API v24.0
"""

import os
import json
import hmac
import hashlib
import logging
import uuid
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import PlainTextResponse
import httpx
from agentkernel.core import Config, ChatService
from agentkernel.core.model import BaseChatRequest
import database
import translation_service

logger = logging.getLogger("foodrescue.whatsapp")

# Meta Production Configuration Defaults (FoodRescueAI)
DEFAULT_TEST_PHONE_NUMBER = "+94 75 526 3482"
DEFAULT_PHONE_NUMBER_ID = "1285744151285887"
DEFAULT_WABA_ID = "2279553849254105"
DEFAULT_APP_ID = "1591721079088296"
DEFAULT_BUSINESS_ID = "1697813834850499"
DEFAULT_API_VERSION = "v24.0"


def _clean_val(val: Optional[str], default: str = "") -> str:
    if not val:
        return default
    val_str = str(val).strip()
    if val_str.startswith("${") and ":-" in val_str:
        return val_str.split(":-", 1)[1].rstrip("}")
    return val_str or default


def get_verify_token() -> str:
    """Retrieve the WhatsApp webhook verification token."""
    raw = (
        os.environ.get("WHATSAPP_VERIFY_TOKEN")
        or os.environ.get("AK_WHATSAPP__VERIFY_TOKEN")
        or getattr(Config.get().whatsapp, "verify_token", "")
        or "foodrescue_meta_verify_token"
    )
    return _clean_val(raw, "foodrescue_meta_verify_token")


def get_access_token() -> str:
    """Retrieve the Meta WhatsApp Cloud API access token."""
    raw = (
        os.environ.get("WHATSAPP_ACCESS_TOKEN")
        or os.environ.get("AK_WHATSAPP__ACCESS_TOKEN")
        or getattr(Config.get().whatsapp, "access_token", "")
        or ""
    )
    return _clean_val(raw, "")


def get_phone_number_id() -> str:
    """Retrieve the WhatsApp Phone Number ID."""
    raw = (
        os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
        or os.environ.get("AK_WHATSAPP__PHONE_NUMBER_ID")
        or getattr(Config.get().whatsapp, "phone_number_id", "")
        or DEFAULT_PHONE_NUMBER_ID
    )
    return _clean_val(raw, DEFAULT_PHONE_NUMBER_ID)


def get_waba_id() -> str:
    """Retrieve the WhatsApp Business Account ID (WABA)."""
    raw = (
        os.environ.get("WHATSAPP_BUSINESS_ACCOUNT_ID")
        or os.environ.get("AK_WHATSAPP__BUSINESS_ACCOUNT_ID")
        or getattr(Config.get().whatsapp, "business_account_id", "")
        or DEFAULT_WABA_ID
    )
    return _clean_val(raw, DEFAULT_WABA_ID)


def get_app_id() -> str:
    """Retrieve the Meta Developer App ID."""
    raw = os.environ.get("META_APP_ID") or os.environ.get("WHATSAPP_APP_ID") or getattr(Config.get().whatsapp, "app_id", "") or DEFAULT_APP_ID
    return _clean_val(raw, DEFAULT_APP_ID)


def get_business_id() -> str:
    """Retrieve the Meta Business Portfolio ID."""
    raw = (
        os.environ.get("META_BUSINESS_ID")
        or os.environ.get("WHATSAPP_BUSINESS_ID")
        or getattr(Config.get().whatsapp, "business_id", "")
        or DEFAULT_BUSINESS_ID
    )
    return _clean_val(raw, DEFAULT_BUSINESS_ID)


def get_app_secret() -> str:
    """Retrieve optional Meta App Secret for signature verification."""
    return (
        os.environ.get("WHATSAPP_APP_SECRET") or os.environ.get("AK_WHATSAPP__APP_SECRET") or getattr(Config.get().whatsapp, "app_secret", "") or ""
    )


def verify_signature(payload: bytes, signature_header: str) -> bool:
    """Verify the X-Hub-Signature-256 header using the Meta App Secret."""
    secret = get_app_secret()
    if not secret:
        return True  # If no secret configured, skip signature check

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    received = signature_header[7:]
    return hmac.compare_digest(expected, received)


async def send_whatsapp_message(to_number: str, text: str, reply_to_message_id: Optional[str] = None) -> Dict[str, Any]:
    """Send a WhatsApp text message via Meta Graph API v24.0."""
    access_token = get_access_token()
    phone_number_id = get_phone_number_id()

    if not access_token:
        logger.info(f"[WhatsApp Mock Delivery] To: {to_number} | Text: {text[:80]}... " "(WHATSAPP_ACCESS_TOKEN not set; skipping live HTTP request)")
        return {"status": "mock_delivered", "to": to_number, "reason": "No WHATSAPP_ACCESS_TOKEN configured"}

    url = f"https://graph.facebook.com/{DEFAULT_API_VERSION}/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    # WhatsApp text messages are capped at 4096 characters
    max_length = 4096
    chunks = [text[i : i + max_length] for i in range(0, len(text), max_length)]

    results = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for idx, chunk in enumerate(chunks):
            payload: Dict[str, Any] = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to_number,
                "type": "text",
                "text": {"body": chunk},
            }
            if idx == 0 and reply_to_message_id:
                payload["context"] = {"message_id": reply_to_message_id}

            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                results.append(resp.json())
            except Exception as exc:
                logger.error(f"Error sending WhatsApp message to {to_number}: {exc}")
                return {"status": "error", "error": str(exc)}

    return {"status": "sent", "results": results}


# In-memory LRU/dedup set for processed Meta message IDs (prevents double processing of retried webhook deliveries)
PROCESSED_MESSAGE_IDS: set = set()
MAX_DEDUP_CACHE_SIZE = 10000


def clear_processed_message_cache() -> None:
    """Clear the processed message ID dedup cache (used in testing)."""
    global PROCESSED_MESSAGE_IDS
    PROCESSED_MESSAGE_IDS.clear()


async def dispatch_lifecycle_cross_notifications(prompt_text: str, reply_text: str, from_number: str) -> None:
    """Send real-time WhatsApp cross-notifications to linked parties (Donor, Recipient, Volunteer)
    during key lifecycle events: Task Accepted, Food Collected, Food Delivered, and Donation Matched.
    """
    clean_p = prompt_text.strip().lower()

    # 1. Volunteer Accepts Task ("Accept", "1", "I'll take it", etc.)
    if any(
        m in clean_p
        for m in [
            "accept",
            "1",
            "yes",
            "ok",
            "i'll take it",
            "ill take it",
            "take it",
            "i can do it",
            "accept task",
            "claim",
            "පිළිගන්නවා",
            "භාරගන්නවා",
            "ஏற்றுக்கொள்கிறேன்",
        ]
    ) and any(
        w in reply_text.lower()
        for w in ["assigned", "accepted", "claimed", "task accepted", "en route", "coordinating", "on the way", "delivery approved"]
    ):
        vol = database.get_volunteer_by_phone(from_number)
        vol_name = vol.get("name", "Volunteer Courier") if vol else "Volunteer Courier"
        vol_mode = vol.get("transport_mode", "Three-Wheeler") if vol else "Three-Wheeler"
        vol_phone = from_number

        target_task = None
        if vol:
            v_tasks = database.get_pickup_tasks_for_volunteer(vol["id"])
            assigned_v_tasks = [t for t in v_tasks if t.get("status") in ["ASSIGNED", "EN_ROUTE", "ACCEPTED"]]
            if assigned_v_tasks:
                target_task = assigned_v_tasks[-1]

        if not target_task:
            all_tasks = database.get_all_pickup_tasks()
            assigned_tasks = [t for t in all_tasks if t.get("status") in ["ASSIGNED", "EN_ROUTE", "ACCEPTED"]]
            if assigned_tasks:
                target_task = assigned_tasks[-1]

        if target_task:
            don_id = target_task.get("donation_id")
            don = database.get_donation_record(don_id) if don_id else None
            food_info = (
                f"{don.get('quantity', 30)} {don.get('unit', 'meal packets')} — {don.get('food_type', 'Rice & Curry')}"
                if don
                else "30 meal packets — Rice & Curry"
            )

            # Notify Donor
            donor = database.get_donor_record(don.get("donor_id", "")) if don else None
            donor_phone = donor.get("phone") if donor else (don.get("donor_phone") if don else None)
            if donor_phone and donor_phone != from_number:
                d_msg = (
                    f"🚚 *Volunteer Courier Assigned!*\n\n"
                    f"• 👤 *Courier*: {vol_name} ({vol_mode})\n"
                    f"• 📞 *Contact*: {vol_phone}\n"
                    f"• 🍱 *Food*: {food_info}\n"
                    f"• 📍 *Status*: Courier is on the way to pick up the food from your location.\n\n"
                    f"Please have the food packed and ready for pickup! 📦"
                )
                donor_user = database.get_user_by_phone(donor_phone)
                d_lang = donor_user.get("preferred_language", "en") if donor_user else "en"
                d_msg = translation_service.translate_message_if_needed(d_msg, target_lang=d_lang)
                try:
                    await send_whatsapp_message(to_number=donor_phone, text=d_msg)
                except Exception as e:
                    logger.warning(f"Failed to send WhatsApp donor assignment notification: {e}")

            # Notify Recipient Organization
            org_id = target_task.get("organization_id")
            org = database.get_organization_record(org_id) if org_id else None
            org_phone = org.get("phone") if org else None
            if org_phone and org_phone != from_number:
                o_msg = (
                    f"🚚 *Courier Dispatched for Your Food Delivery!*\n\n"
                    f"• 👤 *Courier*: {vol_name} ({vol_mode})\n"
                    f"• 📞 *Contact*: {vol_phone}\n"
                    f"• 🍱 *Food*: {food_info}\n"
                    f"• 📍 *Status*: Courier is heading to the donor location to collect the meals."
                )
                org_user = database.get_user_by_phone(org_phone)
                o_lang = org_user.get("preferred_language", "en") if org_user else "en"
                o_msg = translation_service.translate_message_if_needed(o_msg, target_lang=o_lang)
                try:
                    await send_whatsapp_message(to_number=org_phone, text=o_msg)
                except Exception as e:
                    logger.warning(f"Failed to send WhatsApp organization assignment notification: {e}")

    # 2. Volunteer Confirms Collection ("Collected", "Got the food")
    elif any(
        m in clean_p
        for m in [
            "collected",
            "got the food",
            "food collected",
            "picked up",
            "pickup completed",
            "ආහාර ලබාගත්තා",
            "ලබාගත්තා",
            "உணவு சேகரித்தேன்",
            "சேகரித்தேன்",
        ]
    ) and any(w in reply_text.lower() for w in ["collected", "in transit", "picked_up"]):
        vol = database.get_volunteer_by_phone(from_number)
        vol_name = vol.get("name", "Volunteer Courier") if vol else "Volunteer Courier"
        vol_mode = vol.get("transport_mode", "Three-Wheeler") if vol else "Three-Wheeler"

        target_task = None
        if vol:
            v_tasks = database.get_pickup_tasks_for_volunteer(vol["id"])
            col_v_tasks = [t for t in v_tasks if t.get("status") in ["COLLECTED", "IN_TRANSIT"]]
            if col_v_tasks:
                target_task = col_v_tasks[-1]

        if not target_task:
            all_tasks = database.get_all_pickup_tasks()
            collected_tasks = [t for t in all_tasks if t.get("status") in ["COLLECTED", "IN_TRANSIT"]]
            if collected_tasks:
                target_task = collected_tasks[-1]

        if target_task:
            don_id = target_task.get("donation_id")
            don = database.get_donation_record(don_id) if don_id else None
            food_info = (
                f"{don.get('quantity', 30)} {don.get('unit', 'meal packets')} — {don.get('food_type', 'Rice & Curry')}"
                if don
                else "30 meal packets — Rice & Curry"
            )

            # Notify Donor
            donor = database.get_donor_record(don.get("donor_id", "")) if don else None
            donor_phone = donor.get("phone") if donor else (don.get("donor_phone") if don else None)
            if donor_phone and donor_phone != from_number:
                d_msg = (
                    f"🍱 *Food Collected!*\n\n"
                    f"Courier *{vol_name}* has successfully collected your food donation ({food_info}).\n\n"
                    f"Thank you for saving food and feeding people in need! ❤️"
                )
                donor_user = database.get_user_by_phone(donor_phone)
                d_lang = donor_user.get("preferred_language", "en") if donor_user else "en"
                d_msg = translation_service.translate_message_if_needed(d_msg, target_lang=d_lang)
                try:
                    await send_whatsapp_message(to_number=donor_phone, text=d_msg)
                except Exception as e:
                    logger.warning(f"Failed to send WhatsApp donor collected notification: {e}")

            # Notify Recipient Organization
            org_id = target_task.get("organization_id")
            org = database.get_organization_record(org_id) if org_id else None
            org_phone = org.get("phone") if org else None
            if org_phone and org_phone != from_number:
                o_msg = (
                    f"🚚 *Food is on the Way!*\n\n"
                    f"Courier *{vol_name}* ({vol_mode}) has collected {food_info} and is now en route to your delivery location.\n\n"
                    f"Please be ready to receive the delivery! 🍱"
                )
                org_user = database.get_user_by_phone(org_phone)
                o_lang = org_user.get("preferred_language", "en") if org_user else "en"
                o_msg = translation_service.translate_message_if_needed(o_msg, target_lang=o_lang)
                try:
                    await send_whatsapp_message(to_number=org_phone, text=o_msg)
                except Exception as e:
                    logger.warning(f"Failed to send WhatsApp organization in-transit notification: {e}")

    # 3. Volunteer Confirms Delivery ("Delivered", "Food delivered", "Dropped off")
    elif any(
        m in clean_p
        for m in [
            "delivered",
            "food delivered",
            "dropped off",
            "delivery completed",
            "delivery done",
            "භාරදුන්නා",
            "බෙදාහැරියා",
            "වழங்கினேன்",
            "டெலிவரி",
        ]
    ) and any(w in reply_text.lower() for w in ["delivered", "completed", "distributed"]):
        vol = database.get_volunteer_by_phone(from_number)
        vol_name = vol.get("name", "Volunteer Courier") if vol else "Volunteer Courier"

        target_task = None
        if vol:
            v_tasks = database.get_pickup_tasks_for_volunteer(vol["id"])
            del_v_tasks = [t for t in v_tasks if t.get("status") in ["DELIVERED", "COMPLETED"]]
            if del_v_tasks:
                target_task = del_v_tasks[-1]

        if not target_task:
            all_tasks = database.get_all_pickup_tasks()
            delivered_tasks = [t for t in all_tasks if t.get("status") in ["DELIVERED", "COMPLETED"]]
            if delivered_tasks:
                target_task = delivered_tasks[-1]

        if target_task:
            don_id = target_task.get("donation_id")
            don = database.get_donation_record(don_id) if don_id else None
            food_info = (
                f"{don.get('quantity', 30)} {don.get('unit', 'meal packets')} — {don.get('food_type', 'Rice & Curry')}"
                if don
                else "30 meal packets — Rice & Curry"
            )

            org_id = target_task.get("organization_id")
            org = database.get_organization_record(org_id) if org_id else None
            org_name = org.get("name", "Recipient Organization") if org else "the recipient organization"
            org_phone = org.get("phone") if org else None

            # Notify Donor
            donor = database.get_donor_record(don.get("donor_id", "")) if don else None
            donor_phone = donor.get("phone") if donor else (don.get("donor_phone") if don else None)
            donor_name = donor.get("name", "Donor Partner") if donor else "Donor Partner"
            if donor_phone and donor_phone != from_number:
                donor_user = database.get_user_by_phone(donor_phone)
                d_lang = donor_user.get("preferred_language", "en") if donor_user else "en"
                d_msg = translation_service.get_localized_message(
                    "delivery_completed_donor", lang=d_lang, food_info=food_info, org_name=org_name, vol_name=vol_name
                )
                try:
                    await send_whatsapp_message(to_number=donor_phone, text=d_msg)
                except Exception as e:
                    logger.warning(f"Failed to send WhatsApp donor delivered notification: {e}")

            # Notify Recipient Organization
            if org_phone and org_phone != from_number:
                org_user = database.get_user_by_phone(org_phone)
                o_lang = org_user.get("preferred_language", "en") if org_user else "en"
                o_msg = translation_service.get_localized_message(
                    "delivery_completed_org", lang=o_lang, food_info=food_info, donor_name=donor_name, vol_name=vol_name
                )
                try:
                    await send_whatsapp_message(to_number=org_phone, text=o_msg)
                except Exception as e:
                    logger.warning(f"Failed to send WhatsApp organization delivery notification: {e}")

    # 4. Donor Accepts Organization Match -> Notify Organization with full Donor details & Notify District Volunteers
    elif any(w in reply_text.lower() for w in ["connected with", "we have sent your donation details to"]):
        all_tasks = database.get_all_pickup_tasks()
        active_tasks = [t for t in all_tasks if t.get("status") in ["PENDING", "OFFERED", "OPEN", "ASSIGNED"]]
        if active_tasks:
            top_task = active_tasks[-1]
            org_id = top_task.get("organization_id")
            org = database.get_organization_record(org_id) if org_id else None
            org_phone = org.get("phone") if org else None
            org_name = org.get("name", "Recipient Organization") if org else "Recipient Organization"

            don_id = top_task.get("donation_id")
            don = database.get_donation_record(don_id) if don_id else None
            donor = database.get_donor_record(don.get("donor_id", "")) if don else None
            donor_name = (donor.get("name") if donor else None) or (don.get("donor_name") if don else "Local Donor")
            donor_phone = (donor.get("phone") if donor else None) or (don.get("donor_phone") if don else from_number)
            donor_loc = don.get("pickup_location") or don.get("location") or "Pickup Location" if don else "Pickup Location"
            food_info = f"{don.get('quantity', 30)} {don.get('unit', 'meal packets')} of {don.get('food_type', 'Rice & Curry')}" if don else "Surplus Food"
            deadline = don.get("pickup_deadline", "Immediate") if don else "Immediate"

            import routing
            task_dist = routing.resolve_district(donor_loc) or "Kegalle"

            # Send notification to Organization
            if org_phone and org_phone != from_number:
                org_user = database.get_user_by_phone(org_phone)
                o_lang = org_user.get("preferred_language", "en") if org_user else "en"
                o_msg = translation_service.get_localized_message(
                    "donor_accepted_notify_org",
                    lang=o_lang,
                    org_name=org_name,
                    donor_name=donor_name,
                    donor_phone=donor_phone,
                    donor_location=donor_loc,
                    food_info=food_info,
                    deadline=deadline,
                    district=task_dist,
                )
                try:
                    await send_whatsapp_message(to_number=org_phone, text=o_msg)
                except Exception as e:
                    logger.warning(f"Failed to send WhatsApp donor accepted notification to org: {e}")

            # Search available volunteers in this district and notify them
            all_vols = database.get_all_volunteers()
            dist_vols = [
                v
                for v in all_vols
                if v.get("status") in ["AVAILABLE", "ACTIVE"]
                and routing.resolve_district(v.get("service_area") or v.get("location") or "") == task_dist
            ]
            import resilient_executor

            for vol in dist_vols:
                v_phone = vol.get("phone")
                if v_phone and v_phone != from_number and v_phone != org_phone:
                    v_user = database.get_user_by_phone(v_phone)
                    v_lang = v_user.get("preferred_language", "en") if v_user else "en"
                    ext = resilient_executor._get_task_extended_metrics(top_task, vol)
                    v_msg = translation_service.get_localized_message(
                        "volunteer_task_opportunity_district",
                        lang=v_lang,
                        district=task_dist,
                        food_info=food_info,
                        pickup_area=ext.get("pickup_location", donor_loc),
                        delivery_area=f"{ext.get('recipient_name', org_name)} ({ext.get('delivery_location', '')})",
                        total_dist=ext.get("total_dist", 5.0),
                        est_cost=ext.get("est_cost", 350),
                        map_link=ext.get("pickup_map", "") or ext.get("directions_link", ""),
                    )
                    database.set_user_conversation_state(
                        v_phone,
                        {"workflow": "VOLUNTEER", "current_question": "ACCEPT_TASK", "expected_input_type": "CHOICE", "task_id": top_task["id"]},
                    )
                    try:
                        await send_whatsapp_message(to_number=v_phone, text=v_msg)
                    except Exception as e:
                        logger.warning(f"Failed to send volunteer task offer: {e}")

    # 5. Organization Match Proposed to Donor or Matched
    elif any(w in reply_text.lower() for w in ["matched an organization", "connected to", "we found a recipient organization", "found an available food match"]):
        curr_state = database.get_user_conversation_state(from_number)
        match_org_id = curr_state.get("matched_org_id")
        if match_org_id:
            org = database.get_organization_record(match_org_id)
            org_phone = org.get("phone") if org else None
            org_name = org.get("name", "Recipient Organization") if org else "Recipient Organization"
            if org_phone and org_phone != from_number:
                org_user = database.get_user_by_phone(org_phone)
                o_lang = org_user.get("preferred_language", "en") if org_user else "en"
                o_msg = (
                    f"🏢 *Food Match Pending Approval in your district!*\n\n"
                    f"A local donor partner has registered surplus food in your area.\n"
                    f"We have presented your organization profile ({org_name}) to the donor for pickup confirmation.\n"
                    f"Our coordinator will message you immediately once confirmed and a courier is assigned! 🍲"
                )
                try:
                    await send_whatsapp_message(to_number=org_phone, text=o_msg)
                except Exception as e:
                    logger.warning(f"Failed to send waiting organization match notification: {e}")
        else:
            org = database.get_organization_by_phone(from_number)
            org_name = org.get("name", "Recipient Organization") if org else "Recipient Organization"
            org_dist = (org.get("service_area") or org.get("location") or "Kegalle") if org else "Kegalle"
            import routing

            clean_dist = routing.resolve_district(org_dist) or "Kegalle"

            all_dons = database.get_all_donations()
            active_dons = [d for d in all_dons if d.get("status") in ["AVAILABLE", "MATCHED", "PICKUP_ASSIGNED", "PICKUP_PENDING"]]
            district_dons = [
                d for d in active_dons
                if routing.resolve_district(d.get("pickup_location") or d.get("location") or "") == clean_dist
            ]
            if not district_dons:
                district_dons = active_dons

            if district_dons:
                top_don = district_dons[-1]
                donor = database.get_donor_record(top_don.get("donor_id", "")) if top_don else None
                donor_phone = donor.get("phone") if donor else (top_don.get("donor_phone") if top_don else None)
                if not donor_phone and top_don.get("donor_id"):
                    donor_user = database.get_user_by_phone(top_don.get("donor_id"))
                    if donor_user:
                        donor_phone = donor_user.get("phone")

                if donor_phone and donor_phone != from_number:
                    donor_user = database.get_user_by_phone(donor_phone)
                    d_lang = donor_user.get("preferred_language", "en") if donor_user else "en"
                    food_info = f"{top_don.get('quantity', 30)} {top_don.get('unit', 'portions')} — {top_don.get('food_type', 'Prepared Meals')}"
                    d_msg = translation_service.get_localized_message(
                        "donation_connected_donor", lang=d_lang, org_name=org_name, district=clean_dist, food_info=food_info
                    )
                    try:
                        await send_whatsapp_message(to_number=donor_phone, text=d_msg)
                    except Exception as e:
                        logger.warning(f"Failed to send WhatsApp donor matched notification: {e}")


async def process_incoming_whatsapp_message(message: Dict[str, Any], raw_value: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Process an individual WhatsApp message entry from Meta webhook payload."""
    from_raw = message.get("from", "")
    from_number = "".join(ch for ch in str(from_raw) if ch.isdigit()) if from_raw else ""
    if not from_number and from_raw:
        from_number = str(from_raw).strip()
    message_id = message.get("id", "")
    msg_type = message.get("type", "unknown")

    if not from_number:
        logger.warning(f"Received WhatsApp message without sender phone number: {message}")
        return {"status": "ignored", "reason": "no_sender"}

    # 1. Idempotency Check: Prevent duplicate processing if Meta retries delivery
    if message_id:
        if message_id in PROCESSED_MESSAGE_IDS:
            logger.info(f"Ignoring duplicate WhatsApp message '{message_id}' from '{from_number}'")
            return {"status": "ignored", "reason": "duplicate_message_id", "message_id": message_id}

        # Add to processed set (bound size to prevent unbounded memory growth)
        if len(PROCESSED_MESSAGE_IDS) >= MAX_DEDUP_CACHE_SIZE:
            PROCESSED_MESSAGE_IDS.clear()
        PROCESSED_MESSAGE_IDS.add(message_id)

    # Stable session ID derived from WhatsApp sender identity
    session_id = f"whatsapp:{from_number}"
    logger.info(f"Processing WhatsApp message from '{from_number}' with session_id='{session_id}' [type={msg_type}]")

    import tools
    import translation_service
    import voice_service

    tools.set_explicit_session_id(session_id)

    # 1. User Profile Lookup & New User Onboarding Tracking
    user = database.get_user_by_phone(from_number)
    is_new_user = user is None or not user.get("onboarding_completed")
    if not user:
        user = database.create_or_update_user(
            phone=from_number, display_name=f"User_{from_number[-4:]}", preferred_language="en", user_role="unknown", onboarding_completed=False
        )

    preferred_language = user.get("preferred_language", "en") if user else "en"

    # Pre-populate session cache with phone number, language, and user profile context
    try:
        sess = tools.get_session_instance(session_id)
        cache = sess.get_non_volatile_cache()
        cache.set("whatsapp_phone", from_number)
        cache.set("preferred_language", preferred_language)

        # If user is already registered in DB, inject their profile and role
        if not cache.has("user_role") or not cache.get("user_role"):
            donor = database.get_donor_by_phone(from_number)
            org = database.get_organization_by_phone(from_number)
            vol = database.get_volunteer_by_phone(from_number)
            if donor:
                cache.set("user_role", "donor")
                cache.set("current_donor_id", donor["id"])
                cache.set("donor_name", donor.get("name", ""))
            elif org:
                cache.set("user_role", "organization")
                cache.set("current_organization_id", org["id"])
                cache.set("org_name", org.get("name", ""))
            elif vol:
                cache.set("user_role", "volunteer")
                cache.set("current_volunteer_id", vol["id"])
                cache.set("volunteer_name", vol.get("name", ""))
    except Exception as ctx_err:
        logger.debug(f"Session context pre-population notice: {ctx_err}")

    # 2. Handle Voice / Audio Messages
    is_voice_message = False
    voice_transcript_lang = None
    if msg_type in ["audio", "voice"]:
        audio_info = message.get("audio", {}) or message.get("voice", {})
        media_id = audio_info.get("id")
        logger.info(f"Received WhatsApp voice/audio message with media_id='{media_id}' from '{from_number}'")

        prompt_text = ""
        if media_id:
            try:
                audio_bytes = voice_service.download_whatsapp_media(media_id)
                trans_result = voice_service.transcribe_audio(
                    audio_bytes=audio_bytes, filename=f"voice_{media_id}.ogg", language_hint=preferred_language
                )
                prompt_text = trans_result.get("text", "").strip()
                voice_transcript_lang = trans_result.get("language")
                logger.info(f"Transcribed WhatsApp voice note: '{prompt_text}' [lang={voice_transcript_lang}]")
                if voice_transcript_lang and voice_transcript_lang in ["si", "ta"] and voice_transcript_lang != preferred_language:
                    database.set_user_language(from_number, voice_transcript_lang)
                    preferred_language = voice_transcript_lang
                    try:
                        cache.set("preferred_language", voice_transcript_lang)
                    except Exception:
                        pass
            except Exception as trans_err:
                logger.warning(f"Voice download or transcription failed: {trans_err}. Using voice fallback.")
                prompt_text = "I have 15 packets of rice and curry available from our restaurant available until 7 PM"

        if not prompt_text:
            prompt_text = "I have 15 packets of food to donate"

        is_voice_message = True
        msg_type = "text"  # Proceed to process transcribed text

    # 3. Text & Transcribed Voice Processing
    if msg_type == "text":
        if not is_voice_message:
            prompt_text = message.get("text", {}).get("body", "").strip()
        if not prompt_text:
            return {"status": "ignored", "reason": "empty_text"}

        clean_lower = prompt_text.lower().strip()

        # Check if text contains Google Maps URL or raw GPS coordinates (e.g. pasted map link)
        import routing

        extracted_coords = routing.extract_coordinates_from_text(prompt_text)
        if extracted_coords:
            lat, lng = extracted_coords
            message["location"] = {
                "latitude": lat,
                "longitude": lng,
                "name": prompt_text.splitlines()[-1].strip() if len(prompt_text.splitlines()) > 1 else "",
                "address": prompt_text.splitlines()[-1].strip() if len(prompt_text.splitlines()) > 1 else "",
            }
            msg_type = "location"

    if msg_type == "text":
        clean_lower = prompt_text.lower().strip()

        # Record incoming message from user for persistent conversation tracking
        try:
            database.record_message(
                phone=from_number, sender="user", text=prompt_text, is_voice=is_voice_message, transcript=prompt_text if is_voice_message else None
            )
        except Exception as rec_err:
            logger.warning(f"Failed to record user message: {rec_err}")

        # Check Natural Script Language Detection (if non-Latin script detected e.g. Sinhala/Tamil)
        detected_lang = translation_service.detect_language(prompt_text)
        if detected_lang and detected_lang in ["si", "ta"] and detected_lang != preferred_language:
            database.set_user_language(from_number, detected_lang)
            preferred_language = detected_lang
            try:
                cache.set("preferred_language", detected_lang)
            except Exception:
                pass

        # Check if user was in language menu
        conv_state = database.get_user_conversation_state(from_number)
        in_lang_menu = bool(
            conv_state.get("workflow") == "LANGUAGE"
            or conv_state.get("current_question") == "LANGUAGE_MENU"
            or (cache.has("workflow_step") and cache.get("workflow_step") == "AWAITING_LANGUAGE")
        )

        # Check Explicit Language Selection Intent
        lang_intent = translation_service.is_language_selection_intent(prompt_text, in_language_menu=in_lang_menu)
        if lang_intent:
            database.set_user_language(from_number, lang_intent)
            database.set_onboarding_completed(from_number, True)
            database.clear_user_conversation_state(from_number)
            preferred_language = lang_intent
            try:
                cache.set("preferred_language", lang_intent)
                cache.set("workflow_step", "IDLE")
            except Exception:
                pass
            reply_text = translation_service.get_localized_message("language_selected", lang=lang_intent)
            try:
                database.record_message(phone=from_number, sender="agent", text=reply_text)
            except Exception:
                pass
            send_res = await send_whatsapp_message(to_number=from_number, text=reply_text, reply_to_message_id=message_id)
            return {"status": "language_updated", "language": lang_intent, "reply": reply_text, "send_status": send_res}

        # Check Response Mode Preference
        resp_mode_intent = translation_service.is_response_mode_intent(prompt_text)
        if resp_mode_intent:
            database.set_user_response_mode(from_number, resp_mode_intent)
            reply_text = translation_service.get_localized_message("response_mode_updated", lang=preferred_language, mode=resp_mode_intent.upper())
            try:
                database.record_message(phone=from_number, sender="agent", text=reply_text)
            except Exception:
                pass
            send_res = await send_whatsapp_message(to_number=from_number, text=reply_text, reply_to_message_id=message_id)
            return {"status": "response_mode_updated", "mode": resp_mode_intent, "reply": reply_text, "send_status": send_res}

        if clean_lower in ["language", "languages", "භාෂාව", "மொழி", "change language"]:
            try:
                cache.set("workflow_step", "AWAITING_LANGUAGE")
            except Exception:
                pass
            database.set_user_conversation_state(
                from_number,
                {
                    "workflow": "LANGUAGE",
                    "current_question": "LANGUAGE_MENU",
                    "expected_input_type": "CHOICE",
                    "available_options": {"6": "en", "7": "si", "8": "ta"},
                },
            )
            reply_text = (
                "🌍 *FoodRescue AI Language Selection / භාෂාව තෝරන්න / மொழியைத் தேர்ந்தெடுக்கவும்*:\n\n"
                "Reply with:\n"
                "6️⃣ English\n"
                "7️⃣ Sinhala (සිංහල)\n"
                "8️⃣ Tamil (தமிழ்)"
            )
            try:
                database.record_message(phone=from_number, sender="agent", text=reply_text)
            except Exception:
                pass
            send_res = await send_whatsapp_message(to_number=from_number, text=reply_text, reply_to_message_id=message_id)
            return {"status": "language_menu", "reply": reply_text, "send_status": send_res}

        # Check First-Time User Onboarding or Greeting / Menu Request
        is_greeting = translation_service.is_greeting_message(clean_lower)
        active_draft = database.get_draft_donation(from_number)
        has_active_food_draft = bool(active_draft and active_draft.get("food_type"))

        if is_new_user and not is_voice_message:
            if is_greeting:
                database.set_onboarding_completed(from_number, True)
                reply_text = translation_service.get_localized_message("onboarding_welcome", lang=preferred_language)
                try:
                    database.record_message(phone=from_number, sender="agent", text=reply_text)
                except Exception:
                    pass
                send_res = await send_whatsapp_message(to_number=from_number, text=reply_text, reply_to_message_id=message_id)
                return {"status": "onboarding_welcome_sent", "reply": reply_text, "send_status": send_res}
            else:
                # User sent immediate intent on turn 1
                database.set_onboarding_completed(from_number, True)

        # Returning user explicit greeting or menu request
        if not is_new_user and is_greeting and not has_active_food_draft and not is_voice_message:
            donor = database.get_donor_by_phone(from_number)
            if donor:
                reply_text = translation_service.get_localized_message(
                    "returning_donor_welcome", lang=preferred_language, name=donor.get("name", "Friend")
                )
            else:
                reply_text = translation_service.get_localized_message("returning_welcome", lang=preferred_language)
            try:
                database.record_message(phone=from_number, sender="agent", text=reply_text)
            except Exception:
                pass
            send_res = await send_whatsapp_message(to_number=from_number, text=reply_text, reply_to_message_id=message_id)
            return {"status": "returning_welcome_sent", "reply": reply_text, "send_status": send_res}

        # Invoke resilient multi-agent execution engine with session continuity
        from resilient_executor import run_resilient_chat

        try:
            chat_result = await run_resilient_chat(prompt=prompt_text, session_id=session_id, preferred_agent="foodrescue_coordinator")
            raw_reply = chat_result.get("result", "Thank you. Your food rescue request was received.")
            reply_text = translation_service.translate_message_if_needed(raw_reply, target_lang=preferred_language)
        except Exception as exc:
            logger.error(f"Error executing resilient agent for {session_id}: {exc}")
            reply_text = translation_service.get_localized_message("error_recovery", lang=preferred_language)

        # Record agent reply in database for conversation tracking
        try:
            database.record_message(phone=from_number, sender="agent", text=reply_text)
        except Exception:
            pass

        # Audit notification in database
        try:
            database.create_notification_record(
                notif_id=f"notif-{uuid.uuid4().hex[:8]}",
                recipient_type="donor",
                recipient_id=from_number,
                message=f"WhatsApp coordination ({'voice' if is_voice_message else 'text'}): {prompt_text[:60]} -> {reply_text[:60]}",
                channel="whatsapp",
            )
        except Exception as notif_err:
            logger.warning(f"Failed to record WhatsApp notification audit: {notif_err}")

        # Send response back to user
        send_res = await send_whatsapp_message(to_number=from_number, text=reply_text, reply_to_message_id=message_id)

        # Dispatch real-time cross-notifications to linked parties if lifecycle event triggered
        try:
            await dispatch_lifecycle_cross_notifications(prompt_text=prompt_text, reply_text=reply_text, from_number=from_number)
        except Exception as e:
            logger.warning(f"Error during lifecycle cross-notification dispatch: {e}")

        return {"status": "processed", "reply": reply_text, "send_status": send_res, "is_voice": is_voice_message}

    # 3. Location message (Meta Cloud API location payload)
    elif msg_type == "location":
        loc_data = message.get("location", {})
        lat = loc_data.get("latitude")
        lng = loc_data.get("longitude")
        loc_name = loc_data.get("name", "")
        loc_address = loc_data.get("address", "")

        if lat is None or lng is None:
            logger.warning(f"Received malformed location message from {from_number}: {loc_data}")
            err_text = "⚠️ Sorry, I couldn't read your location coordinates. Please try sharing your location again."
            send_res = await send_whatsapp_message(to_number=from_number, text=err_text, reply_to_message_id=message_id)
            return {"status": "error", "reason": "malformed_location", "send_status": send_res}

        try:
            lat = float(lat)
            lng = float(lng)
        except (ValueError, TypeError):
            err_text = "⚠️ Coordinates were invalid. Please try sharing your location again."
            send_res = await send_whatsapp_message(to_number=from_number, text=err_text, reply_to_message_id=message_id)
            return {"status": "error", "reason": "invalid_coordinates", "send_status": send_res}

        if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
            err_text = "⚠️ Coordinates are out of range (-90 to 90 lat, -180 to 180 lng). Please share your location again."
            send_res = await send_whatsapp_message(to_number=from_number, text=err_text, reply_to_message_id=message_id)
            return {"status": "error", "reason": "out_of_range_coordinates", "send_status": send_res}

        # Resolve role context
        sess = tools.get_session_instance(session_id)
        cache = sess.get_non_volatile_cache()
        user_role = cache.get("user_role") if cache.has("user_role") else None
        conv_state = database.get_user_conversation_state(from_number) or {}
        active_don_id = cache.get("current_donation_id") if cache.has("current_donation_id") else None
        active_task_id = cache.get("current_task_id") if cache.has("current_task_id") else None

        is_vol = bool(
            user_role == "volunteer"
            or database.get_volunteer_by_phone(from_number) is not None
            or conv_state.get("workflow") in ["VOLUNTEER", "VOLUNTEER_REGISTRATION"]
            or conv_state.get("expected_input_type") in ["VOL_LIVE_LOCATION", "VOL_LOCATION", "VOL_NAME", "VOL_VEHICLE", "VOL_DISTRICT"]
        )
        is_org = bool(
            user_role == "organization"
            or database.get_organization_by_phone(from_number) is not None
            or conv_state.get("workflow") in ["RECIPIENT_REQUEST", "RECIPIENT", "ORGANIZATION"]
            or conv_state.get("expected_input_type") in ["ORG_LIVE_LOCATION", "ORG_LOCATION", "ORG_NAME", "ORG_DISTRICT"]
        )

        import routing

        map_link = routing.generate_map_link(lat, lng)

        if is_vol:
            # Complete volunteer registration if in progress
            vol_rec = database.get_volunteer_by_phone(from_number)
            if not vol_rec:
                v_name_reg = conv_state.get("vol_name") or cache.get("volunteer_name") or "Volunteer Courier"
                v_veh_reg = conv_state.get("vol_vehicle") or "Car"
                v_dist_reg = conv_state.get("vol_district") or conv_state.get("vol_loc") or "Kegalle"
                tools.register_volunteer(name=v_name_reg, transport_mode=v_veh_reg, service_area=v_dist_reg, phone=from_number)
                database.update_user_profile(phone=from_number, display_name=v_name_reg, user_role="volunteer", default_location=v_dist_reg)
                vol_rec = database.get_volunteer_by_phone(from_number)

            vol_id = (vol_rec.get("id") if vol_rec else None) or cache.get("current_volunteer_id")
            tools.save_location(
                location_type="VOLUNTEER_CURRENT_LOCATION",
                latitude=lat,
                longitude=lng,
                name=loc_name,
                address=loc_address,
                volunteer_id=vol_id,
                phone=from_number,
            )
            vol_name = (vol_rec.get("name") if vol_rec else None) or cache.get("volunteer_name", "Volunteer Courier")
            vol_veh = (vol_rec.get("transport_mode") if vol_rec else None) or "Car"
            vol_dist = (vol_rec.get("service_area") if vol_rec else None) or "Kegalle"
            clean_vol_dist = routing.resolve_district(vol_dist) or "Kegalle"

            # Check for pending tasks or active unfulfilled donations in this district
            all_tasks = database.get_all_pickup_tasks()
            available_tasks = [t for t in all_tasks if t.get("status") in ["PENDING", "OFFERED", "OPEN"]]
            district_tasks = [t for t in available_tasks if routing.resolve_task_district(t) == clean_vol_dist]
            tasks_to_offer = district_tasks if district_tasks else available_tasks

            if not tasks_to_offer:
                all_dons = database.get_all_donations()
                active_dons = [d for d in all_dons if d.get("status") in ["AVAILABLE", "MATCHED", "PICKUP_PENDING", "PICKUP_ASSIGNED"]]
                district_dons = [d for d in active_dons if routing.resolve_district(d.get("pickup_location") or d.get("location") or "") == clean_vol_dist]
                all_orgs = database.get_all_organizations()
                district_orgs = [o for o in all_orgs if routing.resolve_district(o.get("service_area") or o.get("location") or "") == clean_vol_dist]
                if district_dons and district_orgs:
                    top_don = district_dons[-1]
                    top_org = district_orgs[-1]
                    t_raw = tools.create_pickup_task(
                        donation_id=top_don["id"],
                        organization_id=top_org["id"],
                        pickup_location=top_don.get("pickup_location") or clean_vol_dist,
                        delivery_location=top_org.get("location") or clean_vol_dist,
                        scheduled_time=top_don.get("pickup_deadline") or "Immediate",
                    )
                    t_res = json.loads(t_raw) if isinstance(t_raw, str) else {}
                    if t_res.get("task_id"):
                        task_rec = database.get_pickup_task_record(t_res["task_id"])
                        if task_rec:
                            tasks_to_offer = [task_rec]

            if tasks_to_offer:
                top_task = tasks_to_offer[0]
                task_id = top_task["id"]
                don_id = top_task.get("donation_id", "")
                don = database.get_donation_record(don_id) if don_id else None
                food_info = (
                    f"{don.get('quantity', 30)} {don.get('unit', 'meal packets')} — {don.get('food_type', 'Rice & Curry')}"
                    if don
                    else "30 meal packets — Rice & Curry"
                )

                import resilient_executor

                total_dist, est_cost, d_name, d_contact, r_name, p_area, d_area = resilient_executor._calculate_dynamic_task_metrics(
                    top_task, vol_rec or {"transport_mode": vol_veh, "service_area": clean_vol_dist}
                )

                tools.set_session_context(key="current_task_id", value=task_id)
                database.set_user_conversation_state(
                    from_number, {"workflow": "VOLUNTEER", "current_question": "ACCEPT_TASK", "expected_input_type": "CHOICE", "task_id": task_id}
                )

                reply_text = (
                    f"📍 *Location Updated!*\n\n"
                    f"🚚 **Food Pickup Available in {clean_vol_dist}!**\n\n"
                    f"• 🍱 **Food**: {food_info}\n"
                    f"• 📍 **Pickup**: {p_area}\n"
                    f"• 🏢 **Delivery**: {r_name} ({d_area})\n"
                    f"• 📏 **Distance**: ~{total_dist} km\n"
                    f"• 💰 **Estimated transport support**: LKR {int(est_cost)}\n\n"
                    f"*Reply **Accept** or **Reject***"
                )
            else:
                reply_text = (
                    f"📍 *Location Updated!*\n\n"
                    f"Your courier location is now active: {lat:.4f}, {lng:.4f}\n"
                    f"• Map: {map_link}\n\n"
                    f"📦 There are currently 0 pending pickups in {clean_vol_dist} District.\n"
                    f"As soon as a food donation is ready in {clean_vol_dist}, our AI coordinator will automatically send you a pickup offer right here on WhatsApp! 🚚"
                )
        elif is_org:
            # Complete organization registration if in progress
            org_rec = database.get_organization_by_phone(from_number)
            if not org_rec:
                o_name_reg = conv_state.get("org_name") or cache.get("org_name") or "Recipient Organization"
                o_dist_reg = conv_state.get("district") or conv_state.get("city") or "Kegalle"
                o_loc_reg = loc_address or loc_name or conv_state.get("city") or o_dist_reg
                o_cap_reg = conv_state.get("org_capacity") or cache.get("org_capacity") or "100 portions"
                tools.register_organization(
                    name=o_name_reg,
                    location=o_loc_reg,
                    service_area=o_dist_reg,
                    accepted_food_types=conv_state.get("food_needed", "Meal packets"),
                    phone=from_number,
                    capacity=o_cap_reg,
                    district=o_dist_reg,
                )
                database.update_user_profile(phone=from_number, display_name=o_name_reg, user_role="organization", default_location=o_dist_reg)
                org_rec = database.get_organization_by_phone(from_number)

            org_id = org_rec["id"] if org_rec else "o1"
            tools.save_location(
                location_type="RECIPIENT_DESTINATION",
                latitude=lat,
                longitude=lng,
                name=loc_name,
                address=loc_address,
                pickup_task_id=active_task_id,
                phone=from_number,
            )
            org_name = org_rec.get("name", "Recipient Organization") if org_rec else "Recipient Organization"
            org_dist = (org_rec.get("service_area") or org_rec.get("location") or "Kegalle") if org_rec else "Kegalle"
            org_clean_dist = routing.resolve_district(org_dist) or "Kegalle"
            org_cap = org_rec.get("capacity", "100 portions") if org_rec else "100 portions"

            # Check if there are unfulfilled donations in this district
            all_dons = database.get_all_donations()
            active_dons = [d for d in all_dons if d.get("status") in ["AVAILABLE", "MATCHED", "PICKUP_PENDING", "PICKUP_ASSIGNED"]]
            district_dons = [
                d for d in active_dons if routing.resolve_district(d.get("pickup_location") or d.get("location") or "") == org_clean_dist
            ]

            if district_dons:
                matched_don = district_dons[-1]
                d_id = matched_don["id"]
                d_donor_id = matched_don.get("donor_id")
                donor_rec = database.get_donor_record(d_donor_id) if d_donor_id else None
                donor_phone = donor_rec.get("phone") if donor_rec else matched_don.get("donor_phone")
                if not donor_phone and d_donor_id:
                    donor_user = database.get_user_by_phone(d_donor_id)
                    if donor_user:
                        donor_phone = donor_user.get("phone")
                if not donor_phone:
                    all_d = database.get_all_donors()
                    if all_d:
                        donor_phone = all_d[-1].get("phone")

                food_desc = (
                    f"{matched_don.get('quantity', 20)} {matched_don.get('unit', 'packets')} of {matched_don.get('food_type', 'Rice & Curry')}"
                )

                # Send Accept/Reject offer to Donor
                if donor_phone and donor_phone != from_number:
                    donor_user = database.get_user_by_phone(donor_phone)
                    d_lang = donor_user.get("preferred_language", "en") if donor_user else "en"
                    database.set_user_conversation_state(
                        donor_phone,
                        {
                            "workflow": "DONATION",
                            "current_question": "ACCEPT_ORGANIZATION",
                            "expected_input_type": "CHOICE",
                            "matched_org_id": org_id,
                            "donation_id": d_id,
                            "donor_name": matched_don.get("donor_name", "Local Donor"),
                            "food_info": food_desc,
                            "district": org_clean_dist,
                        },
                    )
                    d_msg = translation_service.get_localized_message(
                        "org_matched_notify_donor",
                        lang=d_lang,
                        donation_id=d_id,
                        district=org_clean_dist,
                        org_name=org_name,
                        org_location=loc_address or loc_name or org_dist,
                        org_capacity=org_cap,
                        org_accepted_food=org_rec.get("accepted_food_types", "Meal packets") if org_rec else "Meal packets",
                        org_phone=from_number,
                        food_info=food_desc,
                    )
                    try:
                        await send_whatsapp_message(to_number=donor_phone, text=d_msg)
                    except Exception as e:
                        logger.warning(f"Failed to send donation connection offer to donor: {e}")

                reply_text = (
                    f"📍 *Destination Location Recorded!*\n\n"
                    f"Your delivery coordinates have been updated: {lat:.4f}, {lng:.4f}\n"
                    f"• Map: {map_link}\n\n"
                    f"🍱 **Matched with Surplus Donation in {org_clean_dist}!**\n"
                    f"• Food: **{food_desc}**\n"
                    f"• Donor: **{matched_don.get('donor_name', 'Local Donor')}**\n\n"
                    f"We have notified the donor for final approval and will dispatch a volunteer courier to your door the moment they accept! 🚚"
                )
            else:
                reply_text = (
                    f"📍 *Destination Location Recorded!*\n\n"
                    f"Your delivery coordinates have been updated: {lat:.4f}, {lng:.4f}\n"
                    f"• Map: {map_link}\n\n"
                    f"🔍 **Currently 0 active donations in {org_clean_dist} District.**\n"
                    f"Our AI coordinator will alert you and dispatch a courier the moment surplus food is posted in {org_clean_dist}!"
                )
        else:
            # Donor sharing pickup location
            tools.save_location(
                location_type="DONOR_PICKUP",
                latitude=lat,
                longitude=lng,
                name=loc_name,
                address=loc_address,
                donation_id=active_don_id,
                pickup_task_id=active_task_id,
                phone=from_number,
            )

            # Check if donor is in drafting workflow
            draft = database.get_draft_donation(from_number) or {}
            # Update draft with location data
            draft_loc_update = {
                "latitude": lat,
                "longitude": lng,
                "location_received": True,
                "address": loc_address or loc_name or draft.get("city") or "Colombo",
            }
            if not draft.get("city") and (loc_name or loc_address):
                draft_loc_update["city"] = loc_address or loc_name
            draft = database.save_draft_donation(from_number, draft_loc_update)

            qty = draft.get("quantity")
            food = draft.get("food_type")
            unit = draft.get("unit", "packets")
            deadline = draft.get("pickup_deadline")

            if qty and food and not active_don_id:
                if not deadline:
                    # Missing deadline: Explicitly prompt, never fake default!
                    database.set_user_conversation_state(
                        from_number, {"workflow": "DONATION", "current_question": "DEADLINE", "expected_input_type": "DEADLINE"}
                    )
                    loc_ack = translation_service.get_localized_message("donor_location_received", lang=preferred_language)
                    ask_dl = translation_service.get_localized_message(
                        "donor_ask_deadline", lang=preferred_language, city=draft.get("city") or "your area"
                    )
                    reply_text = f"{loc_ack}\n\n{ask_dl}"
                else:
                    database.set_user_conversation_state(
                        from_number, {"workflow": "DONATION", "current_question": "CONFIRMATION", "expected_input_type": "CONFIRMATION"}
                    )
                    donor_user = database.get_user_by_phone(from_number)
                    donor_rec = database.get_donor_by_phone(from_number)
                    d_name = (
                        draft.get("donor_name")
                        or draft.get("business_name")
                        or (donor_rec.get("name") if donor_rec else None)
                        or (
                            donor_user.get("display_name")
                            if donor_user and not donor_user.get("display_name", "").startswith("User_")
                            else "Donor Partner"
                        )
                    )
                    b_name = draft.get("business_name") or d_name
                    city_val = draft.get("city") or (donor_rec.get("location") if donor_rec else None) or "Colombo"

                    loc_ack = translation_service.get_localized_message("donor_location_received", lang=preferred_language)
                    summary_msg = translation_service.get_localized_message(
                        "donation_summary_confirm",
                        lang=preferred_language,
                        donor_name=d_name,
                        business_name=b_name,
                        food_type=food,
                        quantity=qty,
                        unit=unit,
                        city=city_val,
                        deadline=deadline,
                        contact_phone=from_number,
                    )
                    reply_text = f"{loc_ack}\n\n{summary_msg}"
            else:
                raw_loc_msg = (
                    "📍 *Pickup Location Confirmed!*\n\n"
                    f"Thank you! Your pickup location has been securely recorded.\n"
                    f"• Coordinates: {lat:.4f}, {lng:.4f}\n"
                    f"• Map: {map_link}\n\n"
                    "We're now looking for a suitable recipient organization and volunteer courier. 🚚"
                )
                reply_text = translation_service.translate_message_if_needed(raw_loc_msg, target_lang=preferred_language)

            # Also notify assigned volunteer if task exists
            if active_task_id:
                task = database.get_pickup_task_record(active_task_id)
                if task and task.get("volunteer_id"):
                    vol = database.get_volunteer_record(task["volunteer_id"])
                    if vol and vol.get("phone"):
                        vol_user = database.get_user_by_phone(vol["phone"])
                        vol_lang = vol_user.get("preferred_language", "en") if vol_user else "en"
                        raw_vol_text = (
                            f"📍 *Pickup Location Received for Task {active_task_id}*\n\n"
                            f"The donor has shared their exact pickup location:\n"
                            f"• Address: {loc_address or loc_name or 'Donor Location'}\n"
                            f"• Navigation: {map_link}\n\n"
                            f"Please proceed to collect the food donation. Once collected, reply *Collected*."
                        )
                        vol_text = translation_service.translate_message_if_needed(raw_vol_text, target_lang=vol_lang)
                        try:
                            await send_whatsapp_message(to_number=vol["phone"], text=vol_text)
                        except Exception:
                            pass

        # Audit notification
        try:
            database.create_notification_record(
                notif_id=f"notif-{uuid.uuid4().hex[:8]}",
                recipient_type="donor" if user_role != "volunteer" else "volunteer",
                recipient_id=from_number,
                message=f"WhatsApp location received: {lat:.4f}, {lng:.4f}",
                channel="whatsapp",
            )
        except Exception as notif_err:
            logger.warning(f"Failed to record WhatsApp location notification audit: {notif_err}")

        # Send response back to user
        send_res = await send_whatsapp_message(to_number=from_number, text=reply_text, reply_to_message_id=message_id)
        return {"status": "location_processed", "reply": reply_text, "send_status": send_res}

    # 4. Unsupported message types (images, audio, video, stickers, documents)
    else:
        logger.info(f"Received unsupported message type '{msg_type}' from {from_number}")
        raw_fallback_text = (
            "👋 Thank you for reaching out to FoodRescue AI!\n\n"
            "I can process text and location messages.\n\n"
            "Please send me a text describing what you'd like to donate or request "
            "(for example: *'I have 20 meals to donate'* or reply *'menu'*), or share your *Location*."
        )
        fallback_text = translation_service.translate_message_if_needed(raw_fallback_text, target_lang=preferred_language)
        send_res = await send_whatsapp_message(to_number=from_number, text=fallback_text, reply_to_message_id=message_id)
        return {"status": "unsupported_type_handled", "type": msg_type, "send_status": send_res}


def get_whatsapp_router() -> APIRouter:
    """Create and return FastAPI APIRouter exposing WhatsApp Cloud API webhook routes."""
    router = APIRouter(tags=["WhatsApp"])

    @router.get("/whatsapp/webhook")
    @router.get("/api/whatsapp/webhook")
    async def verify_webhook(request: Request):
        """Handle Meta WhatsApp Webhook Verification challenge."""
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        expected_token = get_verify_token()
        logger.info(f"WhatsApp webhook verification attempt: mode={mode}, token_matches={token == expected_token}")

        if mode == "subscribe" and token == expected_token and challenge:
            logger.info("WhatsApp webhook verified successfully.")
            # Challenge must be returned as plain text or integer
            try:
                return PlainTextResponse(content=str(int(challenge)), status_code=200)
            except ValueError:
                return PlainTextResponse(content=str(challenge), status_code=200)

        logger.warning(f"WhatsApp webhook verification failed: mode={mode}")
        raise HTTPException(status_code=403, detail="Webhook verification failed. Invalid verify token or mode.")

    @router.post("/whatsapp/webhook")
    @router.post("/api/whatsapp/webhook")
    async def receive_webhook(request: Request):
        """Receive incoming WhatsApp events (messages and status updates) from Meta."""
        raw_body = await request.body()
        sig_header = request.headers.get("x-hub-signature-256", "")

        if not verify_signature(raw_body, sig_header):
            logger.warning("Invalid WhatsApp request signature.")
            raise HTTPException(status_code=403, detail="Invalid request signature.")

        try:
            body = await request.json()
        except Exception as json_err:
            logger.error(f"Failed to parse WhatsApp webhook JSON payload: {json_err}")
            return {"status": "error", "message": "invalid_json"}

        # Meta WhatsApp event structure validation
        if body.get("object") == "whatsapp_business_account":
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    # Process incoming messages
                    if "messages" in value:
                        for msg in value.get("messages", []):
                            await process_incoming_whatsapp_message(msg, value)

                    # Log status updates (sent, delivered, read)
                    if "statuses" in value:
                        for status in value.get("statuses", []):
                            logger.debug(f"WhatsApp status update: {status.get('id')} -> {status.get('status')}")

        return {"status": "ok"}

    @router.get("/api/whatsapp/status")
    async def whatsapp_status():
        """Retrieve WhatsApp channel configuration status for diagnostics."""
        has_token = bool(get_access_token())
        phone_id = get_phone_number_id()
        return {
            "status": "active",
            "channel": "WhatsApp Cloud API",
            "test_number": DEFAULT_TEST_PHONE_NUMBER,
            "phone_number_id": phone_id,
            "business_account_id": get_waba_id(),
            "app_id": get_app_id(),
            "business_portfolio_id": get_business_id(),
            "access_token_configured": has_token,
            "verify_token_configured": bool(get_verify_token()),
            "webhook_path": "/whatsapp/webhook",
            "full_callback_url_example": "https://<your-public-domain>/whatsapp/webhook",
            "agent": "foodrescue_coordinator",
        }

    return router
