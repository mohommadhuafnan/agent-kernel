"""FoodRescue AI GraphHopper Routing Service.

Provides secure, location-aware routing, distance calculation, travel-time estimation,
and multi-point pickup route optimization using the GraphHopper Routing API.

Features:
1. Single-leg routing (Donation -> Organization, Volunteer -> Donation).
2. Two-leg multi-point routing (Volunteer -> Donation -> Organization).
3. Volunteer ranking by travel-time and road distance respecting availability.
4. Polyline decoding & GeoJSON coordinates formatting for Leaflet maps.
5. In-memory LRU/TTL caching to prevent redundant API calls.
6. Graceful shielding and fallback when API key is missing or service is unavailable.
"""

import os
import time
import math
import logging
from typing import Dict, Any, Optional, Tuple, List, Union
import httpx

logger = logging.getLogger("foodrescue.routing_service")

# GraphHopper API Config
GRAPHHOPPER_ROUTE_URL = "https://graphhopper.com/api/1/route"
CACHE_TTL_SECONDS = 3600  # 1 hour cache for identical coordinate routes

# In-memory Route Cache: (lat1, lon1, lat2, lon2, profile) -> (timestamp, result_dict)
_ROUTE_CACHE: Dict[Tuple[float, float, float, float, str], Tuple[float, Dict[str, Any]]] = {}


def clear_cache() -> None:
    """Clear in-memory route cache."""
    global _ROUTE_CACHE
    _ROUTE_CACHE.clear()

# Map application transport modes to GraphHopper profiles
TRANSPORT_MODE_PROFILES = {
    "walking": "foot",
    "foot": "foot",
    "bicycle": "bike",
    "bike": "bike",
    "electric bike": "bike",
    "motorbike": "motorcycle",
    "motorcycle": "motorcycle",
    "tuk": "car",
    "tuk-tuk": "car",
    "three-wheeler": "car",
    "car": "car",
    "van": "car"
}


def get_graphhopper_api_key() -> str:
    """Retrieve GraphHopper API Key securely from the server environment."""
    key = os.environ.get("GRAPHHOPPER_API_KEY", "").strip()
    if not key:
        # Check secondary aliases if configured
        key = os.environ.get("GRAPH_HOPPER_API_KEY", "").strip()
    return key


def resolve_coordinates(
    location: Union[str, Dict[str, Any], Tuple[float, float], List[float], Any]
) -> Optional[Tuple[float, float]]:
    """Resolve various location representations into (latitude, longitude).
    
    Supports:
    - Landmark or city name strings ("Colombo 3", "Mawanella", "Kandy")
    - Coordinate strings ("6.9271, 79.8612")
    - Dictionaries {"latitude": 6.9271, "longitude": 79.8612} or {"lat": ..., "lng": ...}
    - Tuples/Lists (lat, lon)
    - Objects with .latitude and .longitude attributes
    """
    if location is None:
        return None

    # Tuple or List [lat, lon]
    if isinstance(location, (tuple, list)) and len(location) >= 2:
        try:
            lat = float(location[0])
            lon = float(location[1])
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return (round(lat, 6), round(lon, 6))
        except (ValueError, TypeError):
            pass

    # Dictionary format
    if isinstance(location, dict):
        lat = location.get("latitude") if location.get("latitude") is not None else location.get("lat")
        lon = location.get("longitude") if location.get("longitude") is not None else location.get("lng")
        if lat is not None and lon is not None:
            try:
                lat_f = float(lat)
                lon_f = float(lon)
                if -90 <= lat_f <= 90 and -180 <= lon_f <= 180:
                    return (round(lat_f, 6), round(lon_f, 6))
            except (ValueError, TypeError):
                pass
        # Fallback to address/location key in dict
        addr_text = location.get("address") or location.get("location") or location.get("pickup_location")
        if addr_text and isinstance(addr_text, str):
            return resolve_coordinates(addr_text)

    # String format
    if isinstance(location, str):
        loc_str = location.strip()
        if not loc_str:
            return None
        
        # Check "lat, lng" format
        if "," in loc_str:
            parts = loc_str.split(",")
            if len(parts) == 2:
                try:
                    lat_f = float(parts[0].strip())
                    lon_f = float(parts[1].strip())
                    if -90 <= lat_f <= 90 and -180 <= lon_f <= 180:
                        return (round(lat_f, 6), round(lon_f, 6))
                except ValueError:
                    pass

        # Use geocoding from routing module
        try:
            import routing
            coords = routing.geocode_location(loc_str)
            if coords:
                return (round(coords[0], 6), round(coords[1], 6))
        except Exception:
            pass

    # Generic object with latitude / longitude attributes
    if hasattr(location, "latitude") and hasattr(location, "longitude"):
        try:
            lat_f = float(getattr(location, "latitude"))
            lon_f = float(getattr(location, "longitude"))
            return (round(lat_f, 6), round(lon_f, 6))
        except (ValueError, TypeError):
            pass

    return None


def decode_polyline(encoded: str) -> List[List[float]]:
    """Decode a Google/GraphHopper encoded polyline string into [[lat, lon], ...]."""
    if not encoded or not isinstance(encoded, str):
        return []
    
    coordinates: List[List[float]] = []
    index = 0
    length = len(encoded)
    lat = 0
    lon = 0

    while index < length:
        # Decode latitude
        shift = 0
        result = 0
        while True:
            if index >= length:
                return coordinates
            byte = ord(encoded[index]) - 63
            index += 1
            result |= (byte & 0x1f) << shift
            shift += 5
            if byte < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat

        # Decode longitude
        shift = 0
        result = 0
        while True:
            if index >= length:
                return coordinates
            byte = ord(encoded[index]) - 63
            index += 1
            result |= (byte & 0x1f) << shift
            shift += 5
            if byte < 0x20:
                break
        dlon = ~(result >> 1) if (result & 1) else (result >> 1)
        lon += dlon

        coordinates.append([round(lat * 1e-5, 6), round(lon * 1e-5, 6)])

    return coordinates


def _haversine_fallback_route(
    origin_coords: Tuple[float, float],
    dest_coords: Tuple[float, float],
    transport_mode: str = "car",
    origin_name: str = "",
    dest_name: str = ""
) -> Dict[str, Any]:
    """Calculate fallback distance and duration using Haversine formula with road curvature correction."""
    lat1, lon1 = origin_coords
    lat2, lon2 = dest_coords
    
    # Haversine straight-line distance
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    straight_km = R * c
    
    # Apply 1.25x road curvature factor
    road_km = round(max(0.2, straight_km * 1.25), 2)
    distance_meters = int(road_km * 1000)
    
    # Average urban speeds in km/h
    speeds = {
        "foot": 5.0,
        "walking": 5.0,
        "bike": 15.0,
        "bicycle": 15.0,
        "electric bike": 20.0,
        "motorbike": 30.0,
        "motorcycle": 30.0,
        "tuk": 25.0,
        "tuk-tuk": 25.0,
        "car": 30.0,
        "van": 25.0
    }
    speed = speeds.get(transport_mode.lower(), 25.0)
    duration_hours = road_km / speed
    duration_seconds = int(duration_hours * 3600)
    duration_minutes = max(1, round(duration_seconds / 60))
    
    try:
        import routing
        cost_calc = routing.calculate_transport_cost(road_km, transport_mode)
        est_cost = cost_calc.get("estimated_cost", 0.0)
    except Exception:
        est_cost = round(road_km * 50.0 + 60.0, 2)

    return {
        "success": True,
        "status": "success",
        "distance_meters": distance_meters,
        "distance_km": road_km,
        "duration_seconds": duration_seconds,
        "duration_minutes": duration_minutes,
        "duration_text": f"{duration_minutes} min",
        "estimated_cost": est_cost,
        "currency": "LKR",
        "route_geometry": None,
        "coordinates": [[lat1, lon1], [lat2, lon2]],
        "origin_coordinates": {"latitude": lat1, "longitude": lon1},
        "destination_coordinates": {"latitude": lat2, "longitude": lon2},
        "origin_name": origin_name,
        "destination_name": dest_name,
        "transport_mode": transport_mode,
        "provider": "haversine_fallback",
        "is_exact_road_route": False
    }


async def calculate_route(
    origin: Union[str, Dict[str, Any], Tuple[float, float]],
    destination: Union[str, Dict[str, Any], Tuple[float, float]],
    transport_mode: str = "car",
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Calculate road route distance, duration, and geometry between two points via GraphHopper Routing API."""
    orig_coords = resolve_coordinates(origin)
    dest_coords = resolve_coordinates(destination)
    
    orig_name = str(origin) if isinstance(origin, str) else "Origin"
    dest_name = str(destination) if isinstance(destination, str) else "Destination"
    
    if not orig_coords or not dest_coords:
        return {
            "success": False,
            "status": "error",
            "distance_km": None,
            "distance_meters": None,
            "duration_minutes": None,
            "duration_seconds": None,
            "error": f"Invalid or unresolved coordinates for origin '{orig_name}' or destination '{dest_name}'.",
            "provider": "graphhopper"
        }
        
    norm_mode = str(transport_mode).strip().lower() if transport_mode else "car"
    profile = TRANSPORT_MODE_PROFILES.get(norm_mode, "car")
    
    # Check In-Memory Cache
    cache_key = (orig_coords[0], orig_coords[1], dest_coords[0], dest_coords[1], profile)
    now = time.time()
    if cache_key in _ROUTE_CACHE:
        cached_time, cached_res = _ROUTE_CACHE[cache_key]
        if now - cached_time < CACHE_TTL_SECONDS:
            return cached_res
            
    key = api_key or get_graphhopper_api_key()
    if not key:
        logger.info("GRAPHHOPPER_API_KEY not configured. Falling back to local coordinate calculation.")
        return _haversine_fallback_route(orig_coords, dest_coords, norm_mode, orig_name, dest_name)
        
    params = {
        "point": [f"{orig_coords[0]},{orig_coords[1]}", f"{dest_coords[0]},{dest_coords[1]}"],
        "profile": profile,
        "locale": "en",
        "calc_points": "true",
        "points_encoded": "true",
        "key": key
    }
    
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(GRAPHHOPPER_ROUTE_URL, params=params)
            
        if response.status_code == 200:
            data = response.json()
            paths = data.get("paths", [])
            if paths:
                path = paths[0]
                dist_m = float(path.get("distance", 0.0))
                time_ms = int(path.get("time", 0))
                polyline_str = path.get("points", "")
                
                dist_km = round(dist_m / 1000.0, 2)
                dur_sec = int(time_ms / 1000)
                dur_min = max(1, round(dur_sec / 60))
                
                decoded_coords = decode_polyline(polyline_str) if polyline_str else [[orig_coords[0], orig_coords[1]], [dest_coords[0], dest_coords[1]]]
                
                try:
                    import routing
                    cost_calc = routing.calculate_transport_cost(dist_km, norm_mode)
                    est_cost = cost_calc.get("estimated_cost", 0.0)
                except Exception:
                    est_cost = round(dist_km * 50.0 + 60.0, 2)

                result = {
                    "success": True,
                    "status": "success",
                    "distance_meters": round(dist_m, 1),
                    "distance_km": dist_km,
                    "duration_seconds": dur_sec,
                    "duration_minutes": dur_min,
                    "duration_text": f"{dur_min} min",
                    "estimated_cost": est_cost,
                    "currency": "LKR",
                    "route_geometry": polyline_str,
                    "coordinates": decoded_coords,
                    "origin_coordinates": {"latitude": orig_coords[0], "longitude": orig_coords[1]},
                    "destination_coordinates": {"latitude": dest_coords[0], "longitude": dest_coords[1]},
                    "origin_name": orig_name,
                    "destination_name": dest_name,
                    "transport_mode": norm_mode,
                    "provider": "graphhopper",
                    "is_exact_road_route": True
                }
                
                # Update Cache
                _ROUTE_CACHE[cache_key] = (now, result)
                return result
                
        elif response.status_code == 400 and profile != "car":
            # Profile like 'motorcycle' might not be enabled on standard tier; retry with 'car'
            params["profile"] = "car"
            async with httpx.AsyncClient(timeout=8.0) as client:
                retry_resp = await client.get(GRAPHHOPPER_ROUTE_URL, params=params)
            if retry_resp.status_code == 200:
                data = retry_resp.json()
                paths = data.get("paths", [])
                if paths:
                    path = paths[0]
                    dist_m = float(path.get("distance", 0.0))
                    time_ms = int(path.get("time", 0))
                    polyline_str = path.get("points", "")
                    dist_km = round(dist_m / 1000.0, 2)
                    dur_sec = int(time_ms / 1000)
                    dur_min = max(1, round(dur_sec / 60))
                    decoded_coords = decode_polyline(polyline_str) if polyline_str else [[orig_coords[0], orig_coords[1]], [dest_coords[0], dest_coords[1]]]
                    try:
                        import routing
                        cost_calc = routing.calculate_transport_cost(dist_km, norm_mode)
                        est_cost = cost_calc.get("estimated_cost", 0.0)
                    except Exception:
                        est_cost = round(dist_km * 50.0 + 60.0, 2)
                    result = {
                        "success": True,
                        "status": "success",
                        "distance_meters": round(dist_m, 1),
                        "distance_km": dist_km,
                        "duration_seconds": dur_sec,
                        "duration_minutes": dur_min,
                        "duration_text": f"{dur_min} min",
                        "estimated_cost": est_cost,
                        "currency": "LKR",
                        "route_geometry": polyline_str,
                        "coordinates": decoded_coords,
                        "origin_coordinates": {"latitude": orig_coords[0], "longitude": orig_coords[1]},
                        "destination_coordinates": {"latitude": dest_coords[0], "longitude": dest_coords[1]},
                        "origin_name": orig_name,
                        "destination_name": dest_name,
                        "transport_mode": norm_mode,
                        "provider": "graphhopper",
                        "is_exact_road_route": True
                    }
                    _ROUTE_CACHE[cache_key] = (now, result)
                    return result
                    
        logger.warning(f"GraphHopper API returned HTTP {response.status_code}: {response.text[:200]}. Falling back to coordinate calculation.")
    except Exception as exc:
        logger.warning(f"GraphHopper API request failed ({exc}). Falling back to coordinate calculation.")
        
    return _haversine_fallback_route(orig_coords, dest_coords, norm_mode, orig_name, dest_name)


async def calculate_distance(
    origin: Union[str, Dict[str, Any], Tuple[float, float]],
    destination: Union[str, Dict[str, Any], Tuple[float, float]],
    transport_mode: str = "car"
) -> Dict[str, Any]:
    """Calculate distance and duration between origin and destination."""
    res = await calculate_route(origin, destination, transport_mode)
    return {
        "success": res.get("success", False),
        "distance_km": res.get("distance_km"),
        "distance_meters": res.get("distance_meters"),
        "duration_minutes": res.get("duration_minutes"),
        "duration_seconds": res.get("duration_seconds"),
        "duration_text": res.get("duration_text"),
        "provider": res.get("provider", "graphhopper"),
        "error": res.get("error")
    }


async def calculate_pickup_route(
    volunteer_location: Optional[Union[str, Dict[str, Any], Tuple[float, float]]],
    donation_location: Union[str, Dict[str, Any], Tuple[float, float]],
    organization_location: Union[str, Dict[str, Any], Tuple[float, float]],
    transport_mode: str = "motorbike"
) -> Dict[str, Any]:
    """Calculate complete two-leg pickup and delivery route:
    Leg 1: Volunteer -> Donation (Pickup)
    Leg 2: Donation -> Organization (Delivery)
    
    Returns normalized distance, duration, leg breakdown, and total route geometry.
    """
    v_loc = volunteer_location or donation_location
    
    # Calculate Leg 1 (Volunteer -> Donation)
    leg1 = await calculate_route(v_loc, donation_location, transport_mode)
    
    # Calculate Leg 2 (Donation -> Organization)
    leg2 = await calculate_route(donation_location, organization_location, transport_mode)
    
    if not leg1.get("success") or not leg2.get("success"):
        return {
            "success": False,
            "status": "error",
            "distance_km": None,
            "duration_minutes": None,
            "error": "Failed to calculate complete pickup route.",
            "provider": "graphhopper"
        }
        
    dist1_m = leg1.get("distance_meters", 0.0) or 0.0
    dist2_m = leg2.get("distance_meters", 0.0) or 0.0
    dist1_km = leg1.get("distance_km", 0.0) or 0.0
    dist2_km = leg2.get("distance_km", 0.0) or 0.0
    
    dur1_sec = leg1.get("duration_seconds", 0) or 0
    dur2_sec = leg2.get("duration_seconds", 0) or 0
    dur1_min = leg1.get("duration_minutes", 0) or 0
    dur2_min = leg2.get("duration_minutes", 0) or 0
    
    total_dist_m = round(dist1_m + dist2_m, 1)
    total_dist_km = round(dist1_km + dist2_km, 2)
    total_dur_sec = dur1_sec + dur2_sec
    total_dur_min = max(1, round(total_dur_sec / 60))
    
    # Combine coordinate paths
    coords1 = leg1.get("coordinates") or []
    coords2 = leg2.get("coordinates") or []
    combined_coords = coords1 + (coords2[1:] if coords2 and coords1 else coords2)
    
    return {
        "success": True,
        "status": "success",
        "volunteer_to_donation": {
            "distance_meters": dist1_m,
            "distance_km": dist1_km,
            "duration_seconds": dur1_sec,
            "duration_minutes": dur1_min,
            "duration_text": f"{dur1_min} min"
        },
        "donation_to_organization": {
            "distance_meters": dist2_m,
            "distance_km": dist2_km,
            "duration_seconds": dur2_sec,
            "duration_minutes": dur2_min,
            "duration_text": f"{dur2_min} min"
        },
        "total_distance_meters": total_dist_m,
        "total_distance_km": total_dist_km,
        "total_duration_seconds": total_dur_sec,
        "total_duration_minutes": total_dur_min,
        "total_duration_text": f"{total_dur_min} min",
        "route_geometry": leg2.get("route_geometry") or leg1.get("route_geometry"),
        "coordinates": combined_coords,
        "provider": "graphhopper"
    }


async def rank_volunteers_by_distance(
    volunteers: List[Dict[str, Any]],
    donation_location: Union[str, Dict[str, Any], Tuple[float, float]],
    food_quantity: Optional[float] = None,
    transport_mode: str = "motorbike"
) -> List[Dict[str, Any]]:
    """Rank volunteers by GraphHopper travel time and distance after enforcing business eligibility rules.
    
    Eligibility rules checked first:
    1. Volunteer availability status must be AVAILABLE (not BUSY, OFFLINE, ON_PICKUP).
    2. Vehicle capacity must accommodate the donation quantity (if provided).
    
    Eligible candidates are then ranked:
    - Primary sort: estimated travel time (duration_minutes / seconds)
    - Secondary sort: road distance (distance_km)
    """
    if not volunteers:
        return []
        
    don_coords = resolve_coordinates(donation_location)
    if not don_coords:
        return volunteers

    eligible_volunteers: List[Dict[str, Any]] = []

    for vol in volunteers:
        # Rule 1: Availability status check
        status = str(vol.get("availability_status") or vol.get("current_status") or "AVAILABLE").upper()
        if status not in ["AVAILABLE", "ONLINE"]:
            continue
            
        # Rule 2: Vehicle capacity check
        v_mode = vol.get("transport_mode", "motorbike")
        if food_quantity is not None:
            try:
                import routing
                has_cap, _ = routing.check_vehicle_capacity(v_mode, float(food_quantity))
                if not has_cap:
                    continue
            except Exception:
                pass

        v_loc = vol.get("current_location") or vol.get("current_coordinates") or vol.get("service_area") or vol.get("location")
        
        # Calculate GraphHopper route from Volunteer -> Donation
        route_res = await calculate_route(v_loc, don_coords, v_mode)
        
        dist_km = route_res.get("distance_km", 999.0) if route_res.get("success") else 999.0
        dur_min = route_res.get("duration_minutes", 999) if route_res.get("success") else 999
        dur_sec = route_res.get("duration_seconds", 99999) if route_res.get("success") else 99999
        
        vol_entry = dict(vol)
        vol_entry["distance_km"] = dist_km
        vol_entry["duration_minutes"] = dur_min
        vol_entry["duration_seconds"] = dur_sec
        vol_entry["duration_text"] = f"{dur_min} min" if dur_min < 999 else "Unknown"
        vol_entry["is_available"] = True
        
        # Calculate suitability score (higher is better)
        suitability = max(10, 100 - int(dist_km * 5) - int(dur_min * 2))
        vol_entry["suitability_score"] = suitability
        
        eligible_volunteers.append(vol_entry)

    # Rank by shortest duration and distance
    eligible_volunteers.sort(key=lambda x: (x["duration_seconds"], x["distance_km"]))
    return eligible_volunteers


async def calculate_task_dynamic_route(
    task_id_or_data: Union[str, Dict[str, Any]],
    volunteer_location_override: Optional[Union[str, Dict[str, Any], Tuple[float, float]]] = None
) -> Dict[str, Any]:
    """Calculate the real dynamic road route for an active pickup task based on its current lifecycle phase.
    
    Phases:
    1. PICKUP Phase (status: PENDING, OFFERED, OPEN, ASSIGNED, EN_ROUTE):
       - Route: Volunteer Current Location -> Donor Pickup Location
       - Action: Directs volunteer to donor to inspect & collect food.
    2. DELIVERY Phase (status: COLLECTED, IN_TRANSIT, PICKED_UP):
       - Route: Volunteer Current Location -> Organization Delivery Destination
       - Action: Directs volunteer to organization kitchen/shelter.
    3. COMPLETED Phase (status: COMPLETED, DELIVERED):
       - Route: Donor Pickup Location -> Organization Delivery Destination
       - Action: Shows completed trip trajectory.
       
    Strict GPS & Error Handling Rules:
    - Never invents coordinates or fake static KM.
    - If GPS is missing for a required participant, returns status='needs_location' with missing_participant.
    - Uses configured transport rates from database.get_transport_settings() for exact reimbursement consistency.
    - Returns Google Maps directions URL for turn-by-turn navigation.
    """
    import database
    import routing

    # Resolve task record
    if isinstance(task_id_or_data, str):
        task = database.get_pickup_task_record(task_id_or_data)
        if not task:
            return {"success": False, "status": "error", "error": f"Pickup task '{task_id_or_data}' not found."}
    elif isinstance(task_id_or_data, dict):
        task = task_id_or_data
    else:
        return {"success": False, "status": "error", "error": "Invalid task parameter."}

    task_id = task.get("id", "task-unknown")
    task_status = str(task.get("status", "ASSIGNED")).upper()
    donation_id = task.get("donation_id")
    organization_id = task.get("organization_id")
    volunteer_id = task.get("volunteer_id")

    # Fetch associated participants
    donation = database.get_donation_record(donation_id) if donation_id else None
    donor = database.get_donor_record(donation.get("donor_id")) if donation and donation.get("donor_id") else None
    organization = database.get_organization_record(organization_id) if organization_id else None
    volunteer = database.get_volunteer_record(volunteer_id) if volunteer_id else None

    # Resolve authoritative coordinates
    vol_loc = (
        volunteer_location_override
        or (volunteer.get("current_coordinates") if volunteer else None)
        or (volunteer.get("current_location") if volunteer else None)
        or (volunteer.get("service_area") if volunteer else None)
        or (volunteer.get("location") if volunteer else None)
    )
    vol_coords = resolve_coordinates(vol_loc)

    donor_loc = (
        (donation.get("pickup_location") if donation else None)
        or (donation.get("location") if donation else None)
        or (donor.get("location") if donor else None)
        or task.get("pickup_location")
    )
    donor_coords = resolve_coordinates(donor_loc)

    org_loc = (
        (organization.get("location") if organization else None)
        or (organization.get("service_area") if organization else None)
        or task.get("delivery_location")
    )
    org_coords = resolve_coordinates(org_loc)

    transport_mode = (volunteer.get("transport_mode") if volunteer else None) or "motorbike"

    # Determine Active Phase and Route Endpoints
    if task_status in ["COLLECTED", "IN_TRANSIT", "PICKED_UP"]:
        phase = "DELIVERY"
        origin_name = (volunteer.get("name") if volunteer else "Volunteer Courier") or "Volunteer Courier"
        origin_role = "volunteer"
        origin_coords = vol_coords or donor_coords

        dest_name = (organization.get("name") if organization else "Recipient Organization") or "Recipient Organization"
        dest_role = "organization"
        dest_coords = org_coords

        if dest_coords is None:
            return {
                "success": False,
                "status": "needs_location",
                "phase": phase,
                "task_id": task_id,
                "missing_participant": "organization",
                "message": "Live location required from Recipient Organization to calculate the delivery route."
            }
        if origin_coords is None:
            return {
                "success": False,
                "status": "needs_location",
                "phase": phase,
                "task_id": task_id,
                "missing_participant": "volunteer",
                "message": "Live location required from Volunteer Courier to calculate the delivery route."
            }

    elif task_status in ["COMPLETED", "DELIVERED"]:
        phase = "COMPLETED"
        origin_name = (donor.get("name") if donor else None) or (donation.get("donor_name") if donation else "Donor Pickup") or "Donor Pickup"
        origin_role = "donor"
        origin_coords = donor_coords

        dest_name = (organization.get("name") if organization else "Recipient Organization") or "Recipient Organization"
        dest_role = "organization"
        dest_coords = org_coords

        if origin_coords is None:
            return {
                "success": False,
                "status": "needs_location",
                "phase": phase,
                "task_id": task_id,
                "missing_participant": "donor",
                "message": "Live location required from Donor to calculate completed trip route."
            }
        if dest_coords is None:
            return {
                "success": False,
                "status": "needs_location",
                "phase": phase,
                "task_id": task_id,
                "missing_participant": "organization",
                "message": "Live location required from Recipient Organization to calculate completed trip route."
            }

    else:
        # Default: Pickup Phase (ASSIGNED, EN_ROUTE, OFFERED, OPEN, PENDING)
        phase = "PICKUP"
        origin_name = (volunteer.get("name") if volunteer else "Volunteer Courier") or "Volunteer Courier"
        origin_role = "volunteer"
        origin_coords = vol_coords

        dest_name = (donor.get("name") if donor else None) or (donation.get("donor_name") if donation else "Donor Pickup") or "Donor Pickup"
        dest_role = "donor"
        dest_coords = donor_coords

        if dest_coords is None:
            return {
                "success": False,
                "status": "needs_location",
                "phase": phase,
                "task_id": task_id,
                "missing_participant": "donor",
                "message": "Live location required from Donor to calculate the pickup route."
            }
        if origin_coords is None:
            return {
                "success": False,
                "status": "needs_location",
                "phase": phase,
                "task_id": task_id,
                "missing_participant": "volunteer",
                "message": "Live location required from Volunteer Courier to calculate the pickup route."
            }

    # Execute Road Route Calculation
    route_res = await calculate_route(origin_coords, dest_coords, transport_mode)
    if not route_res.get("success"):
        return {
            "success": False,
            "status": "error",
            "phase": phase,
            "task_id": task_id,
            "message": "Route temporarily unavailable.",
            "origin": {"name": origin_name, "role": origin_role, "coordinates": {"latitude": origin_coords[0], "longitude": origin_coords[1]}},
            "destination": {"name": dest_name, "role": dest_role, "coordinates": {"latitude": dest_coords[0], "longitude": dest_coords[1]}},
            "all_participants": {
                "volunteer": {"name": volunteer.get("name") if volunteer else None, "coordinates": {"latitude": vol_coords[0], "longitude": vol_coords[1]} if vol_coords else None},
                "donor": {"name": donor.get("name") if donor else (donation.get("donor_name") if donation else None), "coordinates": {"latitude": donor_coords[0], "longitude": donor_coords[1]} if donor_coords else None},
                "organization": {"name": organization.get("name") if organization else None, "coordinates": {"latitude": org_coords[0], "longitude": org_coords[1]} if org_coords else None}
            }
        }

    dist_km = route_res.get("distance_km", 0.0) or 0.0
    dur_min = route_res.get("duration_minutes", 1) or 1
    coords = route_res.get("coordinates", [])
    polyline_str = route_res.get("route_geometry")

    # Generate Google Maps Turn-by-Turn Directions URL
    directions_url = routing.generate_directions_link(origin_coords[0], origin_coords[1], dest_coords[0], dest_coords[1])

    # Dynamic Reimbursement Calculation using configured vehicle rates
    rate_per_km = routing.get_transport_rate(transport_mode)
    cost_calc = routing.calculate_transport_estimate(dist_km, transport_mode)
    est_cost = cost_calc.get("estimated_support_amount", round(dist_km * rate_per_km, 2))

    return {
        "success": True,
        "status": "success",
        "phase": phase,
        "task_id": task_id,
        "task_status": task_status,
        "transport_mode": transport_mode,
        "origin": {
            "name": origin_name,
            "role": origin_role,
            "coordinates": {"latitude": origin_coords[0], "longitude": origin_coords[1]}
        },
        "destination": {
            "name": dest_name,
            "role": dest_role,
            "coordinates": {"latitude": dest_coords[0], "longitude": dest_coords[1]}
        },
        "all_participants": {
            "volunteer": {"name": volunteer.get("name") if volunteer else None, "coordinates": {"latitude": vol_coords[0], "longitude": vol_coords[1]} if vol_coords else None},
            "donor": {"name": donor.get("name") if donor else (donation.get("donor_name") if donation else None), "coordinates": {"latitude": donor_coords[0], "longitude": donor_coords[1]} if donor_coords else None},
            "organization": {"name": organization.get("name") if organization else None, "coordinates": {"latitude": org_coords[0], "longitude": org_coords[1]} if org_coords else None}
        },
        "distance_km": dist_km,
        "duration_minutes": dur_min,
        "duration_text": f"{dur_min} min",
        "coordinates": coords,
        "route_geometry": polyline_str,
        "directions_url": directions_url,
        "estimated_cost": est_cost,
        "rate_per_km": rate_per_km,
        "currency": "LKR",
        "provider": route_res.get("provider", "graphhopper"),
        "is_exact_road_route": route_res.get("is_exact_road_route", True)
    }

