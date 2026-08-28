"""FoodRescue AI MCP Routing & Logistics Tools.

Provides dynamic road distance calculation, multi-leg navigation routing,
and dynamic transport reimbursement calculations using database-configured rates.
"""

import logging
from typing import Optional, Dict, Any
import database
import routing

logger = logging.getLogger("foodrescue.mcp.routing")


async def calculate_route(
    pickup_latitude: float,
    pickup_longitude: float,
    delivery_latitude: float,
    delivery_longitude: float,
    vehicle_type: Optional[str] = "Motorbike"
) -> Dict[str, Any]:
    """Calculate real road distance, duration, and navigation route between pickup and delivery GPS coordinates.

    Args:
        pickup_latitude: Donor pickup latitude.
        pickup_longitude: Donor pickup longitude.
        delivery_latitude: Recipient delivery latitude.
        delivery_longitude: Recipient delivery longitude.
        vehicle_type: Mode of transport ('Motorbike', 'Three-Wheeler', 'Car', 'Van', 'Bicycle').

    Returns:
        Dictionary containing distance in km, duration in minutes, navigation links, and coordinate details.
    """
    logger.info(f"MCP_TOOL_CALLED: calculate_route from ({pickup_latitude}, {pickup_longitude}) to ({delivery_latitude}, {delivery_longitude})")

    origin_str = f"{pickup_latitude},{pickup_longitude}"
    dest_str = f"{delivery_latitude},{delivery_longitude}"
    mode = vehicle_type or "Motorbike"

    route_res = await routing.calculate_route(origin=origin_str, destination=dest_str, transport_mode=mode)
    distance_km = float(route_res.get("distance_km", 5.0))
    duration_sec = route_res.get("duration_seconds", 900)
    duration_mins = round(duration_sec / 60.0, 1) if duration_sec else 15.0
    nav_link = f"https://www.google.com/maps/dir/?api=1&origin={pickup_latitude},{pickup_longitude}&destination={delivery_latitude},{delivery_longitude}"

    logger.info(f"MCP_TOOL_SUCCESS: calculate_route completed: {distance_km} km, {duration_mins} mins")
    return {
        "status": "success",
        "distance_km": round(distance_km, 2),
        "duration_minutes": round(duration_mins, 1),
        "vehicle_type": mode,
        "route_url": nav_link,
        "pickup_location": {
            "latitude": pickup_latitude,
            "longitude": pickup_longitude,
            "map_link": routing.generate_map_link(pickup_latitude, pickup_longitude)
        },
        "delivery_location": {
            "latitude": delivery_latitude,
            "longitude": delivery_longitude,
            "map_link": routing.generate_map_link(delivery_latitude, delivery_longitude)
        }
    }


async def calculate_transport_support(distance_km: float, vehicle_type: str) -> Dict[str, Any]:
    """Calculate dynamic volunteer transport reimbursement based on configured rates.

    Args:
        distance_km: Total road distance in kilometers.
        vehicle_type: Vehicle mode ('Motorbike', 'Three-Wheeler', 'Car', 'Van', 'Bicycle').

    Returns:
        Dictionary containing vehicle type, distance, rate per km, total reimbursement amount in LKR.
    """
    logger.info(f"MCP_TOOL_CALLED: calculate_transport_support for {distance_km} km ({vehicle_type})")
    cost_info = routing.calculate_transport_cost(distance_km=float(distance_km), transport_mode=str(vehicle_type).lower())
    total_lkr = float(cost_info.get("estimated_cost", 350.0))
    rate_per_km = float(cost_info.get("rate_per_km", 70.0))

    logger.info(f"MCP_TOOL_SUCCESS: calculate_transport_support: LKR {total_lkr}")
    return {
        "status": "success",
        "vehicle_type": vehicle_type,
        "distance_km": round(float(distance_km), 2),
        "rate_per_km": round(rate_per_km, 2),
        "transport_support": round(total_lkr, 2),
        "currency": "LKR",
        "formula": f"Base rate ({rate_per_km} LKR/km) × {distance_km} km"
    }


async def calculate_task_metrics(
    donation_id: str,
    organization_id: str,
    volunteer_id: Optional[str] = None
) -> Dict[str, Any]:
    """Compute combined logistical metrics (real coordinates, road distance, duration, transport support).

    Args:
        donation_id: Unique donation identifier.
        organization_id: Unique organization identifier.
        volunteer_id: Optional assigned volunteer identifier.

    Returns:
        Complete task metrics package including pickup details, delivery details, routing, and transport cost.
    """
    logger.info(f"MCP_TOOL_CALLED: calculate_task_metrics (don: {donation_id}, org: {organization_id}, vol: {volunteer_id})")

    don = database.get_donation_record(donation_id)
    org = database.get_organization_record(organization_id)
    vol = database.get_volunteer_record(volunteer_id) if volunteer_id else None

    if not don:
        return {"status": "not_found", "message": f"Donation '{donation_id}' not found."}
    if not org:
        return {"status": "not_found", "message": f"Organization '{organization_id}' not found."}

    pickup_loc = don.get("pickup_location") or don.get("location") or "Colombo"
    delivery_loc = org.get("location") or org.get("service_area") or "Colombo"
    vol_mode = (vol.get("transport_mode") if vol else None) or "Motorbike"

    p_coords = routing.geocode_location(pickup_loc) or (6.9271, 79.8612)
    d_coords = routing.geocode_location(delivery_loc) or (6.9300, 79.8650)

    route_calc = await calculate_route(
        pickup_latitude=p_coords[0],
        pickup_longitude=p_coords[1],
        delivery_latitude=d_coords[0],
        delivery_longitude=d_coords[1],
        vehicle_type=vol_mode
    )

    dist_km = route_calc.get("distance_km", 5.0)
    dur_min = route_calc.get("duration_minutes", 15.0)
    cost_calc = await calculate_transport_support(distance_km=dist_km, vehicle_type=vol_mode)

    logger.info(f"MCP_TOOL_SUCCESS: calculate_task_metrics computed {dist_km} km, LKR {cost_calc.get('transport_support')}")
    return {
        "status": "success",
        "donation_id": donation_id,
        "organization_id": organization_id,
        "volunteer_id": volunteer_id or "",
        "food_info": f"{don.get('quantity', 30)} {don.get('unit', 'portions')} of {don.get('food_type', 'Prepared Meals')}",
        "pickup": {
            "name": don.get("donor_name") or "Donor Partner",
            "location": pickup_loc,
            "latitude": p_coords[0],
            "longitude": p_coords[1],
            "map_link": routing.generate_map_link(p_coords[0], p_coords[1])
        },
        "delivery": {
            "name": org.get("name", "Recipient Organization"),
            "location": delivery_loc,
            "latitude": d_coords[0],
            "longitude": d_coords[1],
            "map_link": routing.generate_map_link(d_coords[0], d_coords[1])
        },
        "distance_km": dist_km,
        "duration_minutes": dur_min,
        "vehicle_type": vol_mode,
        "transport_support": cost_calc.get("transport_support", 350.0),
        "currency": "LKR",
        "directions_link": route_calc.get("route_url")
    }
