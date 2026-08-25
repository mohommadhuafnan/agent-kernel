"""FoodRescue AI MCP Location Tools.

Exposes real-time GPS location lookup for Donors, Organizations, and Volunteers
reusing the unified FoodRescue database and location services without fake data.
"""

import logging
from typing import Optional, Dict, Any
import database
import routing

logger = logging.getLogger("foodrescue.mcp.location")


async def get_live_location(user_id: str, role: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve a registered user's most recent live GPS coordinates and location metadata.

    Args:
        user_id: Phone number or unique user identifier.
        role: Optional role hint ('donor', 'organization', 'volunteer').

    Returns:
        Dictionary containing real latitude, longitude, district, address, and map link.
    """
    clean_id = str(user_id).strip()
    logger.info(f"MCP_TOOL_CALLED: get_live_location for user '{clean_id}' (role: {role})")

    # 1. Check user profile metadata for live coordinates
    user = database.get_user_by_phone(clean_id)
    if user:
        user_role = role or user.get("user_role") or "user"
        meta = user.get("metadata") or {}
        if meta.get("latitude") is not None and meta.get("longitude") is not None:
            try:
                lat = float(meta["latitude"])
                lng = float(meta["longitude"])
                logger.info(f"MCP_TOOL_SUCCESS: get_live_location found in user profile for '{clean_id}'")
                return {
                    "status": "success",
                    "user_id": clean_id,
                    "role": user_role,
                    "latitude": lat,
                    "longitude": lng,
                    "address": user.get("default_location") or meta.get("address") or "",
                    "district": meta.get("district") or routing.resolve_district(user.get("default_location")) or "",
                    "map_link": routing.generate_map_link(lat, lng),
                    "timestamp": user.get("last_seen_at") or ""
                }
            except (ValueError, TypeError):
                pass

    # 2. Check active conversation state / draft
    conv = database.get_user_conversation_state(clean_id) or {}
    if conv.get("latitude") is not None and conv.get("longitude") is not None:
        try:
            lat = float(conv["latitude"])
            lng = float(conv["longitude"])
            logger.info(f"MCP_TOOL_SUCCESS: get_live_location found in active conversation state for '{clean_id}'")
            return {
                "status": "success",
                "user_id": clean_id,
                "role": role or conv.get("workflow", "user").lower(),
                "latitude": lat,
                "longitude": lng,
                "address": conv.get("city") or conv.get("district") or "",
                "district": conv.get("district") or "",
                "map_link": routing.generate_map_link(lat, lng),
                "timestamp": ""
            }
        except (ValueError, TypeError):
            pass

    # 3. Check role-specific records (Donor, Organization, Volunteer)
    if role == "donor" or not role:
        d = database.get_donor_by_phone(clean_id) or database.get_donor_record(clean_id)
        if d and d.get("location"):
            coords = routing.geocode_location(d["location"])
            if coords:
                lat, lng = coords
                return {
                    "status": "success",
                    "user_id": clean_id,
                    "role": "donor",
                    "latitude": lat,
                    "longitude": lng,
                    "address": d["location"],
                    "district": routing.resolve_district(d["location"]) or "",
                    "map_link": routing.generate_map_link(lat, lng),
                    "timestamp": ""
                }

    if role == "organization" or not role:
        org = database.get_organization_by_phone(clean_id) or database.get_organization_record(clean_id)
        if org and (org.get("location") or org.get("service_area")):
            loc_str = org.get("location") or org.get("service_area")
            coords = routing.geocode_location(loc_str)
            if coords:
                lat, lng = coords
                return {
                    "status": "success",
                    "user_id": clean_id,
                    "role": "organization",
                    "latitude": lat,
                    "longitude": lng,
                    "address": loc_str,
                    "district": routing.resolve_district(loc_str) or "",
                    "map_link": routing.generate_map_link(lat, lng),
                    "timestamp": ""
                }

    if role == "volunteer" or not role:
        vol = database.get_volunteer_by_phone(clean_id) or database.get_volunteer_record(clean_id)
        if vol:
            cur_coords = vol.get("current_coordinates") or {}
            if cur_coords.get("latitude") is not None and cur_coords.get("longitude") is not None:
                lat = float(cur_coords["latitude"])
                lng = float(cur_coords["longitude"])
                return {
                    "status": "success",
                    "user_id": clean_id,
                    "role": "volunteer",
                    "latitude": lat,
                    "longitude": lng,
                    "address": vol.get("current_location") or vol.get("service_area") or "",
                    "district": routing.resolve_district(vol.get("service_area")) or "",
                    "map_link": routing.generate_map_link(lat, lng),
                    "timestamp": ""
                }
            loc_str = vol.get("service_area") or vol.get("location") or vol.get("current_location")
            if loc_str:
                coords = routing.geocode_location(loc_str)
                if coords:
                    lat, lng = coords
                    return {
                        "status": "success",
                        "user_id": clean_id,
                        "role": "volunteer",
                        "latitude": lat,
                        "longitude": lng,
                        "address": loc_str,
                        "district": routing.resolve_district(loc_str) or "",
                        "map_link": routing.generate_map_link(lat, lng),
                        "timestamp": ""
                    }

    logger.warning(f"MCP_TOOL_FAILURE: No GPS coordinates found for user '{clean_id}'")
    return {
        "status": "not_found",
        "user_id": clean_id,
        "message": f"No live GPS coordinates or location record found for user '{clean_id}'."
    }
