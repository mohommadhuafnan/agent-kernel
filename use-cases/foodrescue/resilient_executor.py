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
from typing import Optional, Dict, Any, List, Tuple
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


def _extract_location(text: str) -> Optional[str]:
    """Extract location from text or None if not found."""
    loc_match = re.search(
        r'\b(Colombo(?:\s*(?:0?[1-9]|1[0-5]))?|Kandy|Galle|Dehiwala|Nugegoda|Mount Lavinia|Rajagiriya|Bambalapitiya|Kollupitiya|Fort|Cinnamon Gardens|Wellawatte|Battaramulla|Negombo|Mawanella|Kurunegala|Jaffna|Matara)\b',
        text,
        re.IGNORECASE
    )
    if loc_match:
        return loc_match.group(1).strip()
    return None


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


def _calculate_dynamic_task_metrics(task: Dict[str, Any], vol_record: Optional[Dict[str, Any]] = None) -> Tuple[float, float, str, str, str, str, str]:
    """Calculate real road distance, transport cost, donor, and recipient info dynamically."""
    don_id = task.get("donation_id", "")
    don = database.get_donation_record(don_id) if don_id else None
    
    donor_id = don.get("donor_id", "") if don else ""
    donor = database.get_donor_record(donor_id) if donor_id else None
    donor_name = donor.get("name") if donor else (don.get("donor_name") if don else "Donor Partner")
    donor_contact = donor.get("phone") if donor else (don.get("donor_phone") if don else "")
    
    org_id = task.get("organization_id", "")
    org = database.get_organization_record(org_id) if org_id else None
    recipient_name = org.get("name") if org else "Recipient Organization"
    
    p_loc = task.get("pickup_location") or (don.get("pickup_location") if don else "Pickup Location")
    d_loc = task.get("delivery_location") or (org.get("location") if org else "Delivery Location")
    
    vol_mode = vol_record.get("transport_mode", "Motorbike") if vol_record else "Motorbike"
    vol_loc = vol_record.get("current_location") or vol_record.get("location") or vol_record.get("service_area") if vol_record else None
    
    p_coords = routing.geocode_location(p_loc)
    d_coords = routing.geocode_location(d_loc)
    v_coords = routing.geocode_location(vol_loc) if vol_loc else None
    
    if p_coords and d_coords:
        if v_coords:
            leg1 = routing.calculate_haversine_distance(v_coords[0], v_coords[1], p_coords[0], p_coords[1]) * 1.25
            leg2 = routing.calculate_haversine_distance(p_coords[0], p_coords[1], d_coords[0], d_coords[1]) * 1.25
            total_dist = round(max(0.5, leg1 + leg2), 1)
        else:
            total_dist = round(max(0.5, routing.calculate_haversine_distance(p_coords[0], p_coords[1], d_coords[0], d_coords[1]) * 1.25), 1)
    else:
        total_dist = float(task.get("total_distance_km") or task.get("pickup_distance_km") or 5.0)
        
    cost_calc = routing.calculate_transport_estimate(total_dist, vol_mode.lower())
    est_cost = float(cost_calc.get("estimated_support_amount") or (total_dist * routing.get_transport_rate(vol_mode.lower())))
    
    directions_link = ""
    if p_coords and d_coords:
        directions_link = routing.generate_directions_link(p_coords[0], p_coords[1], d_coords[0], d_coords[1])
        
    return total_dist, est_cost, donor_name, donor_contact, recipient_name, p_loc, d_loc


async def execute_deterministic_fallback(prompt: str, session_id: str) -> str:
    """Perform deterministic workflow execution when all LLM quotas are exhausted or for offline rule processing."""
    logger.warning(f"[Deterministic Fallback] Executing offline rule engine for session '{session_id}' with prompt: {prompt[:60]}")
    
    tools.set_explicit_session_id(session_id)
    clean_p = prompt.strip().lower()
    phone = session_id.split("whatsapp:", 1)[1] if "whatsapp:" in session_id else ""

    # Resolve persistent user profile and language
    user = database.get_user_by_phone(phone) if phone else None
    detected = translation_service.detect_language(prompt)
    if detected and detected in ["si", "ta"]:
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
    if clean_p in ["language", "languages", "භාෂාව", "மொழி", "change language"]:
        if phone:
            database.set_user_conversation_state(phone, {
                "workflow": "LANGUAGE",
                "current_question": "LANGUAGE_MENU",
                "expected_input_type": "CHOICE",
                "available_options": {"1": "en", "2": "si", "3": "ta"}
            })
        return (
            "🌍 *FoodRescue AI Language Selection / භාෂාව තෝරන්න / மொழியைத் தேர்ந்தெடுக்கவும்*:\n\n"
            "Reply with:\n"
            "1️⃣ English\n"
            "2️⃣ Sinhala (සිංහල)\n"
            "3️⃣ Tamil (தமிழ்)"
        )

    # 4. Status Queries (Donation / Pickup)
    if clean_p in ["4", "where is my donation?", "where is my donation", "show my donation", "what is my donation status?", "what is my donation status", "check my donation", "track my food"]:
        my_dons_raw = tools.get_my_donations(phone=phone)
        my_dons = json.loads(my_dons_raw) if isinstance(my_dons_raw, str) else {}
        if my_dons.get("status") == "success" and my_dons.get("latest_donation"):
            don = my_dons["latest_donation"]
            tasks = my_dons.get("latest_pickup_tasks", [])
            task_info = f"\n🚚 **Pickup**: {tasks[0].get('status', 'PENDING')}" if tasks else ""
            return translation_service.get_localized_message(
                "donation_status_card",
                lang=lang,
                donation_id=don.get("id"),
                food_type=don.get("food_type"),
                quantity=don.get("quantity"),
                unit=don.get("unit"),
                location=don.get("pickup_location"),
                status=don.get("status"),
                task_info=task_info
            )
        return translation_service.get_localized_message("donation_status_empty", lang=lang)

    if clean_p in ["5", "show my pickup", "where is the pickup?", "where is the pickup", "where is the volunteer?", "where is the volunteer", "where is the food?", "where is the food", "what is my pickup?", "what is my pickup", "pickup status"]:
        my_picks_raw = tools.get_my_pickups(phone=phone)
        my_picks = json.loads(my_picks_raw) if isinstance(my_picks_raw, str) else {}
        if my_picks.get("status") == "success" and my_picks.get("latest_task"):
            task = my_picks["latest_task"]
            vol_name = task.get("volunteer_id", "Assigned Volunteer")
            return translation_service.get_localized_message(
                "pickup_status_card",
                lang=lang,
                task_id=task.get("id"),
                status=task.get("status"),
                pickup_location=task.get("pickup_location"),
                delivery_location=task.get("delivery_location"),
                scheduled_time=task.get("scheduled_time"),
                volunteer_name=vol_name
            )
        return translation_service.get_localized_message("pickup_status_empty", lang=lang)

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
                return translation_service.get_localized_message(
                    "donation_cancelled_success",
                    lang=lang,
                    donation_id=don_id
                )
        return translation_service.get_localized_message("donation_cancelled_draft_success", lang=lang)

    # =========================================================================
    # 5.5 GREETINGS & MAIN MENU (Early dispatch when not in active workflow)
    # =========================================================================
    curr_state = database.get_user_conversation_state(phone) if phone else {}
    in_active_workflow = bool(curr_state.get("workflow"))
    is_greeting_word = clean_p in [
        "hi", "hello", "hey", "menu", "help", "start", "6", "options",
        "මෙනුව", "ආයුබෝවන්", "வணக்கம்", "welcome", "greetings"
    ]
    if is_greeting_word and not in_active_workflow:
        if user and user.get("onboarding_completed"):
            donor_rec = database.get_donor_by_phone(phone) if phone else None
            if donor_rec:
                return translation_service.get_localized_message("returning_donor_welcome", lang=lang, name=donor_rec.get("name", ""))
            return translation_service.get_localized_message("returning_welcome", lang=lang)
        return translation_service.get_localized_message("onboarding_welcome", lang=lang)

    # =========================================================================
    # 6. VOLUNTEER COURIER COORDINATION & PROGRESSIVE ONBOARDING
    # =========================================================================
    in_vol_workflow = curr_state.get("workflow") in ["VOLUNTEER", "VOLUNTEER_REGISTRATION"]
    existing_vol = database.get_volunteer_by_phone(phone) if phone else None

    # 6a. Option 1 / View Available Tasks for Volunteer
    is_vol_view_tasks = (
        (clean_p in ["1", "view available tasks", "view tasks", "available tasks", "pending tasks", "check tasks"] and (existing_vol or in_vol_workflow))
    )
    if is_vol_view_tasks:
        pending = database.get_all_pickup_tasks()
        available_tasks = [t for t in pending if t.get("status") in ["PENDING", "OFFERED", "OPEN"]]
        if available_tasks:
            top_task = available_tasks[0]
            task_id = top_task["id"]
            don_id = top_task.get("donation_id", "")
            don = database.get_donation_record(don_id) if don_id else None
            food_info = f"{don.get('quantity', 30)} {don.get('unit', 'meal packets')} of {don.get('food_type', 'Rice & Curry')}" if don else "30 meal packets of Rice & Curry"
            
            vol_rec = existing_vol or (database.get_volunteer_by_phone(phone) if phone else None)
            total_dist, est_cost, d_name, d_contact, r_name, p_area, d_area = _calculate_dynamic_task_metrics(top_task, vol_rec)
            
            tools.set_session_context(key="current_task_id", value=task_id)
            if existing_vol:
                tools.set_session_context(key="current_volunteer_id", value=existing_vol["id"])
            if phone:
                database.set_user_conversation_state(phone, {
                    "workflow": "VOLUNTEER",
                    "current_question": "ACCEPT_TASK",
                    "expected_input_type": "CHOICE",
                    "task_id": task_id
                })
            
            return (
                f"🚚 **Food Pickup Opportunity Available!**\n\n"
                f"• 🆔 **Task ID**: `{task_id}`\n"
                f"• 🍱 **Food**: {food_info}\n"
                f"• 📍 **Pickup Location**: {p_area}\n"
                f"• 🏢 **Destination**: {r_name} ({d_area})\n"
                f"• 📏 **Estimated Distance**: ~{total_dist} km\n"
                f"• 💰 **Estimated Transport Support**: LKR {int(est_cost)}\n\n"
                f"Would you like to take this pickup?\n"
                f"👉 Reply *'Accept'* or *'Reject'*"
            )
        else:
            return (
                "📦 **Pending Pickup Tasks:**\n\n"
                "There are currently 0 unassigned pickup tasks waiting in your area.\n"
                "You are marked as **AVAILABLE**, and our AI coordinator will notify you immediately the moment a food pickup is ready nearby! ❤️"
            )

    # 6b. Volunteer Accept / Reject Task
    if any(m in clean_p for m in ["accept", "i'll take it", "ill take it", "take it", "i can do it", "accept task", "take pickup", "claim", "භාරගන්නවා", "ඔව්", "ஏற்கிறேன்", "ஆம்", "ஏற்றுக்கொள்கிறேன்", "பணியை ஏற்கிறேன்"]):
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
            if not vol_id and existing_vol:
                vol_id = existing_vol["id"]
            res_raw = tools.accept_pickup_task_atomic(pickup_task_id=task_id, volunteer_id=vol_id, phone=phone)
            res = json.loads(res_raw) if isinstance(res_raw, str) else {}
            
            if res.get("status") == "already_claimed":
                if phone:
                    database.clear_user_conversation_state(phone)
                return "Sorry, this pickup has already been accepted by another volunteer. 🚚 I'll look for another available task for you."
                
            if phone:
                database.clear_user_conversation_state(phone)
                
            f_info = res.get("food_info", "Food Donation")
            d_name = res.get("donor_name", "Donor Partner")
            d_contact = res.get("donor_contact", "")
            p_loc = res.get("pickup_location", "Pickup Location")
            r_name = res.get("recipient_name", "Recipient Organization")
            r_loc = res.get("delivery_location", "Delivery Location")
            dist = res.get("total_distance_km", 5.0)
            cost = res.get("estimated_support_lkr", 250)
            route_link = res.get("directions_link", "")
            contact_line = f"\n• 📞 **Donor Contact**: {d_contact}" if d_contact else ""
            route_line = f"\n• 🗺️ **Open Route**: {route_link}" if route_link else ""
            
            return (
                f"✅ **Pickup Task Assigned & Accepted**\n\n"
                f"• 🆔 **Pickup**: `{task_id}`\n"
                f"• **Status**: `ASSIGNED`\n"
                f"• 🍱 **Food**: {f_info}\n"
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

    if clean_p in ["reject", "can't do it", "cant do it", "no", "decline", "බැහැ", "නැහැ", "மறுக்கிறேன்", "இல்லை"]:
        task_id = tools._get_context_val("current_task_id", "")
        if task_id:
            tools.reject_pickup_task(pickup_task_id=task_id)
            if phone:
                database.clear_user_conversation_state(phone)
            return "👍 No problem! We will offer this task to another available volunteer courier. Thank you!"
        return "No active pickup offer was found. Reply **menu** to see options."

    # 6c. Collection Confirmation ("Collected")
    if any(m in clean_p for m in ["collected", "got the food", "food collected", "picked up", "pickup completed", "ආහාර ලබාගත්තා", "ලබාගත්තා", "உணவு சேகரித்தேன்", "சேகரித்தேன்"]):
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
            dest_org = res.get("destination_organization", "Hope Food Home")
            dest_loc = res.get("delivery_location", "Mawanella")
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
    if any(m in clean_p for m in ["delivered", "food delivered", "dropped off", "delivery completed", "delivery done", "භාරදුන්නා", "බෙදාහැරියා", "வழங்கினேன்", "டெலிவரி"]):
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
            reimb_amount = reimb.get("estimated_support", 378)
            return (
                f"🎉 **Delivery Completed!**\n\n"
                f"• **Task ID**: `{task_id}`\n"
                f"• **Status**: `DELIVERED` / `COMPLETED`\n\n"
                f"Thank you for helping rescue and deliver surplus meals to people in need! ❤️\n\n"
                f"💰 **Transport Support**: Estimated reimbursement of **LKR {int(reimb_amount)}** recorded in accounting ledger.\n\n"
                f"You are now marked as **AVAILABLE** for your next rescue."
            )
        return "No active pickup task was found to mark as delivered. Reply **5** to check your active tasks."

    # 6e. Volunteer Registration & Progressive Availability Intent
    is_vol_intent = any(m in clean_p for m in [
        "i'm free", "i am free", "free now", "i can help", "available for pickup", "available to help",
        "available courier", "pickups near me", "any pickups", "have time", "ready to help",
        "volunteer", "want to volunteer", "courier", "help deliver", "available to volunteer",
        "free to volunteer", "ready to volunteer", "delivery volunteer",
        "ස්වේච්ඡා", "උදව් කරන්න පුළුවන්", "ලෑස්තියි", "உதவ முடியும்", "தன்னார்வலர்", "இலவசம்"
    ]) or (clean_p == "3" and not in_vol_workflow)

    if (is_vol_intent or in_vol_workflow) and not (clean_p in ["hi", "hello", "hey", "menu", "start"] and not in_vol_workflow):
        # 6e-1. Direct availability declaration (e.g. "I'm free now", "Hii i am available to volunteer today", "I'm free to volunteer now")
        is_direct_avail = any(m in clean_p for m in [
            "free now", "i'm free", "i am free", "free to volunteer", "available for pickup",
            "available to volunteer", "available to help", "ready to help", "ස්වේච්ඡා", "ලෑස්තියි", "උදව් කරන්න පුළුවන්"
        ])

        if is_direct_avail and not in_vol_workflow:
            if not existing_vol:
                tools.register_volunteer(
                    name="Volunteer Courier",
                    service_area="Colombo",
                    phone=phone,
                    transport_mode="Motorbike"
                )
                existing_vol = database.get_volunteer_by_phone(phone) if phone else None
            
            if existing_vol:
                tools.update_volunteer_availability(volunteer_id=existing_vol["id"], status="AVAILABLE", current_location=existing_vol.get("service_area", "Colombo"))
            
            pending = database.get_all_pickup_tasks()
            available_tasks = [t for t in pending if t.get("status") in ["PENDING", "OFFERED", "OPEN"]]
            count = len(available_tasks)
            
            if phone:
                database.set_user_conversation_state(phone, {
                    "workflow": "VOLUNTEER",
                    "current_question": "CLAIM_TASK",
                    "expected_input_type": "CHOICE"
                })
                
            vol_area = existing_vol.get("service_area", "Colombo") if existing_vol else "Colombo"
            if count > 0:
                return (
                    f"🎉 **Great! You are now marked as AVAILABLE.**\n\n"
                    f"❤️ **Thank You For Volunteering!**\n"
                    f"You are registered as a FoodRescue AI volunteer courier (Service Area: {vol_area}).\n\n"
                    f"🚚 **Pickup Opportunity Available!**\n"
                    f"📦 There are currently **{count} pending pickup task(s)** available.\n\n"
                    f"Would you like to claim a pickup task?\n"
                    f"1️⃣ View available tasks (or reply *'Accept'*)\n"
                    f"2️⃣ Update my vehicle mode / service area\n"
                    f"3️⃣ Check my active pickups"
                )
            else:
                return (
                    f"🎉 **Great! You are now marked as AVAILABLE.**\n\n"
                    f"❤️ **Thank You For Volunteering!**\n"
                    f"You are registered as a FoodRescue AI volunteer courier (Service Area: {vol_area}).\n\n"
                    f"📦 There are currently **no active pickups** (0 pending tasks) available in your area.\n\n"
                    f"Would you like to check options?\n"
                    f"1️⃣ View available tasks\n"
                    f"2️⃣ Update my vehicle mode / service area\n"
                    f"3️⃣ Check my active pickups"
                )

        vol_name = (existing_vol.get("name") if existing_vol else None) or curr_state.get("vol_name")
        vol_vehicle = (existing_vol.get("transport_mode") if existing_vol else None) or curr_state.get("vol_vehicle")
        vol_loc = (existing_vol.get("service_area") if existing_vol else None) or curr_state.get("vol_loc")

        # Extract Volunteer Name
        v_name_match = re.search(r"(?:my\s*name\s*is|name\s*:|i\s*am)\s*([a-zA-Z\s]+)", prompt, re.IGNORECASE)
        if v_name_match and "kamal hotel" not in clean_p:
            vol_name = v_name_match.group(1).strip()
        elif curr_state.get("expected_input_type") == "VOL_NAME" and len(clean_p.split()) <= 4:
            vol_name = prompt.strip().title()

        # Extract Vehicle / Transport Mode
        if any(w in clean_p for w in ["three-wheeler", "three wheeler", "tuk", "tuk tuk"]):
            vol_vehicle = "Three-Wheeler"
        elif any(w in clean_p for w in ["motorbike", "bike", "motorcycle"]):
            vol_vehicle = "Motorbike"
        elif "car" in clean_p:
            vol_vehicle = "Car"
        elif "van" in clean_p:
            vol_vehicle = "Van"
        elif "bicycle" in clean_p:
            vol_vehicle = "Bicycle"
        elif curr_state.get("expected_input_type") == "VOL_VEHICLE" and len(clean_p.split()) <= 3:
            vol_vehicle = prompt.strip().title()

        # Extract Location / City
        v_loc_match = re.search(r"(?:location|city|district|area)\s*:\s*([^\n\r,]+)", prompt, re.IGNORECASE)
        if v_loc_match:
            vol_loc = v_loc_match.group(1).strip()
        else:
            cities = ["mawanella", "kegalle", "colombo", "kandy", "galle", "matara", "negombo", "gampaha", "jaffna", "kurunegala", "anuradhapura", "batticaloa", "trincomalee", "ratnapura"]
            for c in cities:
                if c in clean_p:
                    vol_loc = c.capitalize()
                    break
        if not vol_loc and curr_state.get("expected_input_type") == "VOL_CITY" and len(clean_p.split()) <= 3:
            vol_loc = prompt.strip().title()

        # If details are complete (or volunteer was already registered)
        if (vol_name or existing_vol) and (vol_vehicle or (existing_vol and existing_vol.get("transport_mode"))) and (vol_loc or (existing_vol and existing_vol.get("service_area"))):
            final_vol_name = vol_name or (existing_vol.get("name") if existing_vol else "Kamal")
            final_vol_veh = vol_vehicle or (existing_vol.get("transport_mode") if existing_vol else "Three-Wheeler")
            final_vol_loc = vol_loc or (existing_vol.get("service_area") if existing_vol else "Mawanella")

            if phone:
                if not existing_vol:
                    tools.register_volunteer(
                        name=final_vol_name,
                        service_area=final_vol_loc,
                        phone=phone,
                        transport_mode=final_vol_veh
                    )
                database.update_user_profile(
                    phone=phone,
                    display_name=final_vol_name,
                    user_role="volunteer",
                    default_location=final_vol_loc
                )
            
            # Clear conversation state
            if phone:
                database.set_user_conversation_state(phone, {})

            # Look up pending tasks
            pending = database.get_all_pickup_tasks()
            available_tasks = [t for t in pending if t.get("status") in ["PENDING", "OFFERED", "OPEN"]]
            
            if available_tasks:
                top_task = available_tasks[0]
                task_id = top_task["id"]
                don_id = top_task.get("donation_id", "")
                don = database.get_donation_record(don_id) if don_id else None
                food_info = f"{don.get('quantity', 30)} {don.get('unit', 'meal packets')} — {don.get('food_type', 'Rice & Curry')}" if don else "30 meal packets — Rice & Curry"
                
                vol_record = database.get_volunteer_by_phone(phone) if phone else None
                total_dist, est_cost, d_name, d_contact, r_name, p_area, d_area = _calculate_dynamic_task_metrics(top_task, vol_record or {"transport_mode": final_vol_veh, "service_area": final_vol_loc})
                
                tools.set_session_context(key="current_task_id", value=task_id)
                if vol_record:
                    tools.set_session_context(key="current_volunteer_id", value=vol_record["id"])
                if phone:
                    database.set_user_conversation_state(phone, {
                        "workflow": "VOLUNTEER",
                        "current_question": "ACCEPT_TASK",
                        "expected_input_type": "CHOICE",
                        "task_id": task_id
                    })
                
                return (
                    f"❤️ **Welcome to FoodRescue AI, {final_vol_name}!**\n\n"
                    f"You are registered as an active courier in **{final_vol_loc}** ({final_vol_veh}) and marked **AVAILABLE**.\n\n"
                    f"🚚 **Food Pickup Available!**\n\n"
                    f"• 🍱 **Food**: {food_info}\n"
                    f"• 📍 **Pickup**: {p_area}\n"
                    f"• 🏢 **Delivery**: {r_name} ({d_area})\n"
                    f"• 📏 **Distance**: ~{total_dist} km\n"
                    f"• 💰 **Estimated transport support**: LKR {int(est_cost)}\n\n"
                    f"*Reply **Accept** or **Reject***"
                )
            else:
                return (
                    f"🎉 **Great, {final_vol_name}! You are now marked as AVAILABLE.**\n\n"
                    f"You are registered in **{final_vol_loc}** with your **{final_vol_veh}**.\n\n"
                    f"📦 There are currently 0 pending pickups waiting in your area.\n"
                    f"As soon as a food donation is ready nearby, our AI coordinator will automatically send you a pickup offer right here on WhatsApp! 🚚"
                )

        # Progressive slot-filling:
        if not vol_name:
            if phone:
                database.set_user_conversation_state(phone, {
                    "workflow": "VOLUNTEER_REGISTRATION",
                    "expected_input_type": "VOL_NAME",
                    "current_question": "VOL_NAME"
                })
            return (
                "❤️ **Volunteer Courier Registration**\n\n"
                "Thank you for stepping up to rescue food in your community! 🚚\n\n"
                "1️⃣ What is your **full name**?"
            )
        elif not vol_vehicle:
            if phone:
                database.set_user_conversation_state(phone, {
                    "workflow": "VOLUNTEER_REGISTRATION",
                    "expected_input_type": "VOL_VEHICLE",
                    "current_question": "VOL_VEHICLE",
                    "vol_name": vol_name
                })
            return (
                f"Nice to meet you, **{vol_name}**! 🛵\n\n"
                "2️⃣ What **vehicle or transport mode** will you use for deliveries?\n"
                "(e.g. *Three-Wheeler*, *Motorbike*, *Car*, *Van*, *Bicycle*)"
            )
        else:
            if phone:
                database.set_user_conversation_state(phone, {
                    "workflow": "VOLUNTEER_REGISTRATION",
                    "expected_input_type": "VOL_CITY",
                    "current_question": "VOL_CITY",
                    "vol_name": vol_name,
                    "vol_vehicle": vol_vehicle
                })
            return (
                f"Got it! 📍 3️⃣ What **city, town, or service area** in Sri Lanka can you cover? (e.g. Mawanella, Colombo, Kandy, Galle)"
            )

    # 7. Recipient Organization Workflow ("2", "request food", "need food", "community organization", "shelter", "hope food")
    is_org_inventory_query = clean_p in ["view all", "view all available donations", "view available", "all donations", "view donations", "available donations", "surplus food", "inventory"]
    is_org_menu_opt = clean_p in ["2", "request food", "request available food", "need food", "food request", "community organization", "shelter"]
    is_org_intent = any(m in clean_p for m in [
        "community organization", "need food", "request food", "food bank", "shelter",
        "we need", "meals for", "packets for", "food for our", "for our shelter",
        "organization name:", "hope food home", "hope food", "charity", "feeding people"
    ])
    curr_state = database.get_user_conversation_state(phone) if phone else {}
    in_org_workflow = curr_state.get("workflow") == "RECIPIENT_REQUEST"

    if (is_org_inventory_query or is_org_menu_opt or is_org_intent or in_org_workflow) and not (clean_p in ["hi", "hello", "hey", "menu", "start"] and not in_org_workflow):
        existing_org = database.get_organization_by_phone(phone) if phone else None
        
        # 7a. User explicitly asked to view all available donations across the network
        if is_org_inventory_query and existing_org:
            all_dons = database.get_all_donations()
            active_dons = [d for d in all_dons if d.get("status") in ["AVAILABLE", "MATCHED", "PICKUP_PENDING", "PICKUP_ASSIGNED"]]
            if active_dons:
                lines = []
                for idx, don in enumerate(active_dons[:5], 1):
                    f_type = don.get("food_type", "Prepared Meals")
                    qty_d = don.get("quantity", 0)
                    unit_d = don.get("unit", "portions")
                    loc_d = don.get("pickup_location", "Sri Lanka")
                    lines.append(f"{idx}️⃣ **{qty_d} {unit_d} — {f_type}** (📍 {loc_d})")
                items_str = "\n".join(lines)
                return (
                    f"📦 **Available Surplus Food Donations Across Network:**\n\n"
                    f"{items_str}\n\n"
                    f"📍 Please share your organization's delivery location using WhatsApp (Tap ➕ → Location → Send your current location 📍) to reserve food!"
                )
            else:
                return (
                    "📦 **Current Surplus Inventory:**\n\n"
                    "There are currently 0 unassigned donations in the network.\n"
                    "We have logged your community request and our AI coordinator will automatically notify you the moment fresh food is posted in your area!"
                )

        # 7b. Entity extraction for multi-field messages or progressive slot answers
        org_name = (existing_org.get("name") if existing_org else None) or curr_state.get("org_name")
        org_loc = (existing_org.get("location") if existing_org else None) or curr_state.get("city")
        food_needed = curr_state.get("food_needed")

        # Extract Organization Name
        name_match = re.search(r"(?:organization\s*(?:name)?|name)\s*:\s*([^\n\r,]+)", prompt, re.IGNORECASE)
        if name_match:
            org_name = name_match.group(1).strip()
        elif "hope food home" in clean_p or "hope food" in clean_p:
            org_name = "Hope Food Home"
        elif curr_state.get("expected_input_type") == "ORG_NAME" and len(clean_p.split()) <= 6 and not is_org_intent:
            org_name = prompt.strip()

        # Extract Location / City
        loc_match = re.search(r"(?:location|city|district|area)\s*:\s*([^\n\r,]+)", prompt, re.IGNORECASE)
        if loc_match:
            org_loc = loc_match.group(1).strip()
        else:
            cities = ["mawanella", "kegalle", "colombo", "kandy", "galle", "matara", "negombo", "gampaha", "jaffna", "kurunegala", "anuradhapura", "batticaloa", "trincomalee", "ratnapura"]
            for c in cities:
                if c in clean_p:
                    org_loc = c.capitalize()
                    break
        if not org_loc and curr_state.get("expected_input_type") == "CITY" and len(clean_p.split()) <= 3:
            org_loc = prompt.strip()

        # Extract Food Need
        food_match = re.search(r"(?:we\s+need|need)\s*([^\n\r\.]+)", prompt, re.IGNORECASE)
        if food_match:
            food_needed = food_match.group(1).strip()
        elif curr_state.get("expected_input_type") == "FOOD_NEED":
            food_needed = prompt.strip()

        # If all details are present, register & match!
        if org_name and org_loc and (food_needed or curr_state.get("expected_input_type") == "FOOD_NEED" or is_org_intent):
            final_org_name = org_name or "Community Organization"
            final_org_loc = org_loc or "Mawanella"
            final_food = food_needed or "Meal packets"

            if phone:
                tools.register_organization(
                    name=final_org_name,
                    location=final_org_loc,
                    service_area=final_org_loc,
                    accepted_food_types=final_food,
                    phone=phone
                )
                database.update_user_profile(
                    phone=phone,
                    display_name=final_org_name,
                    user_role="organization",
                    default_location=final_org_loc
                )
            
            # Clear recipient conversation state on completion
            if phone:
                database.set_user_conversation_state(phone, {})

            # Search available matching donations in network
            all_dons = database.get_all_donations()
            active_dons = [d for d in all_dons if d.get("status") in ["AVAILABLE", "MATCHED", "PICKUP_PENDING", "PICKUP_ASSIGNED"]]
            
            # 1. Check local city matches
            local_matches = [d for d in active_dons if final_org_loc.lower() in d.get("pickup_location", "").lower() or d.get("pickup_location", "").lower() in final_org_loc.lower()]
            
            if local_matches:
                top_m = local_matches[0]
                m_qty = top_m.get("quantity", 30)
                m_unit = top_m.get("unit", "meal packets")
                m_food = top_m.get("food_type", "Rice & Curry")
                m_donor = top_m.get("donor_name", "Afnan Food House")
                m_dead = top_m.get("pickup_deadline", "Before 8 PM")
                return (
                    f"👋 Hello from **{final_org_name}**! I've successfully registered your organization in {final_org_loc}.\n\n"
                    f"🍱 **Great news! We found an available food match in {final_org_loc}:**\n"
                    f"• **{m_qty} {m_unit} — {m_food}** ({m_donor}, {final_org_loc})\n"
                    f"⏰ **Pickup deadline**: {m_dead}\n\n"
                    f"📍 **Please share your organization's exact WhatsApp delivery location pin:**\n"
                    f"Tap ➕ (or paperclip) → Location → 'Send your current location' 📍 so our volunteer courier can pick up and deliver the food to you!"
                )
            elif active_dons:
                lines = [f"• **{d.get('quantity')} {d.get('unit', 'packets')} — {d.get('food_type')}** (📍 {d.get('pickup_location')})" for d in active_dons[:3]]
                avail_str = "\n".join(lines)
                return (
                    f"👋 Hello from **{final_org_name}**! I've registered your organization in {final_org_loc}.\n\n"
                    f"📦 **Currently Available Surplus Donations in the Network:**\n"
                    f"{avail_str}\n\n"
                    f"🔍 We have noted your request for {final_food} in {final_org_loc}. As soon as a local donor in {final_org_loc} posts surplus food, our AI will alert you and dispatch a courier immediately!\n\n"
                    f"📍 Please share your organization's WhatsApp location pin 📍 so your delivery point is saved."
                )
            else:
                return (
                    f"👋 Hello from **{final_org_name}**! I've successfully registered your organization in {final_org_loc}.\n\n"
                    f"🔍 We have logged your request for {final_food} in {final_org_loc}. Our AI coordinator will immediately notify you and dispatch a courier the moment a donor posts surplus food in your area!\n\n"
                    f"📍 **Please share your organization's WhatsApp location pin 📍** so volunteer couriers can navigate directly to your delivery point."
                )

        # If details are missing, progressive slot-filling:
        if not org_name:
            if phone:
                database.set_user_conversation_state(phone, {
                    "workflow": "RECIPIENT_REQUEST",
                    "expected_input_type": "ORG_NAME",
                    "current_question": "ORG_NAME"
                })
            return translation_service.get_localized_message("org_ask_name", lang=lang)
        elif not org_loc:
            if phone:
                database.set_user_conversation_state(phone, {
                    "workflow": "RECIPIENT_REQUEST",
                    "expected_input_type": "CITY",
                    "current_question": "CITY",
                    "org_name": org_name
                })
            return translation_service.get_localized_message("org_ask_city", lang=lang, org_name=org_name)
        else:
            if phone:
                database.set_user_conversation_state(phone, {
                    "workflow": "RECIPIENT_REQUEST",
                    "expected_input_type": "FOOD_NEED",
                    "current_question": "FOOD_NEED",
                    "org_name": org_name,
                    "city": org_loc
                })
            return translation_service.get_localized_message("org_ask_food_need", lang=lang, org_name=org_name)

    # 8. Greetings & Main Menu
    if clean_p in ["hi", "hello", "hey", "menu", "help", "start", "6", "options", "මෙනුව", "ආයුබෝවන්", "வணக்கம்"]:
        if user and user.get("onboarding_completed"):
            donor_rec = database.get_donor_by_phone(phone) if phone else None
            if donor_rec:
                return translation_service.get_localized_message("returning_donor_welcome", lang=lang, name=donor_rec.get("name", ""))
            return translation_service.get_localized_message("returning_welcome", lang=lang)
        return translation_service.get_localized_message("onboarding_welcome", lang=lang)

    # =========================================================================
    # 9. DYNAMIC SLOT-FILLING & CONTEXT-AWARE DONATION WORKFLOW
    # =========================================================================
    curr_state = database.get_user_conversation_state(phone) if phone else {}
    expected_type = curr_state.get("expected_input_type", "")
    curr_q = curr_state.get("current_question", "")
    existing_draft = (database.get_draft_donation(phone) if phone else {}) or {}
    donor = database.get_donor_by_phone(phone) if phone else None
    user = database.get_user_by_phone(phone) if phone else None

    # 9a. Handle Confirmation Stage ("Confirm" / 1 -> commit donation)
    is_confirm_word = clean_p in [
        "1", "confirm", "yes", "y", "ok", "okay", "correct", "create", "confirm donation",
        "තහවුරුයි", "ඔව්", "உறுதி", "ஆம்"
    ] or clean_p == "confirm" or "confirm" in clean_p
    is_confirm_intent = is_confirm_word

    has_required_to_confirm = bool(
        existing_draft.get("food_type") and
        (existing_draft.get("city") or existing_draft.get("location"))
    )

    if (curr_q == "CONFIRMATION" or expected_type == "CONFIRMATION" or (is_confirm_intent and has_required_to_confirm)):
        if is_confirm_intent:
            # Commit donation from persistent draft
            qty = float(existing_draft.get("quantity") or 20.0)
            food = existing_draft.get("food_type") or "Prepared Meals"
            unit = existing_draft.get("unit") or "packets"
            dietary = existing_draft.get("dietary_info") or "Standard"
            city = existing_draft.get("city") or existing_draft.get("location") or (donor.get("location") if donor else None) or "Colombo"
            loc = existing_draft.get("address") or existing_draft.get("location") or city
            deadline = existing_draft.get("pickup_deadline") or "Today before 6 PM"
            donor_name = existing_draft.get("donor_name") or existing_draft.get("business_name") or (donor.get("name") if donor else None) or (user.get("display_name") if user and not user.get("display_name", "").startswith("User_") else "Donor Partner")
            business_name = existing_draft.get("business_name") or donor_name

            if phone:
                tools.register_donor(name=donor_name, location=city, phone=phone)

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

            # Match organization
            match_raw = tools.find_matching_organizations(food_type=food, location=city)
            match_res = json.loads(match_raw) if isinstance(match_raw, str) else {}
            org_id = "o1"
            org_name = "Community Organization"
            deliv_loc = "Colombo"
            if match_res.get("organizations"):
                top_org = match_res["organizations"][0]
                org_id = top_org.get("id", top_org.get("org_id", "o1"))
                org_name = top_org.get("name", "Community Organization")
                deliv_loc = top_org.get("location", "Colombo")
                if don_id:
                    tools.accept_donation(donation_id=don_id, organization_id=org_id)

            # Match volunteer & assign task
            vol_raw = tools.find_available_volunteers(location=city)
            vol_res = json.loads(vol_raw) if isinstance(vol_raw, str) else {}
            vol_id = "v1"
            vol_name = "Volunteer Courier"
            if vol_res.get("volunteers"):
                top_vol = vol_res["volunteers"][0]
                vol_id = top_vol.get("id", top_vol.get("volunteer_id", "v1"))
                vol_name = top_vol.get("name", "Volunteer Courier")

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
                donor_name=donor_name,
                donation_id=don_id,
                quantity=qty,
                unit=unit,
                food_type=food,
                city=city,
                deadline=deadline
            )

        elif clean_p in ["2", "edit", "change", "modify"]:
            return "📝 What details would you like to update? (You can say *'Actually 40 packets'*, *'Change city to Kandy'*, or *'Pickup time 7 PM'*)"
        elif clean_p in ["3", "cancel", "stop"]:
            if phone:
                database.clear_draft_donation(phone)
                database.clear_user_conversation_state(phone)
            return "🛑 Donation creation cancelled. Reply **menu** anytime to start again."

    # 9b. Context-Aware Input Resolution Based on Current Question
    if curr_q == "DONOR_NAME" or expected_type == "NAME":
        cand_name = prompt.strip()
        if _extract_location(cand_name) or any(c in cand_name.lower() for c in ["colombo", "kandy", "galle", "mawanella", "jaffna", "negombo", "dehiwala", "nugegoda"]):
            # User answered location instead of name
            loc_val = _extract_location(cand_name) or cand_name
            draft_update = {"city": loc_val, "location": loc_val}
            if not existing_draft.get("donor_name"):
                draft_update["donor_name"] = "Donor Partner"
                draft_update["business_name"] = "Donor Partner"
            if phone:
                existing_draft = database.save_draft_donation(phone, draft_update)
        else:
            is_name_candidate = (
                cand_name and
                cand_name.lower() not in ["hi", "hello", "1", "2", "3"] and
                not any(w in cand_name.lower() for w in ["actually", "have", "packet", "meals", "change", "curry", "rice", "bread"]) and
                not re.search(r'\d', cand_name)
            )
            if is_name_candidate:
                draft_update = {"donor_name": cand_name, "business_name": cand_name}
                if phone:
                    existing_draft = database.save_draft_donation(phone, draft_update)
                    database.create_or_update_user(phone=phone, display_name=cand_name)

    elif curr_q == "CITY" or expected_type == "CITY":
        extracted_city = _extract_location(prompt) or voice_service.extract_donation_entities(prompt).get("city")
        if extracted_city:
            draft_update = {"city": extracted_city, "location": extracted_city}
            if phone:
                existing_draft = database.save_draft_donation(phone, draft_update)
        elif len(prompt.strip().split()) <= 4 and not any(w in prompt.lower() for w in ["rice", "meal", "packet", "food", "have", "curry", "bread"]) and not re.search(r'\d', prompt):
            cand_city = prompt.strip()
            draft_update = {"city": cand_city, "location": cand_city}
            if phone:
                existing_draft = database.save_draft_donation(phone, draft_update)

    elif curr_q == "DEADLINE" or expected_type == "DEADLINE":
        deadline_match = re.search(r'(?:before|until|by|at)?\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)', prompt, re.IGNORECASE)
        time_val = deadline_match.group(1).strip().upper() if (deadline_match and deadline_match.group(1)) else prompt.strip()
        if "PM" not in time_val and "AM" not in time_val and re.match(r'^\d{1,2}$', time_val):
            time_val = f"Today before {time_val} PM"
        elif "before" in prompt.lower() and not time_val.lower().startswith("today"):
            time_val = f"Today before {time_val}"
        if phone:
            existing_draft = database.save_draft_donation(phone, {"pickup_deadline": time_val})

    elif curr_q == "FOOD_TYPE" or expected_type == "FOOD_CHOICE":
        opt_map = {
            "1": "Rice & Curry",
            "2": "Bread & Bakery",
            "3": "Vegetarian Meals",
            "4": "Biryani",
            "5": "Prepared Meals"
        }
        chosen_food = None
        if "1 and 3" in clean_p or "1 & 3" in clean_p or "1, 3" in clean_p or "1,3" in clean_p:
            chosen_food = "Rice & Vegetarian Meals"
        elif "1 and 2" in clean_p or "1 & 2" in clean_p:
            chosen_food = "Rice & Bread"
        elif clean_p in opt_map:
            chosen_food = opt_map[clean_p]
        elif "rice" in clean_p and "curry" in clean_p:
            chosen_food = "Rice & Curry"
        elif "rice" in clean_p:
            chosen_food = "Rice & Curry"
        elif "bread" in clean_p or "bakery" in clean_p:
            chosen_food = "Bread & Bakery"
        elif "biryani" in clean_p:
            chosen_food = "Biryani"
        else:
            chosen_food = prompt.strip().title()

        if chosen_food:
            draft_update = {"food_type": chosen_food}
            if phone:
                existing_draft = database.save_draft_donation(phone, draft_update)

    elif curr_q == "QUANTITY" or expected_type == "QUANTITY":
        m_num = re.search(r'\b(\d+(?:\.\d+)?)\b', prompt)
        if m_num:
            qty_val = float(m_num.group(1))
            draft_update = {"quantity": qty_val}
            m_unit = re.search(r'\b(packets?|meals?|boxes?|portions?|kg|plates?|servings?|පාර්සල්|පැකට්|பொதிகள்|பாக்கெட்டுகள்)\b', prompt, re.IGNORECASE)
            if m_unit:
                draft_update["unit"] = m_unit.group(1).lower()
            if phone:
                existing_draft = database.save_draft_donation(phone, draft_update)

    # 9c. General Entity Extraction on natural messages
    if curr_q not in ["LANGUAGE_MENU"] and not prompt.strip().isdigit() and prompt.strip() not in ["1", "2", "3", "4", "5", "6"]:
        entities = voice_service.extract_donation_entities(prompt)
        draft_patch = {}
        is_correction = any(w in clean_p for w in ["actually", "change", "instead", "not", "correct", "update", "rather"])

        if entities.get("food_type") and (not existing_draft.get("food_type") or is_correction):
            draft_patch["food_type"] = entities["food_type"]
        if entities.get("quantity") is not None and (not existing_draft.get("quantity") or is_correction or "have" in clean_p):
            draft_patch["quantity"] = entities["quantity"]
            if entities.get("unit"):
                draft_patch["unit"] = entities["unit"]
        if entities.get("city") and (not existing_draft.get("city") or is_correction or "city" in clean_p or "location" in clean_p or "pickup" in clean_p or "in " in clean_p or "at " in clean_p):
            draft_patch["city"] = entities["city"]
            draft_patch["location"] = entities["city"]
        if entities.get("pickup_deadline") and (not existing_draft.get("pickup_deadline") or is_correction or "time" in clean_p or "deadline" in clean_p or "before" in clean_p or "until" in clean_p):
            draft_patch["pickup_deadline"] = entities["pickup_deadline"]
        if entities.get("donor_name") and (not existing_draft.get("donor_name") or is_correction or "name is" in clean_p):
            draft_patch["donor_name"] = entities["donor_name"]
            draft_patch["business_name"] = entities["donor_name"]
        if entities.get("dietary_info") and entities["dietary_info"] != "Standard":
            draft_patch["dietary_info"] = entities["dietary_info"]

        if draft_patch and phone:
            existing_draft = database.save_draft_donation(phone, draft_patch)
            loc_reg = draft_patch.get("city") or existing_draft.get("city")
            if loc_reg:
                tools.register_donor(
                    name=draft_patch.get("donor_name") or existing_draft.get("donor_name") or (user.get("display_name") if user else "Donor Partner"),
                    location=loc_reg,
                    phone=phone
                )

    # 9d. If User Pressed "1" or says "I want to donate" with no draft yet, prompt for food:
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
        return translation_service.get_localized_message("donation_ask_food_type", lang=lang)

    # 9e. Persistent State Resolution & Strict Ordering for Missing Slots
    food_val = existing_draft.get("food_type")
    qty_val = existing_draft.get("quantity")
    unit_val = existing_draft.get("unit", "packets")
    donor_name_val = existing_draft.get("donor_name") or (donor.get("name") if donor else None) or (user.get("display_name") if user and not user.get("display_name", "").startswith("User_") else None)
    business_name_val = existing_draft.get("business_name") or donor_name_val
    city_val = (
        existing_draft.get("city")
        or existing_draft.get("location")
        or (donor.get("location") if donor else None)
        or (user.get("default_location") if user else None)
        or (user.get("location") if user else None)
        or (user.get("city") if user else None)
    )
    deadline_val = existing_draft.get("pickup_deadline")
    loc_received = bool(existing_draft.get("location_received") or existing_draft.get("latitude"))

    # If all other slots (food, qty, city, deadline) were provided all-in-one, default donor name
    if not donor_name_val and (city_val and deadline_val):
        donor_name_val = "Donor Partner"
        business_name_val = "Donor Partner"

    # Step 1: Missing Food Type or Quantity
    if not food_val:
        if phone:
            database.set_user_conversation_state(phone, {
                "workflow": "DONATION",
                "current_question": "FOOD_TYPE",
                "expected_input_type": "FOOD_CHOICE"
            })
        return translation_service.get_localized_message("donation_ask_food_type_simple", lang=lang)

    if qty_val is None or float(qty_val) <= 0:
        if phone:
            database.set_user_conversation_state(phone, {
                "workflow": "DONATION",
                "current_question": "QUANTITY",
                "expected_input_type": "QUANTITY"
            })
        return translation_service.get_localized_message("slot_ask_quantity", lang=lang, food_type=food_val)

    # Step 2: Missing Donor Name / Business Name
    if not donor_name_val:
        if phone:
            database.set_user_conversation_state(phone, {
                "workflow": "DONATION",
                "current_question": "DONOR_NAME",
                "expected_input_type": "NAME"
            })
        return translation_service.get_localized_message("donor_ask_name", lang=lang, quantity=qty_val, unit=unit_val, food_type=food_val)

    # Step 3: Missing City / Area
    if not city_val:
        if phone:
            database.set_user_conversation_state(phone, {
                "workflow": "DONATION",
                "current_question": "CITY",
                "expected_input_type": "CITY"
            })
        return translation_service.get_localized_message("donor_ask_city", lang=lang, name=donor_name_val, quantity=qty_val, unit=unit_val, food_type=food_val)

    # Step 4: Missing Pickup Deadline
    if not deadline_val:
        if phone:
            database.set_user_conversation_state(phone, {
                "workflow": "DONATION",
                "current_question": "DEADLINE",
                "expected_input_type": "DEADLINE"
            })
        return translation_service.get_localized_message("donor_ask_deadline", lang=lang, city=city_val)

    # Step 5: Missing Exact WhatsApp Location (Ask as native standalone instruction)
    if not loc_received and not existing_draft.get("location"):
        if phone:
            database.set_user_conversation_state(phone, {
                "workflow": "DONATION",
                "current_question": "WHATSAPP_LOCATION",
                "expected_input_type": "LOCATION"
            })
        return translation_service.get_localized_message("donor_ask_location_native", lang=lang)

    # Step 6: All fields present -> Show Summary Confirmation!
    if phone:
        database.set_user_conversation_state(phone, {
            "workflow": "DONATION",
            "current_question": "CONFIRMATION",
            "expected_input_type": "CONFIRMATION"
        })

    return translation_service.get_localized_message(
        "donation_summary_confirm",
        lang=lang,
        donor_name=donor_name_val,
        business_name=business_name_val,
        food_type=food_val,
        quantity=qty_val,
        unit=unit_val,
        city=city_val,
        deadline=deadline_val,
        contact_phone=phone
    )


async def run_resilient_chat(
    prompt: str,
    session_id: str,
    preferred_agent: Optional[str] = None
) -> Dict[str, Any]:
    """Execute chat request through stateful coordinator engine and resilient LLM model pool."""
    phone = session_id.split("whatsapp:", 1)[1] if "whatsapp:" in session_id else ""
    clean_p = prompt.strip().lower()

    # Check if there is an active workflow, draft, or domain intent
    active_draft = database.get_draft_donation(phone) if phone else None
    conv_state = database.get_user_conversation_state(phone) if phone else {}
    has_active_state = bool(
        (active_draft and active_draft.get("food_type")) or
        conv_state.get("workflow") in ["DONATION", "VOLUNTEER", "RECIPIENT", "LANGUAGE"]
    )

    is_domain_intent = any(w in clean_p for w in [
        "donate", "food", "packet", "meals", "rice", "curry", "bread", "biryani",
        "volunteer", "courier", "free now", "i can help", "accept", "reject", "collected", "delivered",
        "need food", "request food", "organization", "shelter", "community",
        "confirm", "cancel", "status", "pickup", "where is", "track",
        "language", "භාෂාව", "மொழி", "english", "sinhala", "tamil", "සිංහල", "தமிழ்",
        "actually", "change", "before", "until", "pm", "am", "mawanella", "colombo", "kandy", "galle",
        "name is", "my name", "hope food", "kamal", "three-wheeler", "three wheeler", "three wheeler", "motorbike", "car"
    ]) or clean_p in ["1", "2", "3", "4", "5", "6", "yes", "no", "ok", "confirm", "accept", "reject", "collected", "delivered"] or len(clean_p.split()) <= 4

    if has_active_state or is_domain_intent:
        logger.info(f"[Stateful Engine] Executing stateful coordinator for session '{session_id}' with prompt: '{prompt[:60]}'")
        fallback_result = await execute_deterministic_fallback(prompt, session_id)
        return {
            "status": "success",
            "result": fallback_result,
            "agent_used": "foodrescue_coordinator",
            "model_used": "stateful_coordinator_engine",
            "session_id": session_id,
        }

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

            # If user has a preferred language that is not English, translate the reply
            user = database.get_user_by_phone(phone) if phone else None
            user_lang = user.get("preferred_language", "en") if user else "en"
            if user_lang != "en":
                reply_text = translation_service.translate_message_if_needed(reply_text, target_lang=user_lang)

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
