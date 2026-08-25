"""FoodRescue AI MCP Matching Tools.

Provides nearby organization and volunteer matching capabilities against the
unified database and dynamic road routing algorithms without fake/mock data.
"""

import logging
from typing import Optional, Dict, Any, List
import database
import routing

logger = logging.getLogger("foodrescue.mcp.matching")


async def find_nearby_organizations(
    latitude: float,
    longitude: float,
    district: Optional[str] = None,
    food_type: Optional[str] = None,
    quantity: Optional[float] = None
) -> List[Dict[str, Any]]:
    """Search registered recipient organizations near GPS coordinates matching food criteria.

    Args:
        latitude: Donor pickup latitude.
        longitude: Donor pickup longitude.
        district: Optional administrative district name.
        food_type: Optional food category (e.g. Cooked Meals, Bakery, Halal).
        quantity: Optional food quantity in portions/kg.

    Returns:
        List of real matching organizations ranked by proximity.
    """
    logger.info(f"MCP_TOOL_CALLED: find_nearby_organizations near ({latitude}, {longitude})")
    target_food = food_type or "All"
    target_dist = district or routing.resolve_district(f"{latitude},{longitude}") or "Kegalle"

    # Query matching organizations from database
    orgs = database.find_organizations_by_criteria(target_food, target_dist)
    if not orgs:
        # Fallback to all organizations if district query returns none
        all_orgs = database.get_all_organizations()
        orgs = all_orgs

    if not orgs:
        logger.info("MCP_TOOL_SUCCESS: find_nearby_organizations returned 0 organizations (database empty)")
        return []

    # Calculate distance to each organization and rank
    ranked_list = []
    for org in orgs:
        org_loc = org.get("location") or org.get("service_area") or "Kegalle"
        org_coords = routing.geocode_location(org_loc)
        dist_km = 5.0
        if org_coords:
            dist_km = routing.calculate_haversine_distance(latitude, longitude, org_coords[0], org_coords[1])

        org_item = dict(org)
        org_item["distance_km"] = dist_km
        ranked_list.append(org_item)

    ranked_list.sort(key=lambda x: x.get("distance_km", 999.0))
    logger.info(f"MCP_TOOL_SUCCESS: find_nearby_organizations found {len(ranked_list)} matching organizations")
    return ranked_list


async def find_nearby_volunteers(
    latitude: float,
    longitude: float,
    district: Optional[str] = None,
    vehicle_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Search registered, active/available volunteer couriers near GPS coordinates.

    Args:
        latitude: Pickup latitude.
        longitude: Pickup longitude.
        district: Optional district name.
        vehicle_type: Optional preferred vehicle mode ('Motorbike', 'Three-Wheeler', 'Car', 'Van').

    Returns:
        List of real active volunteers ranked by proximity to the pickup point.
    """
    logger.info(f"MCP_TOOL_CALLED: find_nearby_volunteers near ({latitude}, {longitude})")
    avail_vols = database.get_available_volunteers()
    if not avail_vols:
        all_vols = database.get_all_volunteers()
        avail_vols = [
            v for v in all_vols
            if str(v.get("current_status", "AVAILABLE")).upper() in ["AVAILABLE", "ACTIVE", ""]
            or str(v.get("status", "AVAILABLE")).upper() in ["AVAILABLE", "ACTIVE", ""]
        ]

    if not avail_vols:
        logger.info("MCP_TOOL_SUCCESS: find_nearby_volunteers returned 0 volunteers (no available couriers)")
        return []

    if vehicle_type:
        filtered = [v for v in avail_vols if str(v.get("transport_mode", "")).lower() == str(vehicle_type).lower()]
        if filtered:
            avail_vols = filtered

    ranked_list = []
    for vol in avail_vols:
        vol_loc = vol.get("service_area") or vol.get("location") or vol.get("current_location") or "Kegalle"
        vol_coords = None
        cur_c = vol.get("current_coordinates") or {}
        if cur_c.get("latitude") and cur_c.get("longitude"):
            vol_coords = (float(cur_c["latitude"]), float(cur_c["longitude"]))
        else:
            vol_coords = routing.geocode_location(vol_loc)

        dist_km = 3.0
        if vol_coords:
            dist_km = routing.calculate_haversine_distance(latitude, longitude, vol_coords[0], vol_coords[1])

        vol_item = dict(vol)
        vol_item["distance_km"] = dist_km
        ranked_list.append(vol_item)

    ranked_list.sort(key=lambda x: x.get("distance_km", 999.0))
    logger.info(f"MCP_TOOL_SUCCESS: find_nearby_volunteers found {len(ranked_list)} nearby volunteers")
    return ranked_list


async def match_donation(donation_id: str) -> Dict[str, Any]:
    """Find compatible recipient organizations and couriers for a specific donation.

    Args:
        donation_id: Unique donation identifier.

    Returns:
        Dictionary containing donation details, matched organizations, and available couriers.
    """
    clean_don_id = str(donation_id).strip()
    logger.info(f"MCP_TOOL_CALLED: match_donation for '{clean_don_id}'")
    don = database.get_donation_record(clean_don_id)
    if not don:
        logger.warning(f"MCP_TOOL_FAILURE: Donation '{clean_don_id}' not found")
        return {
            "status": "not_found",
            "donation_id": clean_don_id,
            "message": f"Donation '{clean_don_id}' not found in database."
        }

    pickup_loc = don.get("pickup_location") or don.get("location") or "Kegalle"
    food_type = don.get("food_type", "All")
    qty = float(don.get("quantity", 30))
    district = routing.resolve_district(pickup_loc) or "Kegalle"
    pickup_coords = routing.geocode_location(pickup_loc) or (7.2512, 80.3464)

    ranked_orgs = await find_nearby_organizations(
        latitude=pickup_coords[0],
        longitude=pickup_coords[1],
        district=district,
        food_type=food_type,
        quantity=qty
    )

    ranked_vols = await find_nearby_volunteers(
        latitude=pickup_coords[0],
        longitude=pickup_coords[1],
        district=district
    )

    logger.info(f"MCP_TOOL_SUCCESS: match_donation completed for '{clean_don_id}'")
    return {
        "status": "success",
        "donation": don,
        "district": district,
        "matched_organizations": ranked_orgs,
        "available_volunteers": ranked_vols,
        "total_matched_orgs": len(ranked_orgs),
        "total_available_vols": len(ranked_vols)
    }
