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
import qr_service

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
    return any(
        marker in err_str
        for marker in [
            "429",
            "resource_exhausted",
            "too many requests",
            "quota exceeded",
            "ratelimit",
            "rate limit",
            "retryin",
            "exhausted",
        ]
    )


def _extract_quantity(text: str) -> float:
    """Extract numeric quantity from user prompt."""
    match = re.search(r"\b(\d+(?:\.\d+)?)\b", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 30.0


def _extract_location(text: str) -> Optional[str]:
    """Extract location from text or None if not found."""
    loc_match = re.search(
        r"\b(Colombo(?:\s*(?:0?[1-9]|1[0-5]))?|Kandy|Galle|Dehiwala|Nugegoda|Mount Lavinia|Rajagiriya|Bambalapitiya|Kollupitiya|Fort|Cinnamon Gardens|Wellawatte|Battaramulla|Negombo|Mawanella|Kurunegala|Jaffna|Matara)\b",
        text,
        re.IGNORECASE,
    )
    if loc_match:
        return loc_match.group(1).strip()
    return None


def _extract_food_type(text: str) -> str:
    """Extract food type description from text, preserving user input."""
    text_clean = text.strip()
    if not text_clean:
        return "Surplus Food"
    if "rice & curry" in text_clean.lower() or "rice and curry" in text_clean.lower():
        return "Rice & Curry"
    if "fried rice" in text_clean.lower():
        return "Fried Rice"
    if "biryani" in text_clean.lower():
        return "Biryani"
    if "kottu" in text_clean.lower():
        return "Kottu Roti"
    if "bread" in text_clean.lower() or "bakery" in text_clean.lower():
        return "Bakery Items"
    if "fruit" in text_clean.lower() or "vegetable" in text_clean.lower() or "produce" in text_clean.lower():
        return "Fresh Produce"
    if "rice" in text_clean.lower() or text_clean.lower() in ["බත්", "சோறு", "சாதம்"]:
        return "Rice"
    if "meal" in text_clean.lower():
        return "Prepared Meals"
    return text_clean.title() if len(text_clean.split()) <= 4 else "Surplus Food Packages"


def _format_food_info(don: Optional[Dict[str, Any]]) -> str:
    """Format food info string preserving exact food type, quantity, and unit without hardcoded defaults."""
    if not don:
        return "Surplus Food"
    raw_qty = don.get("quantity")
    if raw_qty is not None:
        disp_qty = int(raw_qty) if isinstance(raw_qty, (int, float)) and raw_qty == int(raw_qty) else raw_qty
    else:
        disp_qty = 20
    unit = don.get("unit") or "portions"
    food = don.get("food_type") or "Prepared Meals"
    return f"{disp_qty} {unit} of {food}"



def _calculate_dynamic_task_metrics(
    task: Dict[str, Any], vol_record: Optional[Dict[str, Any]] = None
) -> Tuple[float, float, str, str, str, str, str]:
    """Calculate real road distance, transport cost, donor, and recipient info dynamically."""
    m = _get_task_extended_metrics(task, vol_record)
    return m["total_dist"], float(m["est_cost"]), m["donor_name"], m["donor_contact"], m["recipient_name"], m["pickup_location"], m["delivery_location"]


def _get_task_extended_metrics(
    task: Dict[str, Any], vol_record: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Calculate complete dynamic task metrics including map links, distances, and contact info."""
    don_id = task.get("donation_id", "")
    don = database.get_donation_record(don_id) if don_id else None

    donor_id = don.get("donor_id", "") if don else ""
    donor = database.get_donor_record(donor_id) if donor_id else None
    donor_name = donor.get("name") if donor else (don.get("donor_name") if don else "Donor Partner")
    donor_contact = donor.get("phone") if donor else (don.get("donor_phone") if don else "")

    org_id = task.get("organization_id", "")
    org = database.get_organization_record(org_id) if org_id else None
    recipient_name = org.get("name") if org else "Recipient Organization"
    recipient_contact = org.get("phone") if org else ""
    org_capacity = org.get("capacity") if org else "As needed"

    p_loc = task.get("pickup_location") or (don.get("pickup_location") if don else "Pickup Location")
    d_loc = task.get("delivery_location") or (org.get("location") if org else "Delivery Location")

    vol_mode = vol_record.get("transport_mode", "Motorbike") if vol_record else "Motorbike"
    vol_loc = vol_record.get("current_location") or vol_record.get("location") or vol_record.get("service_area") if vol_record else None

    # 1. Lookup Pickup Coordinates (Check stored database GPS location first)
    p_coords = None
    if don_id:
        try:
            don_locs = database.get_locations_for_donation(don_id)
            if don_locs:
                p_coords = (float(don_locs[0]["latitude"]), float(don_locs[0]["longitude"]))
        except Exception:
            pass
    if not p_coords and don:
        if don.get("latitude") and don.get("longitude"):
            try:
                p_coords = (float(don["latitude"]), float(don["longitude"]))
            except (ValueError, TypeError):
                pass
        elif don.get("location_pin"):
            p_coords = routing.extract_coordinates_from_text(str(don["location_pin"]))
    if not p_coords:
        p_coords = routing.geocode_location(p_loc)

    # 2. Lookup Delivery Coordinates (Check stored database GPS location first)
    d_coords = None
    if org_id:
        try:
            org_locs = database.get_locations_for_organization(org_id)
            if org_locs:
                d_coords = (float(org_locs[0]["latitude"]), float(org_locs[0]["longitude"]))
        except Exception:
            pass
    if not d_coords and org:
        if org.get("latitude") and org.get("longitude"):
            try:
                d_coords = (float(org["latitude"]), float(org["longitude"]))
            except (ValueError, TypeError):
                pass
        elif org.get("location_pin"):
            d_coords = routing.extract_coordinates_from_text(str(org["location_pin"]))
    if not d_coords:
        d_coords = routing.geocode_location(d_loc)

    # 3. Lookup Volunteer Coordinates
    v_coords = None
    if vol_record:
        vol_id = vol_record.get("id") or vol_record.get("volunteer_id")
        if vol_id:
            try:
                vol_locs = database.get_locations_for_volunteer(vol_id)
                if vol_locs:
                    v_coords = (float(vol_locs[0]["latitude"]), float(vol_locs[0]["longitude"]))
            except Exception:
                pass
        if not v_coords:
            if vol_record.get("latitude") and vol_record.get("longitude"):
                try:
                    v_coords = (float(vol_record["latitude"]), float(vol_record["longitude"]))
                except (ValueError, TypeError):
                    pass
    if not v_coords and vol_loc:
        v_coords = routing.geocode_location(vol_loc)

    # 4. Dynamic Distance Calculation
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

    if p_coords and d_coords:
        directions_link = routing.generate_directions_link(p_coords[0], p_coords[1], d_coords[0], d_coords[1])
    else:
        directions_link = routing.generate_directions_link(p_loc, d_loc)

    p_map = routing.generate_map_link(p_coords[0], p_coords[1]) if p_coords else routing.generate_map_link(p_loc)
    d_map = routing.generate_map_link(d_coords[0], d_coords[1]) if d_coords else routing.generate_map_link(d_loc)
    food_info = _format_food_info(don)
    deadline = (don.get("pickup_deadline") if don else None) or (task.get("scheduled_time") if task else None) or "Immediate"

    return {
        "total_dist": total_dist,
        "est_cost": int(est_cost),
        "donor_name": donor_name,
        "donor_contact": donor_contact,
        "recipient_name": recipient_name,
        "recipient_contact": recipient_contact,
        "org_capacity": org_capacity,
        "pickup_location": p_loc,
        "delivery_location": d_loc,
        "pickup_map": p_map,
        "delivery_map": d_map,
        "directions_link": directions_link,
        "food_info": food_info,
        "deadline": deadline,
    }


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
            database.set_user_conversation_state(
                phone,
                {
                    "workflow": "LANGUAGE",
                    "current_question": "LANGUAGE_MENU",
                    "expected_input_type": "CHOICE",
                    "available_options": {"6": "en", "7": "si", "8": "ta"},
                },
            )
        return (
            "🌍 *FoodRescue AI Language Selection / භාෂාව තෝරන්න / மொழியைத் தேர்ந்தெடுக்கவும்*:\n\n"
            "Reply with:\n"
            "6️⃣ English\n"
            "7️⃣ Sinhala (සිංහල)\n"
            "8️⃣ Tamil (தமிழ்)"
        )

    # 4. Status Queries (Donation / Pickup)
    if clean_p in [
        "4",
        "where is my donation?",
        "where is my donation",
        "show my donation",
        "what is my donation status?",
        "what is my donation status",
        "check my donation",
        "track my food",
    ]:
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
                task_info=task_info,
            )
        return translation_service.get_localized_message("donation_status_empty", lang=lang)

    if clean_p in [
        "5",
        "show my pickup",
        "where is the pickup?",
        "where is the pickup",
        "where is the volunteer?",
        "where is the volunteer",
        "where is the food?",
        "where is the food",
        "what is my pickup?",
        "what is my pickup",
        "pickup status",
    ]:
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
                volunteer_name=vol_name,
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
                return translation_service.get_localized_message("donation_cancelled_success", lang=lang, donation_id=don_id)
        return translation_service.get_localized_message("donation_cancelled_draft_success", lang=lang)

    # =========================================================================
    # 5.5 GREETINGS & MAIN MENU (Early dispatch when not in active workflow)
    # =========================================================================
    curr_state = database.get_user_conversation_state(phone) if phone else {}
    in_active_workflow = bool(curr_state.get("workflow"))
    is_greeting_word = translation_service.is_greeting_message(clean_p)
    vol_rec = database.get_volunteer_by_phone(phone) if phone else None
    org_rec = database.get_organization_by_phone(phone) if phone else None
    donor_rec = database.get_donor_by_phone(phone) if phone else None

    # Handle volunteer availability declaration ("AVAILABLE", "I am free", "ready", "online", "BUSY")
    is_avail_intent = (
        clean_p in ["available", "yes", "ready", "i am free", "i'm free", "im free", "available now", "ready to deliver", "ready for pickups", "online", "free", "active"]
        or any(w in clean_p for w in ["i am free", "i'm free", "im free", "available now", "ready to deliver", "ready for pickups", "mark as available", "mark me available"])
    )
    is_busy_intent = clean_p in ["busy", "not available", "offline", "take a break", "break"] or any(w in clean_p for w in ["i am busy", "not available now", "offline now"])

    if (is_avail_intent or is_busy_intent) and (vol_rec or (user and user.get("user_role") == "volunteer")):
        v_name = (vol_rec.get("name") if vol_rec else None) or (user.get("display_name") if user else "Volunteer")
        s_area = (vol_rec.get("service_area") if vol_rec else None) or (user.get("default_location") if user else "Kegalle")
        clean_dist = routing.resolve_district(s_area) or "Kegalle"

        if is_busy_intent:
            if vol_rec and vol_rec.get("id"):
                database.update_volunteer_record(vol_rec["id"], current_status="BUSY")
            if phone:
                database.clear_user_conversation_state(phone)
            return (
                f"⏸️ **Status Updated: BUSY / OFFLINE**\n\n"
                f"Hi {v_name}! You have been marked as **BUSY** in **{clean_dist}**.\n"
                f"We won't send you pickup notifications while you're taking a break.\n"
                f"Reply *AVAILABLE* anytime you are ready to deliver again! 🚚"
            )

        # Mark AVAILABLE
        if vol_rec and vol_rec.get("id"):
            database.update_volunteer_record(vol_rec["id"], current_status="AVAILABLE")

        pending = database.get_all_pickup_tasks()
        available_tasks = [t for t in pending if t.get("status") in ["PENDING", "OFFERED", "OPEN"]]
        dist_tasks = [t for t in available_tasks if routing.resolve_district(str(t.get("pickup_location", ""))) == clean_dist]
        candidate_tasks = dist_tasks or available_tasks
        if candidate_tasks:
            top_task = candidate_tasks[0]
            task_id = top_task["id"]
            don_id = top_task.get("donation_id", "")
            don = database.get_donation_record(don_id) if don_id else None
            food_info = f"{don.get('quantity', 30)} {don.get('unit', 'portions')} of {don.get('food_type', 'Prepared Meals')}" if don else "Food Donation"
            total_dist, est_cost, d_name, d_contact, r_name, p_area, d_area = _calculate_dynamic_task_metrics(top_task, vol_rec)
            if phone:
                database.set_user_conversation_state(
                    phone, {"workflow": "VOLUNTEER", "current_question": "ACCEPT_TASK", "expected_input_type": "CHOICE", "task_id": task_id}
                )
            return (
                f"📍 *Status Updated: AVAILABLE* 🟢\n\n"
                f"🚚 **Food Pickup Opportunity in {clean_dist}!**\n\n"
                f"• 🆔 **Task ID**: `{task_id}`\n"
                f"• 🍱 **Food**: {food_info}\n"
                f"• 📍 **Pickup**: {p_area}\n"
                f"• 🏢 **Delivery**: {r_name} ({d_area})\n"
                f"• 📏 **Distance**: ~{total_dist} km\n"
                f"• 💰 **Estimated transport support**: LKR {int(est_cost)}\n\n"
                f"*Reply **Accept** or **Reject***"
            )
        else:
            return translation_service.get_localized_message(
                "volunteer_status_updated_available",
                lang=lang,
                volunteer_name=v_name,
                service_area=clean_dist,
                pending_count=0
            )


    if is_greeting_word and not in_active_workflow:
        if vol_rec or (user and user.get("user_role") == "volunteer"):
            name = vol_rec.get("name", "Volunteer") if vol_rec else "Volunteer"
            s_area = vol_rec.get("service_area", "Sri Lanka") if vol_rec else "Sri Lanka"
            return (
                f"🚚 *Welcome back, {name}!* (Volunteer Courier — {s_area})\n\n"
                f"Reply with:\n"
                f"1️⃣ Search active pickups in {s_area}\n"
                f"2️⃣ Check my active delivery status\n"
                f"3️⃣ Mark myself as free / update location\n"
                f"4️⃣ Change language (භාෂාව / மொழி)\n\n"
                f"*Or ask any question about your volunteer tasks!*"
            )
        elif org_rec or (user and user.get("user_role") == "organization"):
            name = org_rec.get("name", "Organization") if org_rec else "Organization"
            area = org_rec.get("location", org_rec.get("city", "Sri Lanka")) if org_rec else "Sri Lanka"
            return (
                f"🏢 *Welcome back, {name}!* (Recipient Organization — {area})\n\n"
                f"Reply with:\n"
                f"1️⃣ Request surplus food donation\n"
                f"2️⃣ Track incoming food deliveries\n"
                f"3️⃣ Update daily portion capacity\n"
                f"4️⃣ Change language (භාෂාව / மொழி)\n\n"
                f"*Or ask any question about available food donations!*"
            )
        elif donor_rec or (user and user.get("user_role") == "donor"):
            name = donor_rec.get("name", "Donor") if donor_rec else "Donor"
            return (
                f"🍲 *Welcome back, {name}!* (Food Donor Partner)\n\n"
                f"Reply with:\n"
                f"1️⃣ Donate surplus food\n"
                f"2️⃣ Track my active donation\n"
                f"3️⃣ View past donations & meals rescued\n"
                f"4️⃣ Change language (භාෂාව / மொழி)\n\n"
                f"*Or tell me what food you have available to donate!*"
            )
        elif user and user.get("onboarding_completed"):
            return translation_service.get_localized_message("returning_welcome", lang=lang)
        return translation_service.get_localized_message("onboarding_welcome", lang=lang)

    # =========================================================================
    # 5.6 ROLE-AWARE CONTEXTUAL QUESTIONS
    # =========================================================================
    vol_rec = database.get_volunteer_by_phone(phone) if phone else None
    org_rec = database.get_organization_by_phone(phone) if phone else None
    donor_rec = database.get_donor_by_phone(phone) if phone else None

    is_food_or_task_query = any(
        w in clean_p
        for w in [
            "any food",
            "any foods",
            "what food",
            "what foods",
            "available food",
            "available foods",
            "food available",
            "foods available",
            "food do you have",
            "foods do you have",
            "food you have",
            "any pickup",
            "any pickups",
            "pickups available",
            "pickup available",
            "tasks available",
            "what tasks",
            "any tasks",
            "task available",
            "surplus food",
            "surplus available",
            "do you have food",
            "have food",
            "food near me",
            "pickups near me",
        ]
    )

    if is_food_or_task_query and not in_active_workflow:
        # A. Registered Volunteer asking for tasks/foods
        if vol_rec or (user and user.get("user_role") == "volunteer"):
            pending = database.get_all_pickup_tasks()
            available_tasks = [t for t in pending if t.get("status") in ["PENDING", "OFFERED", "OPEN"]]
            if available_tasks:
                top_task = available_tasks[0]
                task_id = top_task["id"]
                don_id = top_task.get("donation_id", "")
                don = database.get_donation_record(don_id) if don_id else None
                food_info = _format_food_info(don)
                total_dist, est_cost, d_name, d_contact, r_name, p_area, d_area = _calculate_dynamic_task_metrics(top_task, vol_rec)

                tools.set_session_context(key="current_task_id", value=task_id)
                if vol_rec:
                    tools.set_session_context(key="current_volunteer_id", value=vol_rec["id"])
                if phone:
                    database.set_user_conversation_state(
                        phone, {"workflow": "VOLUNTEER", "current_question": "ACCEPT_TASK", "expected_input_type": "CHOICE", "task_id": task_id}
                    )
                return (
                    f"🚚 **Food Pickup Opportunity Available!**\n\n"
                    f"• 🆔 **Task ID**: `{task_id}`\n"
                    f"• 🍱 **Food**: {food_info}\n"
                    f"• 📍 **Pickup**: {p_area}\n"
                    f"• 🏢 **Delivery**: {r_name} ({d_area})\n"
                    f"• 📏 **Distance**: ~{total_dist} km\n"
                    f"• 💰 **Estimated transport support**: LKR {int(est_cost)}\n\n"
                    f"*Reply **Accept** or **Reject***"
                )
            else:
                s_area = vol_rec.get("service_area", "your district") if vol_rec else "your district"
                return (
                    f"📦 **Volunteer Status**: You are registered in **{s_area}** and marked **AVAILABLE**.\n\n"
                    f"There are currently 0 unassigned pickups waiting in your area.\n"
                    f"As soon as a donation is posted nearby, our coordinator will immediately dispatch a WhatsApp offer to you! 🚚"
                )

        # B. Registered Recipient Organization asking for food
        elif org_rec or (user and user.get("user_role") == "organization"):
            all_dons = database.get_all_donations()
            active_dons = [d for d in all_dons if d.get("status") in ["AVAILABLE", "MATCHED", "PICKUP_PENDING"]]
            if active_dons:
                lines = []
                for idx, don in enumerate(active_dons[:5], 1):
                    lines.append(
                        f"{idx}️⃣ **{don.get('quantity', 0)} {don.get('unit', 'portions')} — {don.get('food_type', 'Prepared Meals')}** (📍 {don.get('pickup_location', 'Sri Lanka')})"
                    )
                items_str = "\n".join(lines)
                return (
                    f"🍱 **Available Food Donations in Network:**\n\n"
                    f"{items_str}\n\n"
                    f"📍 Please share your organization's delivery location (Tap ➕ → Location → Send your current location 📍) to reserve food!"
                )
            else:
                return (
                    "📦 **Surplus Food Inventory:**\n\n"
                    "There are currently 0 unassigned donations available right now.\n"
                    "We have your organization on our priority list and will alert you the moment fresh food is donated in your district! 🍱"
                )

        # C. Registered Donor asking for status/food
        elif donor_rec or (user and user.get("user_role") == "donor"):
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
                    task_info=task_info,
                )
            return (
                "👋 As a food donor, you can donate prepared meals, bakery items, or groceries to feed local shelters!\n\n"
                "Reply **1** to start donating food, or reply **menu** to see all options."
            )

        # D. First-time or Unregistered user asking "what food do you have available?"
        else:
            return (
                "🍱 **Welcome to FoodRescue AI!**\n\n"
                "FoodRescue AI connects surplus food donors (hotels, bakeries, restaurants) with shelters and charities across Sri Lanka.\n\n"
                "Available food types typically include:\n"
                "• 🍚 Fresh Rice & Curry Packets\n"
                "• 🍞 Bakery Items & Bread\n"
                "• 🥗 Vegetarian & Prepared Meals\n"
                "• 🍲 Biryani & Cooked Food\n\n"
                "How would you like to participate?\n"
                "1️⃣ *Donate Food* (Share surplus meals)\n"
                "2️⃣ *Request Food* (For shelters and charities)\n"
                "3️⃣ *Volunteer Courier* (Deliver food and earn travel support)\n\n"
                "Reply with a number (1-3) to begin!"
            )

    # =========================================================================
    # 6. VOLUNTEER COURIER COORDINATION & PROGRESSIVE ONBOARDING
    # =========================================================================
    in_vol_workflow = curr_state.get("workflow") in ["VOLUNTEER", "VOLUNTEER_REGISTRATION"]
    existing_vol = database.get_volunteer_by_phone(phone) if phone else None

    # 6a. Option 1 / View Available Tasks for Volunteer
    is_vol_view_tasks = clean_p in ["1", "view available tasks", "view tasks", "available tasks", "pending tasks", "check tasks"] and (
        existing_vol or in_vol_workflow
    )
    if is_vol_view_tasks:
        pending = database.get_all_pickup_tasks()
        available_tasks = [t for t in pending if t.get("status") in ["PENDING", "OFFERED", "OPEN"]]
        if available_tasks:
            top_task = available_tasks[0]
            task_id = top_task["id"]
            don_id = top_task.get("donation_id", "")
            don = database.get_donation_record(don_id) if don_id else None
            food_info = _format_food_info(don)

            vol_rec = existing_vol or (database.get_volunteer_by_phone(phone) if phone else None)
            total_dist, est_cost, d_name, d_contact, r_name, p_area, d_area = _calculate_dynamic_task_metrics(top_task, vol_rec)

            tools.set_session_context(key="current_task_id", value=task_id)
            if existing_vol:
                tools.set_session_context(key="current_volunteer_id", value=existing_vol["id"])
            if phone:
                database.set_user_conversation_state(
                    phone, {"workflow": "VOLUNTEER", "current_question": "ACCEPT_TASK", "expected_input_type": "CHOICE", "task_id": task_id}
                )

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

    user_state = database.get_user_conversation_state(phone) if phone else {}
    is_donor_accepting_org = bool(user_state.get("current_question") == "ACCEPT_ORGANIZATION")

    # 6b. Volunteer Accept / Reject Task
    if not is_donor_accepting_org and any(
        m in clean_p
        for m in [
            "accept",
            "i'll take it",
            "ill take it",
            "take it",
            "i can do it",
            "accept task",
            "take pickup",
            "claim",
            "භාරගන්නවා",
            "ඔව්",
            "ஏற்கிறேன்",
            "ஆம்",
            "ஏற்றுக்கொள்கிறேன்",
            "பணியை ஏற்கிறேன்",
        ]
    ):
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

            task_rec = database.get_pickup_task_record(task_id) or {"id": task_id}
            ext = _get_task_extended_metrics(task_rec, existing_vol or (database.get_volunteer_by_phone(phone) if phone else None))

            # Generate or retrieve active Pickup QR Code for this task
            task_qrs = database.get_qr_codes_for_task(task_id)
            pk_qr = next((q for q in task_qrs if q.get("qr_type") == "PICKUP" and q.get("status") == "ACTIVE"), None)
            if not pk_qr:
                pk_token = qr_service.generate_secure_token("PK")
                pk_qr = database.create_qr_code_record(
                    qr_id=f"qr-pk-{task_id}",
                    task_id=task_id,
                    donation_id=task_rec.get("donation_id") or "don-unknown",
                    qr_type="PICKUP",
                    token=pk_token,
                    token_hash=qr_service.hash_token(pk_token),
                    donor_id=task_rec.get("donor_id"),
                    organization_id=task_rec.get("organization_id"),
                    assigned_volunteer_id=vol_id or (existing_vol.get("id") if existing_vol else None),
                    status="ACTIVE",
                )
            pk_token = pk_qr.get("token")
            verif_url = qr_service.build_verification_url("PICKUP", pk_token)
            scanner_url = qr_service.build_scanner_url("PICKUP", task_id=task_id)
            qr_img_url = f"{qr_service.get_base_url()}/api/qr/{pk_token}.png"

            return translation_service.get_localized_message(
                "volunteer_task_assigned_full_details",
                lang=lang,
                task_id=task_id,
                donor_name=ext["donor_name"],
                donor_phone=ext["donor_contact"] or "Provided upon arrival",
                pickup_location=ext["pickup_location"],
                food_info=ext["food_info"],
                deadline=ext["deadline"],
                donor_map_link=ext["pickup_map"] or "https://maps.google.com",
                org_name=ext["recipient_name"],
                org_phone=ext["recipient_contact"] or "Provided upon arrival",
                delivery_location=ext["delivery_location"],
                org_capacity=ext["org_capacity"],
                org_map_link=ext["delivery_map"] or "https://maps.google.com",
                total_dist=ext["total_dist"],
                est_cost=ext["est_cost"],
                directions_link=ext["directions_link"] or ext["delivery_map"] or "https://maps.google.com",
                qr_img_link=qr_img_url,
                verification_url=verif_url,
                scanner_url=scanner_url,
            )
        return "No pending pickup task is currently selected. Reply **3** to see available volunteer opportunities."

    if clean_p in ["reject", "can't do it", "cant do it", "no", "decline", "බැහැ", "නැහැ", "மறுக்கிறேன்", "இல்லை"]:
        user_conv = database.get_user_conversation_state(phone) if phone else {}
        if user_conv.get("current_question") == "ACCEPT_ORGANIZATION":
            if phone:
                database.clear_user_conversation_state(phone)
            return "👍 No problem! Your food donation remains active, and we will match you with another organization in your district."
        task_id = tools._get_context_val("current_task_id", "") or user_conv.get("task_id", "")
        if task_id:
            tools.reject_pickup_task(pickup_task_id=task_id)
            if phone:
                database.clear_user_conversation_state(phone)
            return "👍 No problem! We will offer this task to another available volunteer courier. Thank you!"
        return "No active pickup offer was found. Reply **menu** to see options."

    # 6c. Collection Confirmation ("Collected")
    if any(
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
    ):
        task_id = tools._get_context_val("current_task_id", "")
        if not task_id and phone:
            my_picks_raw = tools.get_my_pickups(phone=phone)
            my_picks = json.loads(my_picks_raw) if isinstance(my_picks_raw, str) else {}
            if my_picks.get("status") == "success" and my_picks.get("latest_task"):
                task_id = my_picks["latest_task"]["id"]
        if not task_id:
            all_tasks = database.get_all_pickup_tasks()
            active_tasks = [t for t in all_tasks if t.get("status") in ["ASSIGNED", "PICKUP_ASSIGNED", "EN_ROUTE"]]
            if active_tasks:
                task_id = active_tasks[-1]["id"]
            elif all_tasks:
                task_id = all_tasks[-1]["id"]

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
    if any(
        m in clean_p
        for m in [
            "delivered",
            "food delivered",
            "dropped off",
            "delivery completed",
            "delivery done",
            "භාරදුන්නා",
            "බෙදාහැරියා",
            "வழங்கினேன்",
            "டெலிவரி",
        ]
    ):
        task_id = tools._get_context_val("current_task_id", "")
        if not task_id and phone:
            my_picks_raw = tools.get_my_pickups(phone=phone)
            my_picks = json.loads(my_picks_raw) if isinstance(my_picks_raw, str) else {}
            if my_picks.get("status") == "success" and my_picks.get("latest_task"):
                task_id = my_picks["latest_task"]["id"]
        if not task_id:
            all_tasks = database.get_all_pickup_tasks()
            active_tasks = [t for t in all_tasks if t.get("status") in ["COLLECTED", "IN_TRANSIT", "ASSIGNED", "PICKUP_ASSIGNED", "EN_ROUTE"]]
            if active_tasks:
                task_id = active_tasks[-1]["id"]
            elif all_tasks:
                task_id = all_tasks[-1]["id"]

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
    has_food_or_donation_keywords = any(
        w in clean_p
        for w in [
            "donate",
            "donation",
            "packets",
            "packet",
            "meals",
            "meal",
            "portions",
            "portion",
            "rice",
            "curry",
            "bread",
            "biryani",
            "cooked food",
            "bakery",
            "boxes",
            "kg",
            "i have",
            "we have",
            "hotel",
            "restaurant",
            "caterer",
        ]
    ) and not any(v in clean_p for v in ["available to volunteer", "volunteer to deliver", "deliver food", "help with pickups", "for pickups"])

    is_vol_standalone_avail = (
        clean_p in [
            "available",
            "available now",
            "i am available",
            "i'm available",
            "im available",
            "free",
            "free now",
            "i'm free",
            "i am free",
            "ready",
            "mark me available",
            "mark available",
            "සූදානම්",
            "ලෑස්තියි",
            "தயார்",
        ]
        or clean_p.startswith("available ")
    ) and not has_food_or_donation_keywords

    is_vol_intent = (
        not has_food_or_donation_keywords
        and (
            is_vol_standalone_avail
            or any(
                m in clean_p
                for m in [
                    "i'm free",
                    "i am free",
                    "free now",
                    "free",
                    "i can help",
                    "available for pickup",
                    "available to help",
                    "available courier",
                    "pickups near me",
                    "any pickups",
                    "have time",
                    "ready to help",
                    "volunteer",
                    "want to volunteer",
                    "courier",
                    "help deliver",
                    "available to volunteer",
                    "free to volunteer",
                    "ready to volunteer",
                    "delivery volunteer",
                    "ස්වේච්ඡා",
                    "උදව් කරන්න පුළුවන්",
                    "உதவ முடியும்",
                    "தன்னார்வலர்",
                    "இலவசம்",
                ]
            )
        )
    ) or (clean_p == "3" and not in_vol_workflow and not has_food_or_donation_keywords)

    if (is_vol_intent or in_vol_workflow) and not (clean_p in ["hi", "hello", "hey", "menu", "start"] and not in_vol_workflow):
        if phone:
            database.update_user_profile(phone=phone, user_role="volunteer")
        # 6e-1. Direct availability declaration (e.g. "Available", "I'm free now", "Hii i am available to volunteer today", "I'm free to volunteer now")
        is_direct_avail = (
            is_vol_standalone_avail
            or any(
                m in clean_p
                for m in [
                    "free now",
                    "i'm free",
                    "i am free",
                    "free to volunteer",
                    "available for pickup",
                    "available to volunteer",
                    "available to help",
                    "ready to help",
                    "ready",
                    "ස්වේච්ඡා",
                    "ලෑස්තියි",
                    "සූදානම්",
                    "උදව් කරන්න පුළුවන්",
                    "தயார்",
                ]
            )
        ) and not has_food_or_donation_keywords

        if is_direct_avail:
            if not existing_vol:
                vol_area_guess = (user.get("default_location") if user else None) or "Colombo"
                tools.register_volunteer(
                    name=(user.get("display_name") if user and not user.get("display_name", "").startswith("User_") else "Volunteer Courier"),
                    service_area=vol_area_guess,
                    phone=phone,
                    transport_mode="Motorbike",
                    district=routing.resolve_district(vol_area_guess) or "Colombo"
                )
                existing_vol = database.get_volunteer_by_phone(phone) if phone else None

            if existing_vol:
                tools.update_volunteer_availability(
                    volunteer_id=existing_vol["id"], status="AVAILABLE", current_location=existing_vol.get("service_area", "Colombo")
                )

            vol_area = existing_vol.get("service_area", "Colombo") if existing_vol else "Colombo"
            clean_vol_dist = routing.resolve_district(vol_area) or "Colombo"

            # Clear previous conversation state
            if phone:
                database.clear_user_conversation_state(phone)

            pending = database.get_all_pickup_tasks()
            available_tasks = [t for t in pending if t.get("status") in ["PENDING", "OFFERED", "OPEN"]]
            dist_tasks = [t for t in available_tasks if routing.resolve_district(t.get("pickup_location") or "") == clean_vol_dist]
            candidate_tasks = dist_tasks if dist_tasks else available_tasks

            if candidate_tasks:
                top_task = candidate_tasks[0]
                task_id = top_task["id"]
                don_id = top_task.get("donation_id", "")
                don = database.get_donation_record(don_id) if don_id else None
                food_info = _format_food_info(don)
                total_dist, est_cost, d_name, d_contact, r_name, p_area, d_area = _calculate_dynamic_task_metrics(top_task, existing_vol)
                tools.set_session_context(key="current_task_id", value=task_id)
                if existing_vol:
                    tools.set_session_context(key="current_volunteer_id", value=existing_vol["id"])
                if phone:
                    database.set_user_conversation_state(
                        phone, {"workflow": "VOLUNTEER", "current_question": "ACCEPT_TASK", "expected_input_type": "CHOICE", "task_id": task_id}
                    )
                return (
                    f"🎉 **Great! You are now marked as AVAILABLE.**\n\n"
                    f"🚚 **Food Pickup Opportunity in {clean_vol_dist}!**\n\n"
                    f"• 🆔 **Task ID**: `{task_id}`\n"
                    f"• 🍱 **Food**: {food_info}\n"
                    f"• 📍 **Pickup**: {p_area}\n"
                    f"• 🏢 **Delivery**: {r_name} ({d_area})\n"
                    f"• 📏 **Distance**: ~{total_dist} km\n"
                    f"• 💰 **Estimated transport support**: LKR {int(est_cost)}\n\n"
                    f"*Reply **Accept** or **Reject***"
                )
            else:
                return (
                    f"🎉 **Great! You are now marked as AVAILABLE.**\n\n"
                    f"❤️ **Thank You For Volunteering!**\n"
                    f"You are registered as an active volunteer courier in **{vol_area}**.\n\n"
                    f"📦 There are currently **no active pickups** (0 pending tasks) waiting in your area.\n"
                    f"As soon as a food donation is registered in {clean_vol_dist}, our AI coordinator will automatically notify you right here on WhatsApp! 🚚\n\n"
                    f"Reply with:\n"
                    f"1️⃣ View available tasks\n"
                    f"2️⃣ Update my vehicle mode / service area\n"
                    f"3️⃣ Check my active pickups"
                )

        vol_name = (existing_vol.get("name") if existing_vol else None) or curr_state.get("vol_name")
        vol_vehicle = (existing_vol.get("transport_mode") if existing_vol else None) or curr_state.get("vol_vehicle")
        vol_loc = (existing_vol.get("service_area") if existing_vol else None) or curr_state.get("vol_loc") or curr_state.get("vol_district")

        # Extract Volunteer Name
        v_name_match = re.search(r"(?:my\s*name\s*is|name\s*:|i\s*am)\s*([a-zA-Z\s]+)", prompt, re.IGNORECASE)
        if v_name_match and "kamal hotel" not in clean_p:
            vol_name = v_name_match.group(1).strip()
        elif curr_state.get("expected_input_type") == "VOL_NAME" and len(clean_p.split()) <= 4:
            vol_name = prompt.strip().title()

        # Extract Vehicle / Transport Mode
        if any(w in clean_p for w in ["three-wheeler", "three wheeler", "three_wheeler", "tuk", "tuk tuk", "tuktuk", "ත්‍රීරෝද", "ஆட்டோ"]):
            vol_vehicle = "Three-Wheeler"
        elif any(w in clean_p for w in ["motorbike", "bike", "motorcycle", "scooter", "යතුරුපැදි", "பைக்", "மோட்டார்"]):
            vol_vehicle = "Motorbike"
        elif "car" in clean_p or "කාර්" in clean_p or "கார்" in clean_p:
            vol_vehicle = "Car"
        elif "van" in clean_p or "වෑන්" in clean_p or "வேன்" in clean_p:
            vol_vehicle = "Van"
        elif "bicycle" in clean_p or "පාපැදි" in clean_p or "மிதிவண்டி" in clean_p:
            vol_vehicle = "Bicycle"
        elif curr_state.get("expected_input_type") == "VOL_VEHICLE" and len(clean_p.split()) <= 3:
            vol_vehicle = prompt.strip().title()

        # Extract District / Location

        v_dist_resolved = routing.resolve_district(prompt)
        if v_dist_resolved:
            vol_loc = v_dist_resolved
        elif curr_state.get("expected_input_type") in ["VOL_DISTRICT", "VOL_CITY"] and len(clean_p.split()) <= 4:
            vol_loc = routing.resolve_district(prompt) or prompt.strip().title()

        # Check if volunteer has provided live location or ready to complete
        has_live_loc = curr_state.get("expected_input_type") == "VOL_LIVE_LOCATION" or "location" in clean_p or existing_vol is not None

        # If name, vehicle, and district are present:
        if (
            (vol_name or existing_vol)
            and (vol_vehicle or (existing_vol and existing_vol.get("transport_mode")))
            and (vol_loc or (existing_vol and existing_vol.get("service_area")))
        ):
            final_vol_name = vol_name or (existing_vol.get("name") if existing_vol else "Volunteer Courier")
            final_vol_veh = vol_vehicle or (existing_vol.get("transport_mode") if existing_vol else "Three-Wheeler")
            final_vol_loc = vol_loc or (existing_vol.get("service_area") if existing_vol else "Kegalle")
            final_district = routing.resolve_district(final_vol_loc) or "Kegalle"

            if phone:
                tools.register_volunteer(
                    name=final_vol_name,
                    service_area=final_district,
                    phone=phone,
                    transport_mode=final_vol_veh,
                    district=final_district,
                    location=final_vol_loc,
                )
                database.update_user_profile(phone=phone, display_name=final_vol_name, user_role="volunteer", default_location=final_district)

            if curr_state.get("expected_input_type") != "VOL_LIVE_LOCATION" and not existing_vol:
                # Step 4: Ask for mandatory Live Location Pin after district is entered
                if phone:
                    database.set_user_conversation_state(
                        phone,
                        {
                            "workflow": "VOLUNTEER_REGISTRATION",
                            "expected_input_type": "VOL_LIVE_LOCATION",
                            "current_question": "VOL_LIVE_LOCATION",
                            "vol_name": final_vol_name,
                            "vol_vehicle": final_vol_veh,
                            "vol_district": final_district,
                            "vol_loc": final_vol_loc,
                        },
                    )
                return translation_service.get_localized_message(
                    "vol_ask_live_location", lang=lang, vol_name=final_vol_name, district=final_district, vehicle=final_vol_veh
                )

            # Clear conversation state
            if phone:
                database.set_user_conversation_state(phone, {})

            # Look up pending tasks filtered/ranked by district
            pending = database.get_all_pickup_tasks()
            available_tasks = [t for t in pending if t.get("status") in ["PENDING", "OFFERED", "OPEN"]]
            # Prioritize matching district
            district_tasks = [t for t in available_tasks if routing.resolve_district(t.get("pickup_location") or "") == final_district]
            tasks_to_show = district_tasks if district_tasks else available_tasks

            if tasks_to_show:
                top_task = tasks_to_show[0]
                task_id = top_task["id"]
                don_id = top_task.get("donation_id", "")
                don = database.get_donation_record(don_id) if don_id else None
                food_info = _format_food_info(don)

                vol_record = database.get_volunteer_by_phone(phone) if phone else None
                total_dist, est_cost, d_name, d_contact, r_name, p_area, d_area = _calculate_dynamic_task_metrics(
                    top_task, vol_record or {"transport_mode": final_vol_veh, "service_area": final_district}
                )

                tools.set_session_context(key="current_task_id", value=task_id)
                if vol_record:
                    tools.set_session_context(key="current_volunteer_id", value=vol_record["id"])
                if phone:
                    database.set_user_conversation_state(
                        phone, {"workflow": "VOLUNTEER", "current_question": "ACCEPT_TASK", "expected_input_type": "CHOICE", "task_id": task_id}
                    )

                return (
                    f"❤️ **Welcome to FoodRescue AI, {final_vol_name}!**\n\n"
                    f"You are registered as an active courier in **{final_district} District** ({final_vol_veh}) and marked **AVAILABLE**.\n\n"
                    f"🚚 **Food Pickup Available in {final_district}!**\n\n"
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
                    f"You are registered in **{final_district} District** with your **{final_vol_veh}**.\n\n"
                    f"📦 There are currently 0 pending pickups waiting in {final_district} District.\n"
                    f"As soon as a food donation is ready in {final_district}, our AI coordinator will automatically send you a pickup offer right here on WhatsApp! 🚚"
                )

        # Progressive slot-filling:
        if not vol_name:
            if phone:
                database.set_user_conversation_state(
                    phone, {"workflow": "VOLUNTEER_REGISTRATION", "expected_input_type": "VOL_NAME", "current_question": "VOL_NAME"}
                )
            return translation_service.get_localized_message("vol_ask_name", lang=lang)
        elif not vol_vehicle:
            if phone:
                database.set_user_conversation_state(
                    phone,
                    {
                        "workflow": "VOLUNTEER_REGISTRATION",
                        "expected_input_type": "VOL_VEHICLE",
                        "current_question": "VOL_VEHICLE",
                        "vol_name": vol_name,
                    },
                )
            return translation_service.get_localized_message("vol_ask_vehicle", lang=lang, vol_name=vol_name)
        else:
            if phone:
                database.set_user_conversation_state(
                    phone,
                    {
                        "workflow": "VOLUNTEER_REGISTRATION",
                        "expected_input_type": "VOL_DISTRICT",
                        "current_question": "VOL_DISTRICT",
                        "vol_name": vol_name,
                        "vol_vehicle": vol_vehicle,
                    },
                )
            return translation_service.get_localized_message("vol_ask_district", lang=lang, vol_name=vol_name)

    # 7. Recipient Organization Workflow ("2", "request food", "need food", "community organization", "shelter", "hope food")
    is_org_inventory_query = clean_p in [
        "view all",
        "view all available donations",
        "view available",
        "all donations",
        "view donations",
        "available donations",
        "surplus food",
        "inventory",
    ]
    is_org_menu_opt = clean_p in ["2", "request food", "request available food", "need food", "food request", "community organization", "shelter"]
    is_org_intent = any(
        m in clean_p
        for m in [
            "community organization",
            "need food",
            "request food",
            "food bank",
            "shelter",
            "we need",
            "meals for",
            "packets for",
            "food for our",
            "for our shelter",
            "organization name:",
            "hope food home",
            "hope food",
            "charity",
            "feeding people",
        ]
    )
    curr_state = database.get_user_conversation_state(phone) if phone else {}
    in_org_workflow = curr_state.get("workflow") == "RECIPIENT_REQUEST"

    if (is_org_inventory_query or is_org_menu_opt or is_org_intent or in_org_workflow) and not (
        clean_p in ["hi", "hello", "hey", "menu", "start"] and not in_org_workflow
    ):
        if phone:
            database.update_user_profile(phone=phone, user_role="organization")
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
        org_loc = (existing_org.get("location") if existing_org else None) or curr_state.get("city") or curr_state.get("district")
        org_cap = (existing_org.get("capacity") if existing_org else None) or curr_state.get("org_capacity")
        food_needed = curr_state.get("food_needed")

        # Extract Organization Name
        name_match = re.search(r"(?:organization\s*(?:name)?|name)\s*:\s*([^\n\r,]+)", prompt, re.IGNORECASE)
        if name_match:
            org_name = name_match.group(1).strip()
        elif "hope food home" in clean_p or "hope food" in clean_p:
            org_name = "Hope Food Home"
        elif curr_state.get("expected_input_type") == "ORG_NAME" and len(clean_p.split()) <= 6 and not is_org_intent:
            org_name = prompt.strip()

        # Extract District / Location

        dist_resolved = routing.resolve_district(prompt)
        if dist_resolved:
            org_loc = prompt.strip()
        elif curr_state.get("expected_input_type") in ["ORG_DISTRICT", "CITY"] and len(clean_p.split()) <= 4:
            org_loc = prompt.strip().title()

        # Extract Capacity / Daily Portions Needed
        cap_match = re.search(r"(?:capacity|daily capacity|daily|portions?|meals?)\s*:\s*([^\n\r,]+)", prompt, re.IGNORECASE)
        if cap_match:
            org_cap = cap_match.group(1).strip()
        elif curr_state.get("expected_input_type") == "ORG_CAPACITY":
            org_cap = prompt.strip()
        elif any(w in clean_p for w in ["meals", "portions", "packets", "people", "persons", "meals/day"]):
            org_cap = prompt.strip()

        # Extract Food Need
        food_match = re.search(r"(?:we\s+need|need)\s*([^\n\r\.]+)", prompt, re.IGNORECASE)
        if food_match:
            food_needed = food_match.group(1).strip()
        elif curr_state.get("expected_input_type") in ["FOOD_NEED", "ORG_LIVE_LOCATION"]:
            food_needed = prompt.strip()

        # If all details are present, register & match!
        if org_name and org_loc and org_cap and (food_needed or curr_state.get("expected_input_type") in ["FOOD_NEED", "ORG_LIVE_LOCATION", "ORG_CAPACITY"] or is_org_intent):
            final_org_name = org_name or "Community Organization"
            final_org_loc = org_loc or "Kegalle"
            final_district = routing.resolve_district(final_org_loc) or "Kegalle"
            final_food = food_needed or "Meal packets"
            final_capacity = org_cap or "100 portions"

            if phone:
                tools.register_organization(
                    name=final_org_name,
                    location=final_org_loc,
                    service_area=final_district,
                    accepted_food_types=final_food,
                    phone=phone,
                    capacity=final_capacity,
                    district=final_district,
                )
                database.update_user_profile(phone=phone, display_name=final_org_name, user_role="organization", default_location=final_district)

            if curr_state.get("expected_input_type") != "ORG_LIVE_LOCATION" and not existing_org:
                # Step 4: Ask for Live Location Pin after district and capacity are entered
                if phone:
                    database.set_user_conversation_state(
                        phone,
                        {
                            "workflow": "RECIPIENT_REQUEST",
                            "expected_input_type": "ORG_LIVE_LOCATION",
                            "current_question": "ORG_LIVE_LOCATION",
                            "org_name": final_org_name,
                            "district": final_district,
                            "city": final_org_loc,
                            "org_capacity": final_capacity,
                            "food_needed": final_food,
                        },
                    )
                return translation_service.get_localized_message("org_ask_live_location", lang=lang, city=final_org_loc or final_district, district=final_district)

            # Clear recipient conversation state on completion
            if phone:
                database.set_user_conversation_state(phone, {})

            reg_loc_str = (
                f"**{final_org_loc}** ({final_district} District)"
                if final_org_loc.lower() != final_district.lower()
                else f"**{final_district} District**"
            )

            # Search available matching donations in network (filtered by district)
            all_dons = database.get_all_donations()
            active_dons = [d for d in all_dons if d.get("status") in ["AVAILABLE", "MATCHED", "PICKUP_PENDING", "PICKUP_ASSIGNED"]]

            # Match donations in the same district
            district_matches = [d for d in active_dons if routing.resolve_district(d.get("pickup_location") or "") == final_district]

            if district_matches:
                top_m = district_matches[0]
                food_info = _format_food_info(top_m)
                m_donor = top_m.get("donor_name", "Local Donor")
                m_dead = top_m.get("pickup_deadline") or "Immediate"
                d_phone = top_m.get("donor_phone")
                d_donor_id = top_m.get("donor_id")
                if not d_phone and d_donor_id:
                    d_rec = database.get_donor_record(d_donor_id)
                    d_phone = d_rec.get("phone") if d_rec else None

                # Propose organization to Donor so Donor can Accept/Reject
                if d_phone:
                    database.set_user_conversation_state(
                        d_phone,
                        {
                            "workflow": "DONATION",
                            "current_question": "ACCEPT_ORGANIZATION",
                            "expected_input_type": "CHOICE",
                            "matched_org_id": (existing_org.get("id") if existing_org else "o1"),
                            "donation_id": top_m.get("id"),
                            "donor_name": m_donor,
                            "food_info": food_info,
                            "district": final_district,
                        },
                    )

                return (
                    f"👋 Hello from **{final_org_name}**! I've successfully registered your organization in {reg_loc_str} (Daily Capacity: {final_capacity}).\n\n"
                    f"🍱 **Great news! We found an available food match in {final_district} District:**\n"
                    f"• **{m_qty} {m_unit} — {m_food}** ({m_donor}, {top_m.get('pickup_location', final_district)})\n"
                    f"⏰ **Pickup deadline**: {m_dead}\n\n"
                    f"📍 **Please share your organization's exact WhatsApp live location pin:**\n"
                    f"Tap ➕ (or 📎) → Location → 'Send your current location' 📍 so our volunteer courier can pick up and deliver the food to you!"
                )
            elif active_dons:
                lines = [
                    f"• **{d.get('quantity')} {d.get('unit', 'packets')} — {d.get('food_type')}** (📍 {d.get('pickup_location')})"
                    for d in active_dons[:3]
                ]
                avail_str = "\n".join(lines)
                return (
                    f"👋 Hello from **{final_org_name}**! I've registered your organization in {reg_loc_str} (Daily Capacity: {final_capacity}).\n\n"
                    f"📦 **Currently Available Surplus Donations in the Network:**\n"
                    f"{avail_str}\n\n"
                    f"🔍 We have noted your request for {final_food} in **{final_district} District**. As soon as a local donor in {final_district} posts surplus food, our AI will alert you and dispatch a courier immediately!\n\n"
                    f"📍 Please share your organization's WhatsApp live location pin 📍 so your delivery point is saved."
                )
            else:
                return (
                    f"👋 Hello from **{final_org_name}**! I've successfully registered your organization in {reg_loc_str} (Daily Capacity: {final_capacity}).\n\n"
                    f"🔍 We have logged your request for {final_food} in **{final_district} District**. Our AI coordinator will immediately notify you and dispatch a courier the moment a donor posts surplus food in your area!\n\n"
                    f"📍 **Please share your organization's WhatsApp live location pin 📍** so volunteer couriers can navigate directly to your delivery point."
                )

        # If details are missing, progressive slot-filling:
        if not org_name:
            if phone:
                database.set_user_conversation_state(
                    phone, {"workflow": "RECIPIENT_REQUEST", "expected_input_type": "ORG_NAME", "current_question": "ORG_NAME"}
                )
            return translation_service.get_localized_message("org_ask_name", lang=lang)
        elif not org_loc:
            if phone:
                database.set_user_conversation_state(
                    phone,
                    {
                        "workflow": "RECIPIENT_REQUEST",
                        "expected_input_type": "ORG_DISTRICT",
                        "current_question": "ORG_DISTRICT",
                        "org_name": org_name,
                    },
                )
            return translation_service.get_localized_message("org_ask_district", lang=lang, org_name=org_name)
        elif not org_cap:
            if phone:
                database.set_user_conversation_state(
                    phone,
                    {
                        "workflow": "RECIPIENT_REQUEST",
                        "expected_input_type": "ORG_CAPACITY",
                        "current_question": "ORG_CAPACITY",
                        "org_name": org_name,
                        "district": org_loc,
                        "city": org_loc,
                    },
                )
            return translation_service.get_localized_message("org_ask_capacity", lang=lang, org_name=org_name)
        else:
            if phone:
                database.set_user_conversation_state(
                    phone,
                    {
                        "workflow": "RECIPIENT_REQUEST",
                        "expected_input_type": "ORG_LIVE_LOCATION",
                        "current_question": "ORG_LIVE_LOCATION",
                        "org_name": org_name,
                        "district": org_loc,
                        "city": org_loc,
                        "org_capacity": org_cap,
                    },
                )
            return translation_service.get_localized_message("org_ask_live_location", lang=lang, city=org_loc or "your area", district=org_loc or "your district")

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
    vol_rec = database.get_volunteer_by_phone(phone) if phone else None
    org_rec = database.get_organization_by_phone(phone) if phone else None

    # Pre-fill draft from registered donor master profile if returning donor
    if donor and phone:
        needs_save = False
        draft_seed = {}
        if not existing_draft.get("donor_name") and donor.get("name"):
            draft_seed["donor_name"] = donor["name"]
            draft_seed["business_name"] = donor.get("organization_name") or donor["name"]
            needs_save = True
        if not existing_draft.get("city") and donor.get("location"):
            draft_seed["city"] = donor["location"]
            draft_seed["location"] = donor["location"]
            needs_save = True
        if needs_save:
            existing_draft = database.save_draft_donation(phone, draft_seed)

    # Role guard for registered volunteer: Never prompt for food donations or create drafts
    if (vol_rec or (user and user.get("user_role") == "volunteer")) and curr_state.get("workflow") != "DONATION":
        is_explicit_donate = any(w in clean_p for w in ["i want to donate", "donate food", "i have food to donate", "පරිත්‍යාග", "தானம்"])
        if not is_explicit_donate:
            vol_name = (vol_rec.get("name") if vol_rec else None) or (user.get("display_name") if user else "Volunteer")
            vol_area = (vol_rec.get("service_area") if vol_rec else None) or (user.get("default_location") if user else "Sri Lanka")
            vol_dist = routing.resolve_district(vol_area) or "Kegalle"

            pending = database.get_all_pickup_tasks()
            available_tasks = [t for t in pending if t.get("status") in ["PENDING", "OFFERED", "OPEN"]]
            dist_tasks = [t for t in available_tasks if routing.resolve_district(t.get("pickup_location") or "") == vol_dist]
            candidate_tasks = dist_tasks if dist_tasks else available_tasks

            if candidate_tasks:
                top_task = candidate_tasks[0]
                task_id = top_task["id"]
                don_id = top_task.get("donation_id", "")
                don = database.get_donation_record(don_id) if don_id else None
                food_info = (
                    f"{don.get('quantity', 30)} {don.get('unit', 'meal packets')} — {don.get('food_type', 'Prepared Meals')}"
                    if don
                    else "30 meal packets — Prepared Meals"
                )
                total_dist, est_cost, d_name, d_contact, r_name, p_area, d_area = _calculate_dynamic_task_metrics(top_task, vol_rec)

                tools.set_session_context(key="current_task_id", value=task_id)
                if vol_rec:
                    tools.set_session_context(key="current_volunteer_id", value=vol_rec["id"])
                if phone:
                    database.set_user_conversation_state(
                        phone, {"workflow": "VOLUNTEER", "current_question": "ACCEPT_TASK", "expected_input_type": "CHOICE", "task_id": task_id}
                    )

                return (
                    f"🚚 **Food Pickup Opportunity in {vol_dist}!**\n\n"
                    f"Hi {vol_name}! A food rescue task is available:\n\n"
                    f"• 🆔 **Task ID**: `{task_id}`\n"
                    f"• 🍱 **Food**: {food_info}\n"
                    f"• 📍 **Pickup**: {p_area}\n"
                    f"• 🏢 **Delivery**: {r_name} ({d_area})\n"
                    f"• 📏 **Distance**: ~{total_dist} km\n"
                    f"• 💰 **Estimated transport support**: LKR {int(est_cost)}\n\n"
                    f"*Reply **Accept** or **Reject***"
                )
            else:
                return (
                    f"🚚 **Volunteer Courier Portal ({vol_dist})**\n\n"
                    f"Hi {vol_name}! You are registered as an active courier in **{vol_dist}** and marked **AVAILABLE**.\n\n"
                    f"There are currently 0 unassigned pickups waiting in {vol_dist}.\n\n"
                    f"Reply with:\n"
                    f"1️⃣ Search active pickups\n"
                    f"2️⃣ Check active delivery status\n"
                    f"3️⃣ Mark myself as free / update vehicle\n"
                    f"4️⃣ Change language (භාෂාව / மொழி)\n\n"
                    f"Our coordinator will message you immediately once a local pickup is ready! 🚚"
                )

    # 9a-0. Handle Organization Accepting/Declining Food Donation Offer
    if (curr_q == "ACCEPT_DONATION_OFFER" or expected_type == "ACCEPT_DONATION_OFFER" or (org_rec and curr_state.get("workflow") == "ORGANIZATION" and curr_state.get("donation_id"))) and (org_rec or (user and user.get("user_role") == "organization")):
        if any(
            m in clean_p
            for m in [
                "accept",
                "1",
                "yes",
                "confirm",
                "ok",
                "sure",
                "y",
                "agree",
                "claim",
                "පිළිගන්නවා",
                "ඔව්",
                "භාරගන්නවා",
                "ஏற்கிறேன்",
                "ஆம்",
                "ஏற்றுக்கொள்கிறேன்",
            ]
        ):
            don_id = curr_state.get("donation_id")
            donor_phone = curr_state.get("donor_phone")
            donor_name = curr_state.get("donor_name", "Local Food Donor")
            food_info = curr_state.get("food_info", "Surplus Food")
            org_id = (org_rec.get("id") if org_rec else None) or "o1"
            org_name = (org_rec.get("name") if org_rec else None) or "Recipient Organization"
            org_loc = (org_rec.get("location") or org_rec.get("service_area") or "Kegalle") if org_rec else "Kegalle"
            org_clean_dist = routing.resolve_district(org_loc) or "Kegalle"

            don = database.get_donation_record(don_id) if don_id else None
            if don:
                donor_loc = don.get("pickup_location") or don.get("location") or org_clean_dist
                deadline = don.get("pickup_deadline", "Immediate")
                if not donor_phone and don.get("donor_id"):
                    donor_rec = database.get_donor_record(don.get("donor_id"))
                    donor_phone = donor_rec.get("phone") if donor_rec else don.get("donor_phone")
            else:
                donor_loc = org_clean_dist
                deadline = "Immediate"

            if don_id:
                tools.accept_donation(donation_id=don_id, organization_id=org_id)

            task_raw = tools.create_pickup_task(
                donation_id=don_id,
                organization_id=org_id,
                pickup_location=donor_loc,
                delivery_location=org_loc,
                scheduled_time=deadline,
            )
            task_res = json.loads(task_raw) if isinstance(task_raw, str) else {}
            task_id = task_res.get("task_id", "")

            # Clear org state
            if phone:
                database.clear_user_conversation_state(phone)

            # Find available volunteers in this district and broadcast/offer
            all_vols = database.get_all_volunteers()
            dist_vols = [
                v for v in all_vols
                if (v.get("current_status", "").upper() in ["AVAILABLE", "ACTIVE", ""] or v.get("status", "").upper() in ["AVAILABLE", "ACTIVE", ""])
                and (
                    routing.resolve_district(v.get("service_area") or v.get("location") or "") == org_clean_dist
                    or not v.get("service_area")
                    or v.get("service_area") == "Sri Lanka"
                )
            ]

            if task_id and dist_vols:
                for v in dist_vols[:3]:
                    v_phone = v.get("phone")
                    if v_phone and v_phone != phone and v_phone != donor_phone:
                        database.set_user_conversation_state(
                            v_phone,
                            {
                                "workflow": "VOLUNTEER",
                                "current_question": "ACCEPT_TASK",
                                "expected_input_type": "CHOICE",
                                "task_id": task_id,
                            }
                        )

            return translation_service.get_localized_message(
                "org_accepted_dispatching_volunteer",
                lang=lang,
                org_name=org_name,
                food_info=food_info,
                donor_name=donor_name,
                donor_location=donor_loc,
                org_location=org_loc,
                district=org_clean_dist,
            )

        elif any(m in clean_p for m in ["decline", "no", "reject", "cancel", "pass", "බැහැ", "මඟහරින්න", "மறுக்கிறேன்"]):
            if phone:
                database.clear_user_conversation_state(phone)
            return "👍 Thank you for letting us know. We will offer this donation to other organizations in your district."

    # Role guard for registered organization: Never prompt for food donations or create drafts
    if (org_rec or (user and user.get("user_role") == "organization")) and curr_state.get("workflow") != "DONATION":
        is_explicit_donate = any(w in clean_p for w in ["i want to donate", "donate food", "i have food to donate", "පරිත්‍යාග", "தானம்"])
        if not is_explicit_donate:
            org_name = (org_rec.get("name") if org_rec else None) or (user.get("display_name") if user else "Recipient Organization")
            org_area = (org_rec.get("location") if org_rec else None) or (user.get("default_location") if user else "Sri Lanka")
            org_dist = routing.resolve_district(org_area) or "Kegalle"

            all_dons = database.get_all_donations()
            active_dons = [d for d in all_dons if d.get("status") in ["AVAILABLE", "MATCHED", "PICKUP_PENDING"]]
            dist_dons = [d for d in active_dons if routing.resolve_district(d.get("pickup_location") or "") == org_dist]
            match_dons = dist_dons if dist_dons else active_dons

            if match_dons:
                lines = [
                    f"• **{d.get('quantity')} {d.get('unit', 'portions')} — {d.get('food_type')}** (📍 {d.get('pickup_location', org_dist)})"
                    for d in match_dons[:3]
                ]
                avail_str = "\n".join(lines)
                return (
                    f"🏢 **Recipient Organization Portal ({org_dist})**\n\n"
                    f"Hi {org_name}! Available surplus food in network:\n\n"
                    f"{avail_str}\n\n"
                    f"📍 Please share your organization's delivery location pin (Tap ➕ → Location → Send your current location 📍) to receive food!"
                )
            else:
                return (
                    f"🏢 **Recipient Organization Portal ({org_dist})**\n\n"
                    f"Hi {org_name}! We have **{org_name}** registered on our priority food distribution list for **{org_dist} District**.\n\n"
                    f"There are currently 0 active surplus food donations available right now.\n\n"
                    f"You don't need to keep asking; our AI coordinator will automatically notify you on WhatsApp the moment fresh surplus food is donated in your district! 🍱"
                )

    # 9a. Handle Donor Accepting/Rejecting Matched Organization (Backwards Compatibility)
    if curr_q == "ACCEPT_ORGANIZATION" or expected_type == "ACCEPT_ORGANIZATION":
        if any(
            m in clean_p
            for m in [
                "accept",
                "1",
                "yes",
                "confirm",
                "ok",
                "connect",
                "sure",
                "y",
                "agree",
                "පිළිගන්නවා",
                "ඔව්",
                "ஏற்கிறேன்",
                "ஆம்",
            ]
        ):
            matched_org_id = curr_state.get("matched_org_id")
            don_id = curr_state.get("donation_id")
            if not don_id:
                all_dons = database.get_all_donations()
                if all_dons:
                    don_id = all_dons[-1]["id"]
            if not matched_org_id:
                all_orgs = database.get_all_organizations()
                if all_orgs:
                    matched_org_id = all_orgs[-1]["id"]

            don = database.get_donation_record(don_id) if don_id else None
            org = database.get_organization_record(matched_org_id) if matched_org_id else None
            org_name = org.get("name", "Recipient Organization") if org else "Recipient Organization"
            org_phone = org.get("phone") if org else None

            if don_id and matched_org_id:
                tools.accept_donation(donation_id=don_id, organization_id=matched_org_id)

            donor_name = don.get("donor_name", "Local Donor") if don else "Local Donor"
            donor_phone = phone or (don.get("donor_phone") if don else "")
            food_info = (
                f"{don.get('quantity', 20)} {don.get('unit', 'packets')} of {don.get('food_type', 'Rice & Curry')}"
                if don
                else "20 packets of Rice & Curry"
            )
            deadline = don.get("pickup_deadline", "Immediate") if don else "Immediate"
            pickup_loc = don.get("pickup_location") or don.get("location") or "Pickup Location" if don else "Pickup Location"
            deliv_loc = org.get("location") or org.get("service_area") or "Delivery Location" if org else "Delivery Location"

            don_dist = routing.resolve_district(pickup_loc) or routing.resolve_district(deliv_loc) or "Kegalle"

            # Create pickup task linking donor and organization
            task_id = ""
            if don_id and matched_org_id:
                task_raw = tools.create_pickup_task(
                    donation_id=don_id,
                    organization_id=matched_org_id,
                    pickup_location=pickup_loc,
                    delivery_location=deliv_loc,
                    scheduled_time=deadline,
                )
                task_res = json.loads(task_raw) if isinstance(task_raw, str) else {}
                task_id = task_res.get("task_id", "")

            # Search available volunteers in this specific district
            all_vols = database.get_all_volunteers()
            dist_vols = [
                v
                for v in all_vols
                if (v.get("current_status", "").upper() in ["AVAILABLE", "ACTIVE", ""] or v.get("status", "").upper() in ["AVAILABLE", "ACTIVE", ""])
                and (
                    routing.resolve_district(v.get("service_area") or v.get("location") or "") == don_dist
                    or not v.get("service_area")
                    or v.get("service_area") == "Sri Lanka"
                )
            ]

            # If task created and volunteers available in district, offer to available volunteer(s)
            if task_id and dist_vols:
                top_vol = dist_vols[0]
                v_phone = top_vol.get("phone")
                if v_phone:
                    task_rec = database.get_pickup_task_record(task_id) or {"id": task_id}
                    ext = _get_task_extended_metrics(task_rec, top_vol)
                    database.set_user_conversation_state(
                        v_phone,
                        {"workflow": "VOLUNTEER", "current_question": "ACCEPT_TASK", "expected_input_type": "CHOICE", "task_id": task_id},
                    )

            if phone:
                database.clear_user_conversation_state(phone)

            return (
                f"✅ **Connected with {org_name}!**\n\n"
                f"We have sent your donation details to **{org_name}**.\n"
                f"Our AI coordinator is now searching for and dispatching available volunteer couriers in **{don_dist} District** to pick up and deliver the food. 🚚"
            )

        elif any(m in clean_p for m in ["reject", "no", "cancel", "decline", "වෙනත්", "මඟහරින්න", "மறுக்கிறேன்"]):
            if phone:
                database.clear_user_conversation_state(phone)
            return "👍 No problem! Your food donation remains active, and we will match you with another organization in your district."

    # 9b. Handle Confirmation Stage ("Confirm" / 1 -> commit donation)
    is_confirm_word = (
        clean_p in ["1", "confirm", "yes", "y", "ok", "okay", "correct", "create", "confirm donation", "තහවුරුයි", "ඔව්", "உறுதி", "ஆம்"]
        or clean_p == "confirm"
        or "confirm" in clean_p
    )
    is_confirm_intent = is_confirm_word

    loc_received = bool(
        existing_draft.get("location_received")
        or (existing_draft.get("latitude") and existing_draft.get("longitude"))
    )

    has_required_to_confirm = bool(
        existing_draft.get("food_type")
        and (existing_draft.get("quantity") and float(existing_draft.get("quantity", 0)) > 0)
        and (existing_draft.get("city") or existing_draft.get("location"))
        and loc_received
    )

    if curr_q == "CONFIRMATION" or expected_type == "CONFIRMATION" or (is_confirm_intent and has_required_to_confirm):
        if is_confirm_intent:
            # Commit donation from persistent draft
            qty = float(existing_draft.get("quantity") or 20.0)
            disp_qty = int(qty) if qty == int(qty) else qty
            food = existing_draft.get("food_type") or "Prepared Meals"
            unit = existing_draft.get("unit") or "packets"
            dietary = existing_draft.get("dietary_info") or "Standard"
            city = existing_draft.get("city") or existing_draft.get("location") or (donor.get("location") if donor else None) or "Colombo"
            loc = existing_draft.get("address") or existing_draft.get("location") or city
            deadline = existing_draft.get("pickup_deadline") or "Immediate"
            donor_name = (
                existing_draft.get("donor_name")
                or existing_draft.get("business_name")
                or (donor.get("name") if donor else None)
                or (user.get("display_name") if user and not user.get("display_name", "").startswith("User_") else "Donor Partner")
            )
            business_name = existing_draft.get("business_name") or donor_name

            if phone:
                reg_raw = tools.register_donor(name=donor_name, location=city, phone=phone)
                reg_res = json.loads(reg_raw) if isinstance(reg_raw, str) else {}
                donor_id = reg_res.get("donor_id") or "d1"
            else:
                donor_id = "d1"

            don_raw = tools.create_donation(
                donor_id=donor_id,
                food_type=food,
                quantity=qty,
                unit=unit,
                dietary_information=dietary,
                location=loc,
                available_from="Now",
                pickup_deadline=deadline,
            )
            don_res = json.loads(don_raw) if isinstance(don_raw, str) else {}
            don_id = don_res.get("donation_id", f"don-{uuid.uuid4().hex[:8]}")

            don_dist = routing.resolve_district(city) or routing.resolve_district(loc) or "Kegalle"

            # Check for matching recipient organizations in this district ranked by distance
            all_orgs = database.get_all_organizations()
            dist_orgs = [o for o in all_orgs if routing.resolve_district(o.get("service_area") or o.get("location") or "") == don_dist]
            if not dist_orgs:
                dist_orgs = all_orgs

            # Calculate distances to organizations
            donor_coords = None
            if existing_draft.get("latitude") and existing_draft.get("longitude"):
                try:
                    donor_coords = (float(existing_draft["latitude"]), float(existing_draft["longitude"]))
                except (ValueError, TypeError):
                    pass
            if not donor_coords:
                donor_coords = routing.geocode_location(loc) or routing.geocode_location(city)

            org_distances = []
            for o in dist_orgs:
                o_loc = o.get("location") or o.get("service_area") or don_dist
                o_coords = routing.geocode_location(o_loc)
                if donor_coords and o_coords:
                    d_km = round(max(0.5, routing.calculate_haversine_distance(donor_coords[0], donor_coords[1], o_coords[0], o_coords[1]) * 1.25), 1)
                else:
                    d_km = 3.5
                org_distances.append((d_km, o))

            org_distances.sort(key=lambda x: x[0])

            food_info = f"{disp_qty} {unit} of {food}"

            if org_distances and phone:
                top_dist, top_org = org_distances[0]
                # Set conversation state for organizations in district to receive donation offer
                for d_km, org_cand in org_distances:
                    o_phone = org_cand.get("phone")
                    if o_phone:
                        database.set_user_conversation_state(
                            o_phone,
                            {
                                "workflow": "ORGANIZATION",
                                "current_question": "ACCEPT_DONATION_OFFER",
                                "expected_input_type": "CHOICE",
                                "donation_id": don_id,
                                "donor_phone": phone,
                                "donor_name": donor_name,
                                "food_info": food_info,
                                "district": don_dist,
                                "distance_km": d_km,
                                "pickup_location": loc,
                                "deadline": deadline,
                            }
                        )

                database.clear_draft_donation(phone)
                database.clear_user_conversation_state(phone)

                return translation_service.get_localized_message(
                    "donor_donation_published_notified_orgs",
                    lang=lang,
                    donation_id=don_id,
                    donor_name=donor_name,
                    food_info=food_info,
                    city=loc or city,
                    deadline=deadline,
                    district=don_dist,
                    org_name=top_org.get("name", "Recipient Organization"),
                    distance_km=top_dist,
                )
            else:
                if phone:
                    database.clear_draft_donation(phone)
                    database.clear_user_conversation_state(phone)

                return translation_service.get_localized_message(
                    "donation_created_card",
                    lang=lang,
                    donor_name=donor_name,
                    donation_id=don_id,
                    quantity=disp_qty,
                    unit=unit,
                    food_type=food,
                    city=city,
                    deadline=deadline,
                )


        elif clean_p in ["2", "edit", "change", "modify"]:
            return (
                "📝 What details would you like to update? (You can say *'Actually 40 packets'*, *'Change city to Kandy'*, or *'Pickup time 7 PM'*)"
            )
        elif clean_p in ["3", "cancel", "stop"]:
            if phone:
                database.clear_draft_donation(phone)
                database.clear_user_conversation_state(phone)
            return "🛑 Donation creation cancelled. Reply **menu** anytime to start again."

    # 9b. Context-Aware Input Resolution Based on Current Question
    if curr_q == "DONOR_NAME" or expected_type == "NAME":
        cand_name = prompt.strip()
        if _extract_location(cand_name) or any(
            c in cand_name.lower() for c in ["colombo", "kandy", "galle", "mawanella", "jaffna", "negombo", "dehiwala", "nugegoda"]
        ):
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
                cand_name
                and cand_name.lower() not in ["hi", "hello", "1", "2", "3"]
                and not any(w in cand_name.lower() for w in ["actually", "have", "packet", "meals", "change", "curry", "rice", "bread"])
                and not re.search(r"\d", cand_name)
            )
            if is_name_candidate:
                draft_update = {"donor_name": cand_name, "business_name": cand_name}
                if phone:
                    existing_draft = database.save_draft_donation(phone, draft_update)
                    database.create_or_update_user(phone=phone, display_name=cand_name)

    elif curr_q in ["CITY", "DISTRICT"] or expected_type in ["CITY", "DISTRICT"]:

        dist_res = routing.resolve_district(prompt)
        extracted_city = _extract_location(prompt) or voice_service.extract_donation_entities(prompt).get("city") or dist_res
        if extracted_city:
            draft_update = {"city": extracted_city, "location": extracted_city, "district": dist_res or extracted_city}
            if phone:
                existing_draft = database.save_draft_donation(phone, draft_update)
        elif (
            len(prompt.strip().split()) <= 4
            and not any(w in prompt.lower() for w in ["rice", "meal", "packet", "food", "have", "curry", "bread"])
            and not re.search(r"\d", prompt)
        ):
            cand_city = prompt.strip()
            draft_update = {"city": cand_city, "location": cand_city, "district": dist_res or cand_city}
            if phone:
                existing_draft = database.save_draft_donation(phone, draft_update)

    elif curr_q == "DEADLINE" or expected_type == "DEADLINE":
        deadline_match = re.search(r"(?:before|until|by|at)?\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)", prompt, re.IGNORECASE)
        time_val = deadline_match.group(1).strip().upper() if (deadline_match and deadline_match.group(1)) else prompt.strip()
        if "PM" not in time_val and "AM" not in time_val and re.match(r"^\d{1,2}$", time_val):
            time_val = f"Today before {time_val} PM"
        elif "before" in prompt.lower() and not time_val.lower().startswith("today"):
            time_val = f"Today before {time_val}"
        if phone:
            existing_draft = database.save_draft_donation(phone, {"pickup_deadline": time_val})

    elif curr_q == "FOOD_TYPE" or expected_type == "FOOD_CHOICE":
        opt_map = {"1": "Rice & Curry", "2": "Bread & Bakery", "3": "Vegetarian Meals", "4": "Biryani", "5": "Prepared Meals"}
        chosen_food = None
        if "1 and 3" in clean_p or "1 & 3" in clean_p or "1, 3" in clean_p or "1,3" in clean_p:
            chosen_food = "Rice & Vegetarian Meals"
        elif "1 and 2" in clean_p or "1 & 2" in clean_p:
            chosen_food = "Rice & Bread"
        elif clean_p in opt_map:
            chosen_food = opt_map[clean_p]
        elif any(
            b in clean_p
            for b in [
                "chicken biryani",
                "mutton biryani",
                "beef biryani",
                "veg biryani",
                "vegetable biryani",
                "egg biryani",
                "fish biryani",
                "dum biryani",
            ]
        ):
            m_b = re.search(r"\b((?:chicken|mutton|beef|veg|vegetable|egg|fish|dum)?\s*biryani)\b", clean_p, re.IGNORECASE)
            chosen_food = m_b.group(1).strip().title() if m_b else "Biryani"
        elif "biryani" in clean_p or "briyani" in clean_p or "biriyani" in clean_p:
            chosen_food = "Biryani"
        elif "fried rice" in clean_p:
            chosen_food = "Fried Rice"
        elif "kottu" in clean_p or "koththu" in clean_p or "kothu" in clean_p:
            chosen_food = "Kottu Roti"
        elif "noodles" in clean_p or "pasta" in clean_p:
            chosen_food = "Noodles & Pasta"
        elif "rice" in clean_p and "curry" in clean_p:
            chosen_food = "Rice & Curry"
        elif "rice" in clean_p or clean_p in ["බත්", "சோறு", "சாதம்"]:
            chosen_food = "Rice"
        elif "bread" in clean_p or "bakery" in clean_p:
            chosen_food = "Bread & Bakery"
        else:
            chosen_food = prompt.strip().title()

        if chosen_food:
            draft_update = {"food_type": chosen_food}
            if phone:
                existing_draft = database.save_draft_donation(phone, draft_update)

    elif curr_q == "QUANTITY" or expected_type == "QUANTITY":
        m_num = re.search(r"\b(\d+(?:\.\d+)?)\b", prompt)
        if m_num:
            qty_val = float(m_num.group(1))
            draft_update = {"quantity": qty_val}
            m_unit = re.search(
                r"\b(packets?|meals?|boxes?|portions?|kg|kilograms?|plates?|servings?|trays?|containers?|bags?|parcels?|පාර්සල්|පැකට්|පැකට්ටු|කොටස්|பொதிகள்|பாக்கெட்டுகள்|பங்குகள்)\b",
                prompt,
                re.IGNORECASE,
            )
            if m_unit:
                draft_update["unit"] = m_unit.group(1).lower()
            elif "portion" in clean_p or "plate" in clean_p or "serving" in clean_p:
                draft_update["unit"] = "portions"
            elif "box" in clean_p or "tray" in clean_p:
                draft_update["unit"] = "boxes"
            elif "meal" in clean_p:
                draft_update["unit"] = "meals"
            elif "kg" in clean_p:
                draft_update["unit"] = "kg"
            else:
                draft_update["unit"] = existing_draft.get("unit") or "portions"
            if phone:
                existing_draft = database.save_draft_donation(phone, draft_update)

    # 9c. General Entity Extraction on natural messages
    if curr_q not in ["LANGUAGE_MENU", "WHATSAPP_LOCATION"] and not prompt.strip().isdigit() and prompt.strip() not in ["1", "2", "3", "4", "5", "6"]:
        entities = voice_service.extract_donation_entities(prompt)
        draft_patch = {}
        is_correction = any(w in clean_p for w in ["actually", "change", "instead", "not", "correct", "update", "rather"])

        if entities.get("food_type") and (not existing_draft.get("food_type") or is_correction):
            draft_patch["food_type"] = entities["food_type"]
        if entities.get("quantity") is not None and (not existing_draft.get("quantity") or is_correction or "have" in clean_p):
            draft_patch["quantity"] = entities["quantity"]
            if entities.get("unit"):
                draft_patch["unit"] = entities["unit"]
        if entities.get("city") and (
            not existing_draft.get("city")
            or is_correction
            or "city" in clean_p
            or "location" in clean_p
            or "pickup" in clean_p
            or "in " in clean_p
            or "at " in clean_p
        ):
            draft_patch["city"] = entities["city"]
            draft_patch["location"] = entities["city"]
        if entities.get("pickup_deadline") and (
            not existing_draft.get("pickup_deadline")
            or is_correction
            or "time" in clean_p
            or "deadline" in clean_p
            or "before" in clean_p
            or "until" in clean_p
        ):
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
                    phone=phone,
                )

    elif (curr_q in ["WHATSAPP_LOCATION", "LOCATION"] or expected_type == "LOCATION") and not loc_received:
        cand_text = prompt.strip()
        if not re.search(r"^(?:cancel|stop|menu)\b", clean_p):
            coords = routing.extract_coordinates_from_text(cand_text)
            if coords:
                existing_draft = database.save_draft_donation(phone, {"latitude": coords[0], "longitude": coords[1], "location_received": True})
                loc_received = True
            else:
                if _extract_location(cand_text):
                    loc_ext = _extract_location(cand_text)
                    existing_draft = database.save_draft_donation(phone, {"city": loc_ext, "address": cand_text})
                if phone:
                    database.set_user_conversation_state(
                        phone, {"workflow": "DONATION", "current_question": "WHATSAPP_LOCATION", "expected_input_type": "LOCATION"}
                    )
                return translation_service.get_localized_message("location_pin_required_reminder", lang=lang)

    # Refresh draft from DB before slot evaluation
    if phone:
        db_draft = database.get_draft_donation(phone)
        if db_draft:
            existing_draft = db_draft

    # 9d. If User Pressed "1" or says "I want to donate" with no draft yet, prompt for food:
    if (clean_p in ["1", "donate", "i want to donate", "donate food", "i have food", "පරිත්‍යාග", "தானம்"]) and not existing_draft.get("food_type"):
        if phone:
            database.update_user_profile(phone=phone, user_role="donor")
            database.set_user_conversation_state(
                phone,
                {
                    "workflow": "DONATION",
                    "current_question": "FOOD_TYPE",
                    "expected_input_type": "FOOD_CHOICE",
                    "available_options": {"1": "Rice & Curry", "2": "Bread & Bakery", "3": "Vegetarian Meals", "4": "Biryani", "5": "Other"},
                },
            )
        return translation_service.get_localized_message("donation_ask_food_type", lang=lang)

    # 9e. Persistent State Resolution & Strict Ordering for Missing Slots
    food_val = existing_draft.get("food_type")
    qty_val = existing_draft.get("quantity")
    unit_val = existing_draft.get("unit", "packets")
    donor_name_val = (
        existing_draft.get("donor_name")
        or (donor.get("name") if donor else None)
        or (user.get("display_name") if user and not user.get("display_name", "").startswith("User_") else None)
    )
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
    loc_received = bool(existing_draft.get("location_received") or (existing_draft.get("latitude") and existing_draft.get("longitude")))

    # If all other slots (food, qty, city, deadline) were provided all-in-one, default donor name
    if not donor_name_val and (city_val and deadline_val):
        donor_name_val = "Donor Partner"
        business_name_val = "Donor Partner"

    # Step 0: Role-aware guard - Don't route registered volunteers or organizations into donor slot filling
    if (vol_rec or (user and user.get("user_role") == "volunteer")) and not existing_draft.get("food_type"):
        vol_area = (vol_rec.get("service_area") if vol_rec else None) or (user.get("default_location") if user else "your area")
        vol_name = (vol_rec.get("name") if vol_rec else None) or (user.get("display_name") if user else "Volunteer")
        return (
            f"🚚 *Welcome, {vol_name}!* (Volunteer Courier — {vol_area})\n\n"
            f"Reply with:\n"
            f"1️⃣ View available tasks\n"
            f"2️⃣ Check active delivery status\n"
            f"3️⃣ Mark myself as AVAILABLE\n"
            f"4️⃣ Change language (භාෂාව / மொழி)\n\n"
            f"*Or reply with any question about your volunteer tasks!*"
        )

    if (org_rec or (user and user.get("user_role") == "organization")) and not existing_draft.get("food_type"):
        org_area = (org_rec.get("location") if org_rec else None) or (user.get("default_location") if user else "your area")
        org_name = (org_rec.get("name") if org_rec else None) or (user.get("display_name") if user else "Organization")
        return (
            f"🏢 *Welcome, {org_name}!* (Recipient Organization — {org_area})\n\n"
            f"Reply with:\n"
            f"1️⃣ Request surplus food donation\n"
            f"2️⃣ Track incoming food deliveries\n"
            f"3️⃣ Update daily portion capacity\n"
            f"4️⃣ Change language (භාෂාව / மொழி)\n\n"
            f"*Or ask any question about available food donations!*"
        )

    # Step 1: Missing Food Type or Quantity
    if not food_val:
        if phone:
            database.set_user_conversation_state(
                phone, {"workflow": "DONATION", "current_question": "FOOD_TYPE", "expected_input_type": "FOOD_CHOICE"}
            )
        return translation_service.get_localized_message("donation_ask_food_type_simple", lang=lang)

    if qty_val is None or float(qty_val) <= 0:
        if phone:
            database.set_user_conversation_state(phone, {"workflow": "DONATION", "current_question": "QUANTITY", "expected_input_type": "QUANTITY"})
        return translation_service.get_localized_message("slot_ask_quantity", lang=lang, food_type=food_val)

    # Step 2: Missing Donor Name / Business Name
    if not donor_name_val:
        if phone:
            database.set_user_conversation_state(phone, {"workflow": "DONATION", "current_question": "DONOR_NAME", "expected_input_type": "NAME"})
        return translation_service.get_localized_message("donor_ask_name", lang=lang, quantity=qty_val, unit=unit_val, food_type=food_val)

    # Step 3: Missing District
    if not city_val:
        if phone:
            database.set_user_conversation_state(phone, {"workflow": "DONATION", "current_question": "DISTRICT", "expected_input_type": "DISTRICT"})
        return translation_service.get_localized_message(
            "donor_ask_district", lang=lang, name=donor_name_val, quantity=qty_val, unit=unit_val, food_type=food_val
        )

    # Step 4: Missing Food Pickup Deadline (Prompt for deadline if not provided)
    if not deadline_val and not loc_received:
        if phone:
            database.set_user_conversation_state(phone, {"workflow": "DONATION", "current_question": "DEADLINE", "expected_input_type": "DEADLINE"})
        return translation_service.get_localized_message("donor_ask_deadline", lang=lang, city=city_val or "your area")

    # Step 5: Missing Exact WhatsApp Location Pin (MANDATORY before summary / confirmation)
    if not loc_received:
        if phone:
            database.set_user_conversation_state(
                phone, {"workflow": "DONATION", "current_question": "WHATSAPP_LOCATION", "expected_input_type": "LOCATION"}
            )
        return translation_service.get_localized_message(
            "donor_ask_location_native",
            lang=lang,
            quantity=qty_val or 20,
            unit=unit_val or "packets",
            food_type=food_val or "Food",
            city=city_val or "Sri Lanka",
            donor_name=donor_name_val or "Friend",
        )

    # Step 5: All fields present (Food, Qty, Name, District, Live Location Pin) -> Show Summary Confirmation!
    if phone:
        database.set_user_conversation_state(
            phone, {"workflow": "DONATION", "current_question": "CONFIRMATION", "expected_input_type": "CONFIRMATION"}
        )

    final_deadline = deadline_val or "Immediate"
    return translation_service.get_localized_message(
        "donation_summary_confirm",
        lang=lang,
        donor_name=donor_name_val,
        business_name=business_name_val,
        food_type=food_val,
        quantity=qty_val,
        unit=unit_val,
        city=city_val,
        deadline=final_deadline,
        contact_phone=phone,
    )


async def run_resilient_chat(prompt: str, session_id: str, preferred_agent: Optional[str] = None) -> Dict[str, Any]:
    """Execute chat request through stateful coordinator engine and resilient LLM model pool."""
    phone = session_id.split("whatsapp:", 1)[1] if "whatsapp:" in session_id else ""
    clean_p = prompt.strip().lower()

    # Check if there is an active workflow, draft, or domain intent
    active_draft = database.get_draft_donation(phone) if phone else None
    conv_state = database.get_user_conversation_state(phone) if phone else {}
    has_active_state = bool(
        (active_draft and active_draft.get("food_type")) or conv_state.get("workflow") in ["DONATION", "VOLUNTEER", "RECIPIENT", "LANGUAGE"]
    )

    is_greeting = translation_service.is_greeting_message(clean_p)
    if is_greeting and not has_active_state:
        logger.info(f"[Greeting Engine] Executing greeting/welcome for session '{session_id}' with prompt: '{prompt[:60]}'")
        fallback_result = await execute_deterministic_fallback(prompt, session_id)
        return {
            "status": "success",
            "result": fallback_result,
            "agent_used": "foodrescue_coordinator",
            "model_used": "stateful_coordinator_engine",
            "session_id": session_id,
        }

    is_domain_intent = (
        any(
            w in clean_p
            for w in [
                "donate",
                "food",
                "packet",
                "meals",
                "rice",
                "curry",
                "bread",
                "biryani",
                "volunteer",
                "courier",
                "available",
                "free now",
                "free",
                "ready",
                "i can help",
                "accept",
                "reject",
                "collected",
                "delivered",
                "need food",
                "request food",
                "organization",
                "shelter",
                "community",
                "confirm",
                "cancel",
                "status",
                "pickup",
                "where is",
                "track",
                "language",
                "භාෂාව",
                "மொழி",
                "english",
                "sinhala",
                "tamil",
                "සිංහල",
                "தமிழ்",
                "actually",
                "change",
                "before",
                "until",
                "pm",
                "am",
                "mawanella",
                "colombo",
                "kandy",
                "galle",
                "name is",
                "my name",
                "hope food",
                "kamal",
                "three-wheeler",
                "three wheeler",
                "three wheeler",
                "motorbike",
                "car",
            ]
        )
        or clean_p in ["1", "2", "3", "4", "5", "6", "yes", "no", "ok", "confirm", "accept", "reject", "collected", "delivered"]
        or len(clean_p.split()) <= 4
    )

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

            req = BaseChatRequest(agent=agent_name, prompt=prompt, session_id=session_id)
            # Cap individual agent execution at 8.0s to avoid hanging on slow retries
            chat_result = await asyncio.wait_for(chat_service.process_async_chat_request(req), timeout=8.0)

            if isinstance(chat_result, dict):
                reply_text = chat_result.get("result", "")
            else:
                reply_text = str(chat_result)

            # If the response contains an unhandled rate limit or agent execution failure message, rotate model
            if not reply_text or any(
                m in reply_text.lower()
                for m in [
                    "quota exceeded",
                    "resource_exhausted",
                    "too many requests",
                    "429",
                    "no api key",
                    "error processing",
                    "encountered an error",
                    "node failed",
                    "dynamic node",
                ]
            ):
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
        "notice": "Served via high-reliability fallback engine during peak LLM rate limit window.",
    }
