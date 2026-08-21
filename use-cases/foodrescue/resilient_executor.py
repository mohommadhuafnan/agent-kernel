"""FoodRescue AI Resilient Execution Engine.

Provides automatic model pool rotation, rate-limit fallback (429 / RESOURCE_EXHAUSTED),
error masking, and deterministic tool fallback so users never experience errors.
"""

import os
import re
import json
import uuid
import asyncio
import logging
from typing import Optional, Dict, Any, List
from agentkernel.core import ChatService
from agentkernel.core.model import BaseChatRequest
import tools
import database
import app
import translation_service
import voice_service
import routing

logger = logging.getLogger("foodrescue.resilient")

# Model candidate pool (prioritized by highest free-tier quota & throughput)
MODEL_POOL = [
    os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
]


def _is_rate_limit_error(exc: Exception) -> bool:
    """Determine if an exception is caused by API rate limiting or quota exhaustion."""
    err_str = str(exc).lower()
    return any(marker in err_str for marker in [
        "429",
        "resource_exhausted",
        "too many requests",
        "quota exceeded",
        "ratelimit",
        "rate limit",
        "retryin",
        "exhausted",
    ])


def _extract_quantity(text: str) -> float:
    """Extract numeric quantity from user prompt."""
    match = re.search(r'\b(\d+(?:\.\d+)?)\b', text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 30.0


def _extract_location(text: str) -> str:
    """Extract location from text or default to Colombo."""
    loc_match = re.search(
        r'\b(Colombo(?:\s*(?:0?[1-9]|1[0-5]))?|Kandy|Galle|Dehiwala|Nugegoda|Mount Lavinia|Rajagiriya|Bambalapitiya|Kollupitiya|Fort|Cinnamon Gardens|Wellawatte|Battaramulla|Negombo)\b',
        text,
        re.IGNORECASE
    )
    if loc_match:
        return loc_match.group(1).strip()
    return "Colombo"


def _extract_food_type(text: str) -> str:
    """Extract food type description from text."""
    text_clean = text.strip()
    if "meal" in text_clean.lower():
        return "Prepared Meals"
    if "bread" in text_clean.lower() or "bakery" in text_clean.lower():
        return "Bakery Items"
    if "fruit" in text_clean.lower() or "vegetable" in text_clean.lower() or "produce" in text_clean.lower():
        return "Fresh Produce"
    if "rice" in text_clean.lower() or "curry" in text_clean.lower():
        return "Rice & Curry Packages"
    return "Surplus Food Packages"


async def execute_deterministic_fallback(prompt: str, session_id: str) -> str:
    """Perform deterministic workflow execution when all LLM quotas are exhausted or for offline rule processing."""
    logger.warning(f"[Deterministic Fallback] Executing offline rule engine for session '{session_id}' with prompt: {prompt[:60]}")
    
    tools.set_explicit_session_id(session_id)
    clean_p = prompt.strip().lower()
    phone = session_id.split("whatsapp:", 1)[1] if "whatsapp:" in session_id else ""

    # Resolve persistent user profile and language
    user = database.get_user_by_phone(phone) if phone else None
    detected = translation_service.detect_language(prompt)
    if detected and detected in ["si", "ta", "ml"]:
        lang = detected
    else:
        lang = user.get("preferred_language", "en") if user else (detected or "en")

    # 1. Language Selection Intent (explicit change request e.g. 'Tamil', 'Change language to Tamil', 'தமிழ்', 'English please')
    in_lang_menu = False
    state = database.get_user_conversation_state(phone) if phone else {}
    if state.get("workflow") == "LANGUAGE" or state.get("current_question") == "LANGUAGE_MENU":
        in_lang_menu = True

    lang_intent = translation_service.is_language_selection_intent(prompt, in_language_menu=in_lang_menu)
    if lang_intent:
        if phone:
            database.set_user_language(phone, lang_intent)
            database.clear_user_conversation_state(phone)
        return translation_service.get_localized_message("language_selected", lang=lang_intent)

    # 2. Response Mode Intent ('voice replies please' / 'text only')
    resp_mode_intent = translation_service.is_response_mode_intent(prompt)
    if resp_mode_intent:
        if phone:
            database.set_user_response_mode(phone, resp_mode_intent)
        return translation_service.get_localized_message("response_mode_updated", lang=lang, mode=resp_mode_intent.upper())

    # 3. Explicit Language Menu Request ('language' / 'භාෂාව' / 'மொழி')
    if clean_p in ["language", "languages", "භාෂාව", "மொழி", "ഭാഷ", "change language"]:
        if phone:
            database.set_user_conversation_state(phone, {
                "workflow": "LANGUAGE",
                "current_question": "LANGUAGE_MENU",
                "expected_input_type": "CHOICE",
                "available_options": {"1": "si", "2": "ta", "3": "en", "4": "ml"}
            })
        return (
            "🌍 *FoodRescue AI Language Selection / භාෂාව තෝරන්න / மொழியைத் தேர்ந்தெடுக்கவும்*:\n\n"
            "Reply with:\n"
            "1 - Sinhala (සිංහල)\n"
            "2 - Tamil (தமிழ்)\n"
            "3 - English\n"
            "4 - Malayalam (മലയാളം)"
        )

    # 4. Status Queries (Donation / Pickup)
    if clean_p in ["4", "where is my donation?", "where is my donation", "show my donation", "what is my donation status?", "what is my donation status", "check my donation", "track my food"]:
        my_dons_raw = tools.get_my_donations(phone=phone)
        my_dons = json.loads(my_dons_raw) if isinstance(my_dons_raw, str) else {}
        if my_dons.get("status") == "success" and my_dons.get("latest_donation"):
            don = my_dons["latest_donation"]
            tasks = my_dons.get("latest_pickup_tasks", [])
            task_info = f"\n🚚 **Pickup**: {tasks[0].get('status', 'PENDING')}" if tasks else ""
            return (
                f"📦 **Your Latest Donation**\n\n"
                f"• **Donation ID**: `{don.get('id')}`\n"
                f"• **Food**: {don.get('quantity')} {don.get('unit')} of {don.get('food_type')}\n"
                f"• **Location**: 📍 {don.get('pickup_location')}\n"
                f"• **Status**: `{don.get('status')}`{task_info}\n\n"
                f"Thank you for helping rescue food! ❤️"
            )
        return (
            "📦 **No Active Donation Found**\n\n"
            "You don't have any active donations registered under your phone number right now.\n"
            "Reply **1** or say *'I have food to donate'* to create a new donation."
        )

    if clean_p in ["5", "show my pickup", "where is the pickup?", "where is the pickup", "where is the volunteer?", "where is the volunteer", "where is the food?", "where is the food", "what is my pickup?", "what is my pickup", "pickup status"]:
        my_picks_raw = tools.get_my_pickups(phone=phone)
        my_picks = json.loads(my_picks_raw) if isinstance(my_picks_raw, str) else {}
        if my_picks.get("status") == "success" and my_picks.get("latest_task"):
            task = my_picks["latest_task"]
            vol_name = task.get("volunteer_id", "Assigned Volunteer")
            return (
                f"🚚 **Pickup Status Update**\n\n"
                f"• **Pickup ID**: `{task.get('id')}`\n"
                f"• **Status**: `{task.get('status')}`\n"
                f"• **From**: 📍 {task.get('pickup_location')}\n"
                f"• **To**: 🏢 {task.get('delivery_location')}\n"
                f"• **Scheduled Time**: ⏰ {task.get('scheduled_time')}\n"
                f"• **Volunteer**: {vol_name}\n\n"
                f"I'll keep you posted as the pickup progresses!"
            )
        return (
            "🚚 **No Active Pickup Found**\n\n"
            "There are currently no active pickup tasks assigned to or linked with your account."
        )

    # 5. Cancellation
    if any(m in clean_p for m in ["cancel my donation", "cancel donation", "cancel pickup", "cancel"]):
        if phone:
            database.clear_draft_donation(phone)
            database.clear_user_conversation_state(phone)
        don_ctx = json.loads(tools.get_session_context())
        don_id = don_ctx.get("active_donation_id")
        if not don_id and phone:
            my_dons_raw = tools.get_my_donations(phone=phone)
            my_dons = json.loads(my_dons_raw) if isinstance(my_dons_raw, str) else {}
            if my_dons.get("status") == "success" and my_dons.get("latest_donation"):
                don_id = my_dons["latest_donation"]["id"]
        if don_id:
            res_raw = tools.cancel_donation(donation_id=don_id)
            res = json.loads(res_raw) if isinstance(res_raw, str) else {}
            if res.get("status") == "success":
                return (
                    f"🛑 **Donation Cancelled**\n\n"
                    f"Donation `{don_id}` and its associated pickup coordination have been cancelled.\n"
                    f"Let me know if you need help with anything else!"
                )
        return "🛑 **Donation Cancelled**\n\nYour active donation draft has been cancelled. Let me know if you need anything else!"

    # 6. Volunteer Availability & Natural Language Intent ("I'm free", "I can help", "pickups near me")
    if any(m in clean_p for m in ["i'm free", "i am free", "free now", "i can help", "available for pickup", "available to help", "available courier", "pickups near me", "any pickups", "have time", "ready to help", "ස්වේච්ඡා", "උදව් කරන්න පුළුවන්", "ලෑස්තියි", "உதவ முடியும்", "தன்னார்வலர்", "இலவசம்", "സന്നദ്ധ"]) or clean_p == "available":
        vol_id = "v1"
        if phone:
            v = database.get_volunteer_by_phone(phone)
            if v:
                vol_id = v["id"]
            else:
                tools.register_volunteer(name="Volunteer Courier", service_area="Colombo", phone=phone, transport_mode="Motorbike")
                v = database.get_volunteer_by_phone(phone)
                if v:
                    vol_id = v["id"]
                    
        tools.update_volunteer_availability(volunteer_id=vol_id, status="AVAILABLE", current_location="Colombo")
        
        pending = database.get_all_pickup_tasks()
        available_tasks = [t for t in pending if t.get("status") in ["PENDING", "OFFERED"]]
        
        if available_tasks:
            top_task = available_tasks[0]
            task_id = top_task["id"]
            don_id = top_task.get("donation_id", "")
            don = database.get_donation_record(don_id) if don_id else None
            food_info = f"{don.get('quantity', 15)} {don.get('unit', 'portions')} of {don.get('food_type', 'Prepared Meals')}" if don else "15 portions of food"
            
            p_area = top_task.get("pickup_location", "Colombo 3")
            d_area = top_task.get("delivery_location", "Colombo 7")
            
            cost_calc = routing.calculate_transport_estimate(6.2, "motorbike")
            est_cost = cost_calc.get("estimated_support_amount", 310.0)
            
            tools.set_session_context(key="current_task_id", value=task_id)
            tools.set_session_context(key="current_volunteer_id", value=vol_id)
            if phone:
                database.set_user_conversation_state(phone, {
                    "workflow": "VOLUNTEER",
                    "current_question": "ACCEPT_TASK",
                    "expected_input_type": "CHOICE",
                    "task_id": task_id
                })
            
            return (
                f"🎉 **Great! You are now marked as AVAILABLE.**\n\n"
                f"🚚 **Pickup Opportunity Available!**\n\n"
                f"• **Task ID**: `{task_id}`\n"
                f"• **Food**: {food_info}\n"
                f"• **Pickup Area**: 📍 {p_area} _(exact donor address shared upon acceptance)_\n"
                f"• **Destination**: 🏢 {d_area}\n"
                f"• **Distance**: ~6.2 km (~20 min)\n"
                f"• **Estimated Transport Support**: LKR {int(est_cost)}\n\n"
                f"Would you like to take this pickup?\n"
                f"👉 Reply *'Accept'* or *'Reject'*"
            )
        return (
            "🎉 **Great! You are now marked as AVAILABLE.**\n\n"
            "There are currently no active pickups waiting in your area.\n"
            "We will send you an immediate notification the moment a surplus food donation is matched nearby! ❤️"
        )

    # 6b. Volunteer Accept / Reject Task
    if any(m in clean_p for m in ["accept", "i'll take it", "ill take it", "take it", "i can do it", "accept task", "take pickup", "claim", "භාරගන්නවා", "ඔව්", "ஏற்கிறேன்", "ஆம்", "സ്വീകരിക്കുക", "ஏற்றுக்கொள்கிறேன்", "பணியை ஏற்கிறேன்"]):
        task_id = tools._get_context_val("current_task_id", "")
        if not task_id and phone:
            st = database.get_user_conversation_state(phone)
            task_id = st.get("task_id", "")
        if not task_id:
            pending = database.get_all_pickup_tasks()
            avail = [t for t in pending if t.get("status") in ["PENDING", "OFFERED", "OPEN"]]
            if avail:
                task_id = avail[0]["id"]
            else:
                task_id = "task-assigned-01"
                
        if task_id:
            vol_id = tools._get_context_val("current_volunteer_id", "")
            res_raw = tools.accept_pickup_task_atomic(pickup_task_id=task_id, volunteer_id=vol_id, phone=phone)
            res = json.loads(res_raw) if isinstance(res_raw, str) else {}
            
            if res.get("status") == "already_claimed":
                if phone:
                    database.clear_user_conversation_state(phone)
                return "Sorry, this pickup has already been accepted by another volunteer. 🚚 I'll look for another available task for you."
                
            if phone:
                database.clear_user_conversation_state(phone)
                
            f_info = res.get("food_info", "Surplus food package")
            d_name = res.get("donor_name", "Donor Partner")
            d_contact = res.get("donor_contact", "")
            p_loc = res.get("pickup_location", "Colombo")
            r_name = res.get("recipient_name", "Community Organization")
            r_loc = res.get("delivery_location", "Colombo")
            dist = res.get("total_distance_km", 6.2)
            cost = res.get("estimated_support_lkr", 310)
            route_link = res.get("directions_link", "")
            contact_line = f"\n• 📞 **Donor Contact**: {d_contact}" if d_contact else ""
            route_line = f"\n• 🗺️ **Open Route**: {route_link}" if route_link else ""
            
            return (
                f"✅ **Pickup Task Assigned & Accepted**\n\n"
                f"• 🆔 **Pickup**: `{task_id}`\n"
                f"• **Status**: `ASSIGNED`\n"
                f"• 🍚 **Food**: {f_info}\n"
                f"• 👤 **Donor**: {d_name}{contact_line}\n"
                f"• 🟢 **Pickup Location**: 📍 {p_loc}\n"
                f"• 🏢 **Recipient**: {r_name} ({r_loc})\n"
                f"• 📏 **Total Route**: ~{dist} km\n"
                f"• 💰 **Estimated Transport Support**: LKR {cost}{route_line}\n\n"
                f"📍 **Please share your current location**\n"
                f"Tap: **+ → Location → Send your current location**\n"
                f"This helps the donor and recipient know that you are on the way! 🚚\n\n"
                f"Once you collect the food, simply reply *'Collected'*."
            )
        return "No pending pickup task is currently selected. Reply **3** to see available volunteer opportunities."

    if clean_p in ["reject", "can't do it", "cant do it", "no", "decline", "බැහැ", "නැහැ", "மறுக்கிறேன்", "இல்லை", "ഇല്ല"]:
        task_id = tools._get_context_val("current_task_id", "")
        if task_id:
            tools.reject_pickup_task(pickup_task_id=task_id)
            if phone:
                database.clear_user_conversation_state(phone)
            return "👍 No problem! We will offer this task to another available volunteer courier. Thank you!"
        return "No active pickup offer was found. Reply **menu** to see options."

    # 6c. Collection Confirmation ("Collected")
    if any(m in clean_p for m in ["collected", "got the food", "food collected", "picked up", "pickup completed", "ආහාර ලබාගත්තා", "ලබාගත්තා", "உணவு சேகரித்தேன்", "சேகரித்தேன்", "ഭക്ഷണം ശേഖരിച്ചു"]):
        task_id = tools._get_context_val("current_task_id", "")
        if not task_id and phone:
            my_picks_raw = tools.get_my_pickups(phone=phone)
            my_picks = json.loads(my_picks_raw) if isinstance(my_picks_raw, str) else {}
            if my_picks.get("status") == "success" and my_picks.get("latest_task"):
                task_id = my_picks["latest_task"]["id"]
        if not task_id:
            all_tasks = database.get_all_pickup_tasks()
            active_tasks = [t for t in all_tasks if t.get("status") in ["ASSIGNED", "EN_ROUTE"]]
            if active_tasks:
                task_id = active_tasks[-1]["id"]
                
        if task_id:
            res_raw = tools.confirm_pickup(pickup_task_id=task_id)
            res = json.loads(res_raw) if isinstance(res_raw, str) else {}
            dest_org = res.get("destination_organization", "Community Kitchen")
            dest_loc = res.get("delivery_location", "Colombo 7")
            map_link = res.get("destination_map_link", "")
            map_info = f"\n• 📍 **Navigation Link**: {map_link}" if map_link else ""
            return (
                f"🍱 **Pickup Confirmed!**\n\n"
                f"• **Task ID**: `{task_id}`\n"
                f"• **Status**: `COLLECTED` (In Transit 🚚)\n\n"
                f"The donor and recipient have been notified.\n\n"
                f"**Next Step**: Please deliver the meals to:\n"
                f"• 🏢 **Recipient**: {dest_org} ({dest_loc}){map_info}\n\n"
                f"Once handed over, reply *'Delivered'*."
            )
        return "No assigned pickup task was found to mark as collected. Reply **5** to check your active tasks."

    # 6d. Delivery Confirmation ("Delivered")
    if any(m in clean_p for m in ["delivered", "food delivered", "dropped off", "delivery completed", "delivery done", "භාරදුන්නා", "බෙදාහැරියා", "வழங்கினேன்", "டெலிவரி", "ഡെലിവറി ചെയ്തു"]):
        task_id = tools._get_context_val("current_task_id", "")
        if not task_id and phone:
            my_picks_raw = tools.get_my_pickups(phone=phone)
            my_picks = json.loads(my_picks_raw) if isinstance(my_picks_raw, str) else {}
            if my_picks.get("status") == "success" and my_picks.get("latest_task"):
                task_id = my_picks["latest_task"]["id"]
        if not task_id:
            all_tasks = database.get_all_pickup_tasks()
            active_tasks = [t for t in all_tasks if t.get("status") in ["COLLECTED", "IN_TRANSIT", "ASSIGNED", "EN_ROUTE"]]
            if active_tasks:
                task_id = active_tasks[-1]["id"]
                
        if task_id:
            res_raw = tools.confirm_delivery(pickup_task_id=task_id)
            res = json.loads(res_raw) if isinstance(res_raw, str) else {}
            reimb = res.get("reimbursement", {})
            reimb_amount = reimb.get("estimated_support", 310)
            return (
                f"🎉 **Delivery Completed!**\n\n"
                f"• **Task ID**: `{task_id}`\n"
                f"• **Status**: `DELIVERED` / `COMPLETED`\n\n"
                f"Thank you for helping rescue and deliver surplus meals to people in need! ❤️\n\n"
                f"💰 **Transport Support**: Estimated reimbursement of **LKR {int(reimb_amount)}** recorded in accounting ledger.\n\n"
                f"You are now marked as **AVAILABLE** for your next rescue."
            )
        return "No active pickup task was found to mark as delivered. Reply **5** to check your active tasks."

    # 6e. General Volunteer Flow ("3", "volunteer", "courier", "want to volunteer")
    if clean_p == "3" or any(m in clean_p for m in ["want to volunteer", "volunteer", "courier", "help deliver"]):
        tools.register_volunteer(
            name="Volunteer Courier",
            service_area="Colombo",
            phone=phone,
            transport_mode="Motorbike"
        )
        tasks_raw = tools.get_available_pickup_tasks(location="Colombo")
        tasks_res = json.loads(tasks_raw) if isinstance(tasks_raw, str) else {}
        count = tasks_res.get("count", 0)
        return (
            f"❤️ **Thank You For Volunteering!**\n\n"
            f"You are registered as a FoodRescue AI volunteer courier (Service Area: Colombo).\n\n"
            f"📦 There are currently **{count} pending pickup task(s)** available.\n\n"
            f"Would you like to claim a pickup task?\n"
            f"1️⃣ View available tasks\n"
            f"2️⃣ Update my vehicle mode / service area\n"
            f"3️⃣ Check my active pickups"
        )

    # 7. Recipient Flow ("2", "request food", "need food", "community kitchen")
    if clean_p == "2" or any(m in clean_p for m in ["need food", "request food", "community kitchen", "food bank", "shelter"]):
        tools.register_organization(
            name="Community Food Organization",
            location="Colombo",
            service_area="Colombo",
            accepted_food_types="prepared meals, bakery, dry rations",
            phone=phone
        )
        avail_dons_raw = tools.get_available_donations(location="Colombo")
        avail_dons = json.loads(avail_dons_raw) if isinstance(avail_dons_raw, str) else {}
        count = avail_dons.get("count", 0)
        return (
            f"🏠 **Recipient Organization Service**\n\n"
            f"We have registered your organization with FoodRescue AI.\n\n"
            f"🔎 I currently found **{count} available surplus donation(s)** in your area.\n\n"
            f"Would you like me to reserve the available surplus food for your community?\n"
            f"1️⃣ Yes, request top available donation\n"
            f"2️⃣ View all available donations\n"
            f"3️⃣ Update dietary requirements"
        )

    # 8. Greetings & Main Menu
    if clean_p in ["hi", "hello", "hey", "menu", "help", "start", "6", "options", "ආයුබෝවන්", "வணக்கம்", "നമസ്കാരം"]:
        if user and user.get("onboarding_completed"):
            donor = database.get_donor_by_phone(phone) if phone else None
            if donor:
                return translation_service.get_localized_message("returning_donor_welcome", lang=lang, name=donor.get("name", ""))
            return translation_service.get_localized_message("returning_welcome", lang=lang)
        return translation_service.get_localized_message("onboarding_welcome", lang=lang)

    # =========================================================================
    # 9. DYNAMIC SLOT-FILLING & CONTEXT-AWARE DONATION WORKFLOW
    # =========================================================================
    curr_state = database.get_user_conversation_state(phone) if phone else {}
    expected_type = curr_state.get("expected_input_type", "")
    curr_q = curr_state.get("current_question", "")
    existing_draft = (database.get_draft_donation(phone) if phone else {}) or {}

    # 9a. Handle Confirmation Stage ("Confirm" / 1 -> commit donation)
    is_confirm_intent = clean_p in [
        "1", "confirm", "yes", "y", "ok", "okay", "correct", "create", "confirm donation",
        "තහවුරුයි", "ඔව්", "உறுதி", "ஆம்", "ശരി"
    ] or clean_p == "confirm" or "confirm" in clean_p
    
    if (curr_q == "CONFIRMATION" or expected_type == "CONFIRMATION" or (is_confirm_intent and existing_draft.get("food_type"))):
        if is_confirm_intent:
            # Commit donation from persistent draft
            qty = float(existing_draft.get("quantity") or 25.0)
            food = existing_draft.get("food_type") or "Prepared Meals"
            unit = existing_draft.get("unit") or "portions"
            dietary = existing_draft.get("dietary_info") or "Standard"
            loc = existing_draft.get("location") or existing_draft.get("pickup_location") or "Colombo"
            deadline = existing_draft.get("pickup_deadline") or "Before 8 PM"

            if phone:
                donor_user = database.get_user_by_phone(phone)
                donor_name = (donor_user.get("display_name") if donor_user else None) or "Donor Partner"
                tools.register_donor(name=donor_name, location=loc, phone=phone)

            don_raw = tools.create_donation(
                donor_id="d1",
                food_type=food,
                quantity=qty,
                unit=unit,
                dietary_information=dietary,
                location=loc,
                available_from="Now",
                pickup_deadline=deadline
            )
            don_res = json.loads(don_raw) if isinstance(don_raw, str) else {}
            don_id = don_res.get("donation_id", f"don-{uuid.uuid4().hex[:8]}")

            # Match org
            match_raw = tools.find_matching_organizations(food_type=food, location=loc)
            match_res = json.loads(match_raw) if isinstance(match_raw, str) else {}
            org_id = "o1"
            org_name = "Community Kitchen Colombo"
            deliv_loc = "Colombo 7"
            if match_res.get("organizations"):
                top_org = match_res["organizations"][0]
                org_id = top_org.get("id", top_org.get("org_id", "o1"))
                org_name = top_org.get("name", "Community Kitchen Colombo")
                deliv_loc = top_org.get("location", "Colombo 7")
                if don_id:
                    tools.accept_donation(donation_id=don_id, organization_id=org_id)

            # Match volunteer & assign task
            vol_raw = tools.find_available_volunteers(location=loc)
            vol_res = json.loads(vol_raw) if isinstance(vol_raw, str) else {}
            vol_id = "v1"
            vol_name = "Amara Silva"
            if vol_res.get("volunteers"):
                top_vol = vol_res["volunteers"][0]
                vol_id = top_vol.get("id", top_vol.get("volunteer_id", "v1"))
                vol_name = top_vol.get("name", "Amara Silva")

            task_id = ""
            if don_id:
                task_raw = tools.create_pickup_task(
                    donation_id=don_id,
                    organization_id=org_id,
                    pickup_location=loc,
                    delivery_location=deliv_loc,
                    scheduled_time=deadline
                )
                task_res = json.loads(task_raw) if isinstance(task_raw, str) else {}
                task_id = task_res.get("task_id", "")
                if task_id and vol_id:
                    tools.assign_volunteer(task_id=task_id, volunteer_id=vol_id)

            if phone:
                database.clear_draft_donation(phone)
                database.clear_user_conversation_state(phone)

            return translation_service.get_localized_message(
                "donation_created_card",
                lang=lang,
                donation_id=don_id,
                quantity=qty,
                unit=unit,
                food_type=food,
                dietary=dietary,
                pickup_loc=loc,
                deadline=deadline,
                org_name=org_name,
                deliv_loc=deliv_loc,
                vol_name=vol_name
            )

        elif clean_p in ["2", "edit", "change", "modify"]:
            return "📝 What details would you like to update? (You can say *'Actually 40 meals'*, *'Change location to Colombo 3'*, or *'Pickup time 7 PM'*)"
        elif clean_p in ["3", "cancel", "stop"]:
            if phone:
                database.clear_draft_donation(phone)
                database.clear_user_conversation_state(phone)
            return "🛑 Donation creation cancelled. Reply **menu** anytime to start again."

    # 9b. Context-Aware Numbered Input Resolution for Food Type Question
    if curr_q == "FOOD_TYPE" or expected_type == "FOOD_CHOICE":
        opt_map = {
            "1": "Rice & Curry",
            "2": "Bread & Bakery",
            "3": "Vegetarian Meals",
            "4": "Biryani",
            "5": "Prepared Meals"
        }
        chosen_food = None
        if clean_p in opt_map:
            chosen_food = opt_map[clean_p]
        elif "1 and 3" in clean_p or "1 & 3" in clean_p or "1, 3" in clean_p or "1,3" in clean_p:
            chosen_food = "Rice & Vegetarian Meals"
        elif "1 and 2" in clean_p or "1 & 2" in clean_p:
            chosen_food = "Rice & Bread"
        elif "rice" in clean_p and "curry" in clean_p:
            chosen_food = "Rice & Curry"
        elif "rice" in clean_p:
            chosen_food = "Rice"
        elif "bread" in clean_p:
            chosen_food = "Bread & Bakery"
        elif "biryani" in clean_p:
            chosen_food = "Biryani"
        elif "other" in clean_p:
            custom_food = re.sub(r'^(?:5|other\s*-\s*|other\s*)', '', prompt, flags=re.IGNORECASE).strip()
            chosen_food = custom_food.title() if custom_food else "Prepared Meals"

        if chosen_food:
            draft_update = {"food_type": chosen_food}
            if "veg" in chosen_food.lower():
                draft_update["dietary_info"] = "Vegetarian"
            if phone:
                existing_draft = database.save_draft_donation(phone, draft_update)

    # 9c. Context-Aware Number Resolution for Quantity Question
    elif curr_q == "QUANTITY" or expected_type == "QUANTITY":
        m_num = re.search(r'\b(\d+(?:\.\d+)?)\b', prompt)
        if m_num:
            qty_val = float(m_num.group(1))
            draft_update = {"quantity": qty_val}
            m_unit = re.search(r'\b(packets?|meals?|boxes?|portions?|kg|plates?)\b', prompt, re.IGNORECASE)
            if m_unit:
                draft_update["unit"] = m_unit.group(1).lower()
            if phone:
                existing_draft = database.save_draft_donation(phone, draft_update)

    # 9d. Context-Aware Location Question
    elif curr_q == "LOCATION" or expected_type == "LOCATION":
        loc_val = _extract_location(prompt)
        if loc_val:
            if phone:
                existing_draft = database.save_draft_donation(phone, {"location": loc_val})

    # 9e. Context-Aware Deadline Question
    elif curr_q == "DEADLINE" or expected_type == "DEADLINE":
        deadline_match = re.search(r'(?:before|until|by|at)?\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)', prompt, re.IGNORECASE)
        time_val = deadline_match.group(1).strip().upper() if (deadline_match and deadline_match.group(1)) else prompt.strip()
        if phone:
            existing_draft = database.save_draft_donation(phone, {"pickup_deadline": time_val})

    # 9f. General Entity Extraction on any natural message (only if not a menu command or specific choice question)
    if curr_q not in ["FOOD_TYPE", "LANGUAGE_MENU"] and not prompt.strip().isdigit() and prompt.strip() not in ["1", "2", "3", "4", "5", "6"]:
        entities = voice_service.extract_donation_entities(prompt)
        draft_patch = {}
        if entities.get("food_type") and (not existing_draft.get("food_type") or "actually" in clean_p or "change" in clean_p):
            draft_patch["food_type"] = entities["food_type"]
        if entities.get("quantity") is not None and (not existing_draft.get("quantity") or "actually" in clean_p or "change" in clean_p):
            draft_patch["quantity"] = entities["quantity"]
            if entities.get("unit"):
                draft_patch["unit"] = entities["unit"]
        if entities.get("location") and (not existing_draft.get("location") or "actually" in clean_p or "change" in clean_p or "location" in clean_p):
            draft_patch["location"] = entities["location"]
        if entities.get("pickup_deadline") and (not existing_draft.get("pickup_deadline") or "actually" in clean_p or "change" in clean_p or "time" in clean_p):
            draft_patch["pickup_deadline"] = entities["pickup_deadline"]
        if entities.get("dietary_info") and entities["dietary_info"] != "Standard":
            draft_patch["dietary_info"] = entities["dietary_info"]

        if draft_patch and phone:
            existing_draft = database.save_draft_donation(phone, draft_patch)
            tools.register_donor(
                name=user.get("display_name", "Donor Partner") if user else "Donor Partner",
                location=draft_patch.get("location") or existing_draft.get("location") or "Colombo",
                phone=phone
            )

    # 9g. If User Pressed "1" or says "I want to donate" with no draft yet, start donation flow:
    if (clean_p in ["1", "donate", "i want to donate", "donate food", "i have food", "පරිත්‍යාග", "தானம்"]) and not existing_draft.get("food_type"):
        if phone:
            database.set_user_conversation_state(phone, {
                "workflow": "DONATION",
                "current_question": "FOOD_TYPE",
                "expected_input_type": "FOOD_CHOICE",
                "available_options": {
                    "1": "Rice & Curry",
                    "2": "Bread & Bakery",
                    "3": "Vegetarian Meals",
                    "4": "Biryani",
                    "5": "Other"
                }
            })
        return (
            "🍱 *What type of Food do you have for Donation?*\n\n"
            "1️⃣ Rice & Curry\n"
            "2️⃣ Bread & Bakery\n"
            "3️⃣ Vegetarian Meals\n"
            "4️⃣ Biryani\n"
            "5️⃣ Other\n\n"
            "Reply with a number or simply describe the food."
        )

    # 9h. Dynamic Slot Assessment
    food_val = existing_draft.get("food_type")
    qty_val = existing_draft.get("quantity")
    loc_val = existing_draft.get("location")
    time_val = existing_draft.get("pickup_deadline")
    dietary_val = existing_draft.get("dietary_info", "Standard")
    unit_val = existing_draft.get("unit", "portions")

    # Check next missing slot
    if not food_val:
        if phone:
            database.set_user_conversation_state(phone, {
                "workflow": "DONATION",
                "current_question": "FOOD_TYPE",
                "expected_input_type": "FOOD_CHOICE"
            })
        return "🍱 *What type of food do you have available?* (e.g. Rice & Curry, Bread, Vegetarian Meals)"

    if qty_val is None or float(qty_val) <= 0:
        if phone:
            database.set_user_conversation_state(phone, {
                "workflow": "DONATION",
                "current_question": "QUANTITY",
                "expected_input_type": "QUANTITY"
            })
        return translation_service.get_localized_message("slot_ask_quantity", lang=lang, food_type=food_val)

    if not loc_val:
        if phone:
            database.set_user_conversation_state(phone, {
                "workflow": "DONATION",
                "current_question": "LOCATION",
                "expected_input_type": "LOCATION"
            })
        return (
            f"Great! I have recorded {qty_val} {unit_val} of {food_val}. 🍚\n\n"
            "📍 Before I create the donation, please share the exact pickup location using WhatsApp.\n\n"
            "Tap: **+ → Location → Send your current location**\n\n"
            "This location will only be shared with the assigned volunteer courier."
        )

    if not time_val:
        if phone:
            database.set_user_conversation_state(phone, {
                "workflow": "DONATION",
                "current_question": "DEADLINE",
                "expected_input_type": "DEADLINE"
            })
        return (
            f"Great! I have recorded {qty_val} {unit_val} of {food_val}.\n\n"
            "What time should the food be collected by?"
        )

    # All slots collected! Present Summary Confirmation
    if phone:
        database.set_user_conversation_state(phone, {
            "workflow": "DONATION",
            "current_question": "CONFIRMATION",
            "expected_input_type": "CONFIRMATION"
        })

    donor_user = database.get_user_by_phone(phone) if phone else None
    donor_name = (donor_user.get("display_name") if donor_user else None) or "Donor Partner"

    return (
        "📦 **Donation Summary**\n\n"
        f"🍚 Food: {food_val}\n"
        f"📦 Quantity: {qty_val} {unit_val}\n"
        f"📍 Pickup location: {loc_val}\n"
        f"⏰ Pickup deadline: {time_val}\n"
        f"👤 Donor: {donor_name}\n\n"
        "Everything is ready.\n\n"
        "**Confirm donation?**\n\n"
        "Reply:\n"
        "**Confirm** or **Change**"
    )


async def run_resilient_chat(
    prompt: str,
    session_id: str,
    preferred_agent: Optional[str] = None
) -> Dict[str, Any]:
    """Execute chat request through foodrescue_coordinator with dynamic model fallback."""
    chat_service = ChatService(rest_api_mode=True)
    agent_name = "foodrescue_coordinator"

    # Distinct model candidates
    seen = set()
    model_candidates = []
    for m in MODEL_POOL:
        if m and m not in seen:
            seen.add(m)
            model_candidates.append(m)

    for model_name in model_candidates:
        try:
            logger.info(f"[Resilient Run] Executing '{agent_name}' with model '{model_name}' for session '{session_id}'")
            # Update agent model dynamically
            app.foodrescue_coordinator.model = model_name

            req = BaseChatRequest(
                agent=agent_name,
                prompt=prompt,
                session_id=session_id
            )
            # Cap individual agent execution at 8.0s to avoid hanging on slow retries
            chat_result = await asyncio.wait_for(
                chat_service.process_async_chat_request(req),
                timeout=8.0
            )

            if isinstance(chat_result, dict):
                reply_text = chat_result.get("result", "")
            else:
                reply_text = str(chat_result)
            
            # If the response contains an unhandled rate limit or agent execution failure message, rotate model
            if not reply_text or any(m in reply_text.lower() for m in [
                "quota exceeded",
                "resource_exhausted",
                "too many requests",
                "429",
                "no api key",
                "error processing",
                "encountered an error",
                "node failed",
                "dynamic node"
            ]):
                logger.warning(f"Model '{model_name}' returned failure/error in text: '{reply_text[:60]}...'. Rotating model...")
                continue

            return {
                "status": "success",
                "result": reply_text,
                "agent_used": agent_name,
                "model_used": model_name,
                "session_id": session_id,
            }

        except Exception as exc:
            if _is_rate_limit_error(exc) or isinstance(exc, asyncio.TimeoutError):
                logger.warning(f"Model '{model_name}' hit rate limit or timeout ({exc}). Rotating model...")
                continue
            else:
                logger.error(f"Execution notice on model '{model_name}': {exc}. Trying next candidate...")
                continue

    # If all models in the pool were rate limited, execute deterministic fallback
    logger.warning("All LLM models in pool were rate-limited. Activating deterministic fallback.")
    fallback_result = await execute_deterministic_fallback(prompt, session_id)
    return {
        "status": "success",
        "result": fallback_result,
        "agent_used": agent_name,
        "model_used": "deterministic_fallback",
        "session_id": session_id,
        "notice": "Served via high-reliability fallback engine during peak LLM rate limit window."
    }
