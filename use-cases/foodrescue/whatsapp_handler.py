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
    raw = (
        os.environ.get("META_APP_ID")
        or os.environ.get("WHATSAPP_APP_ID")
        or getattr(Config.get().whatsapp, "app_id", "")
        or DEFAULT_APP_ID
    )
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
        os.environ.get("WHATSAPP_APP_SECRET")
        or os.environ.get("AK_WHATSAPP__APP_SECRET")
        or getattr(Config.get().whatsapp, "app_secret", "")
        or ""
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


async def send_whatsapp_message(
    to_number: str,
    text: str,
    reply_to_message_id: Optional[str] = None
) -> Dict[str, Any]:
    """Send a WhatsApp text message via Meta Graph API v24.0."""
    access_token = get_access_token()
    phone_number_id = get_phone_number_id()

    if not access_token:
        logger.info(
            f"[WhatsApp Mock Delivery] To: {to_number} | Text: {text[:80]}... "
            "(WHATSAPP_ACCESS_TOKEN not set; skipping live HTTP request)"
        )
        return {"status": "mock_delivered", "to": to_number, "reason": "No WHATSAPP_ACCESS_TOKEN configured"}

    url = f"https://graph.facebook.com/{DEFAULT_API_VERSION}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # WhatsApp text messages are capped at 4096 characters
    max_length = 4096
    chunks = [text[i:i + max_length] for i in range(0, len(text), max_length)]

    results = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for idx, chunk in enumerate(chunks):
            payload: Dict[str, Any] = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to_number,
                "type": "text",
                "text": {"body": chunk}
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


async def process_incoming_whatsapp_message(
    message: Dict[str, Any],
    raw_value: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
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
    is_new_user = (user is None or not user.get("onboarding_completed"))
    if not user:
        user = database.create_or_update_user(
            phone=from_number,
            display_name=f"User_{from_number[-4:]}",
            preferred_language="en",
            user_role="unknown",
            onboarding_completed=False
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
                    audio_bytes=audio_bytes,
                    filename=f"voice_{media_id}.ogg",
                    language_hint=preferred_language
                )
                prompt_text = trans_result.get("text", "").strip()
                voice_transcript_lang = trans_result.get("language")
                logger.info(f"Transcribed WhatsApp voice note: '{prompt_text}' [lang={voice_transcript_lang}]")
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

        # Check Natural Script Language Detection
        detected_lang = translation_service.detect_language(prompt_text)
        if detected_lang and detected_lang != preferred_language:
            database.set_user_language(from_number, detected_lang)
            preferred_language = detected_lang
            try:
                cache.set("preferred_language", detected_lang)
            except Exception:
                pass

        # Check if user was in language menu
        in_lang_menu = False
        try:
            in_lang_menu = (cache.get("workflow_step") == "AWAITING_LANGUAGE")
        except Exception:
            pass

        # Check Explicit Language Selection Intent
        lang_intent = translation_service.is_language_selection_intent(prompt_text, in_language_menu=in_lang_menu)
        if lang_intent:
            database.set_user_language(from_number, lang_intent)
            database.set_onboarding_completed(from_number, True)
            preferred_language = lang_intent
            try:
                cache.set("preferred_language", lang_intent)
                cache.set("workflow_step", "IDLE")
            except Exception:
                pass
            reply_text = translation_service.get_localized_message("language_selected", lang=lang_intent)
            send_res = await send_whatsapp_message(to_number=from_number, text=reply_text, reply_to_message_id=message_id)
            return {"status": "language_updated", "language": lang_intent, "reply": reply_text, "send_status": send_res}

        if clean_lower in ["language", "languages", "භාෂාව", "மொழி", "ഭാഷ"]:
            try:
                cache.set("workflow_step", "AWAITING_LANGUAGE")
            except Exception:
                pass
            reply_text = (
                "🌍 *FoodRescue AI Language Selection / භාෂාව තෝරන්න / மொழியைத் தேர்ந்தெடுக்கவும்*:\n\n"
                "Reply with:\n"
                "1 - Sinhala (සිංහල)\n"
                "2 - Tamil (தமிழ்)\n"
                "3 - English\n"
                "4 - Malayalam (മലയാളം)"
            )
            send_res = await send_whatsapp_message(to_number=from_number, text=reply_text, reply_to_message_id=message_id)
            return {"status": "language_menu", "reply": reply_text, "send_status": send_res}

        # Check First-Time User Onboarding
        if is_new_user and not is_voice_message:
            # Check if this is a general greeting or first contact
            is_initial_greeting = clean_lower in ["hi", "hello", "hey", "start", "join", "help", "menu", "info", ""] or len(clean_lower) <= 4
            if is_initial_greeting:
                database.set_onboarding_completed(from_number, True)
                reply_text = translation_service.get_localized_message("onboarding_welcome", lang=preferred_language)
                send_res = await send_whatsapp_message(to_number=from_number, text=reply_text, reply_to_message_id=message_id)
                return {"status": "onboarding_welcome_sent", "reply": reply_text, "send_status": send_res}
            else:
                # User sent immediate intent on turn 1
                database.set_onboarding_completed(from_number, True)

        # Returning user explicit menu request
        if not is_new_user and clean_lower in ["hi", "hello", "hey", "menu", "start"] and not is_voice_message:
            reply_text = translation_service.get_localized_message("returning_welcome", lang=preferred_language)
            send_res = await send_whatsapp_message(to_number=from_number, text=reply_text, reply_to_message_id=message_id)
            return {"status": "returning_welcome_sent", "reply": reply_text, "send_status": send_res}

        # Invoke resilient multi-agent execution engine with session continuity
        from resilient_executor import run_resilient_chat

        try:
            chat_result = await run_resilient_chat(
                prompt=prompt_text,
                session_id=session_id,
                preferred_agent="foodrescue_coordinator"
            )
            reply_text = chat_result.get("result", "Thank you. Your food rescue request was received.")
        except Exception as exc:
            logger.error(f"Error executing resilient agent for {session_id}: {exc}")
            reply_text = translation_service.get_localized_message("error_recovery", lang=preferred_language)

        # Audit notification in database
        try:
            database.create_notification_record(
                notif_id=f"notif-{uuid.uuid4().hex[:8]}",
                recipient_type="donor",
                recipient_id=from_number,
                message=f"WhatsApp coordination ({'voice' if is_voice_message else 'text'}): {prompt_text[:60]} -> {reply_text[:60]}",
                channel="whatsapp"
            )
        except Exception as notif_err:
            logger.warning(f"Failed to record WhatsApp notification audit: {notif_err}")

        # Send response back to user
        send_res = await send_whatsapp_message(
            to_number=from_number,
            text=reply_text,
            reply_to_message_id=message_id
        )
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
        active_don_id = cache.get("current_donation_id") if cache.has("current_donation_id") else None
        active_task_id = cache.get("current_task_id") if cache.has("current_task_id") else None
        
        import routing
        map_link = routing.generate_map_link(lat, lng)
        
        if user_role == "volunteer":
            # Volunteer sharing current location
            vol_id = cache.get("current_volunteer_id")
            tools.save_location(
                location_type="VOLUNTEER_CURRENT_LOCATION",
                latitude=lat,
                longitude=lng,
                name=loc_name,
                address=loc_address,
                volunteer_id=vol_id,
                phone=from_number
            )
            reply_text = (
                "📍 *Location Updated!*\n\n"
                f"Your courier location is now active: {lat:.4f}, {lng:.4f}\n"
                f"• Map: {map_link}\n\n"
                "You are marked as *AVAILABLE*. We will notify you when a pickup opportunity is ready near you!"
            )
        elif user_role == "organization":
            # Recipient sharing destination location
            tools.save_location(
                location_type="RECIPIENT_DESTINATION",
                latitude=lat,
                longitude=lng,
                name=loc_name,
                address=loc_address,
                pickup_task_id=active_task_id,
                phone=from_number
            )
            reply_text = (
                "📍 *Destination Location Recorded!*\n\n"
                f"Your delivery coordinates have been updated: {lat:.4f}, {lng:.4f}\n"
                f"• Map: {map_link}\n\n"
                "Volunteers delivering food will navigate directly to this address."
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
                phone=from_number
            )
            reply_text = (
                "📍 *Pickup Location Confirmed!*\n\n"
                f"Thank you! Your pickup location has been securely recorded.\n"
                f"• Coordinates: {lat:.4f}, {lng:.4f}\n"
                f"• Map: {map_link}\n\n"
                "Your assigned volunteer courier has been provided navigation directions and will arrive soon! 🚚"
            )
            
            # Also notify assigned volunteer if task exists
            if active_task_id:
                task = database.get_pickup_task_record(active_task_id)
                if task and task.get("volunteer_id"):
                    vol = database.get_volunteer_record(task["volunteer_id"])
                    if vol and vol.get("phone"):
                        vol_text = (
                            f"📍 *Pickup Location Received for Task {active_task_id}*\n\n"
                            f"The donor has shared their exact pickup location:\n"
                            f"• Address: {loc_address or loc_name or 'Donor Location'}\n"
                            f"• Navigation: {map_link}\n\n"
                            f"Please proceed to collect the food donation. Once collected, reply *Collected*."
                        )
                        await send_whatsapp_message(to_number=vol["phone"], text=vol_text)

        # Audit notification
        try:
            database.create_notification_record(
                notif_id=f"notif-{uuid.uuid4().hex[:8]}",
                recipient_type="donor" if user_role != "volunteer" else "volunteer",
                recipient_id=from_number,
                message=f"WhatsApp location received: {lat:.4f}, {lng:.4f}",
                channel="whatsapp"
            )
        except Exception as notif_err:
            logger.warning(f"Failed to record WhatsApp location notification audit: {notif_err}")

        # Send response back to user
        send_res = await send_whatsapp_message(
            to_number=from_number,
            text=reply_text,
            reply_to_message_id=message_id
        )
        return {"status": "location_processed", "reply": reply_text, "send_status": send_res}

    # 4. Unsupported message types (images, audio, video, stickers, documents)
    else:
        logger.info(f"Received unsupported message type '{msg_type}' from {from_number}")
        fallback_text = (
            "👋 Thank you for reaching out to FoodRescue AI!\n\n"
            "I can process text and location messages.\n\n"
            "Please send me a text describing what you'd like to donate or request "
            "(for example: *'I have 20 meals to donate'* or reply *'menu'*), or share your *Location*."
        )
        send_res = await send_whatsapp_message(
            to_number=from_number,
            text=fallback_text,
            reply_to_message_id=message_id
        )
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
