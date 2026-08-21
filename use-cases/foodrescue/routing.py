"""FoodRescue AI Routing and Transport Cost Estimation Engine.

Provides:
1. Configurable transport rate calculations by vehicle mode.
2. Abstract RouteProvider interface.
3. GoogleRoutesProvider: Real road routing, durations, and polylines via Google Routes API.
4. HaversineRouteProvider: Approximate straight-line distance, durations, and coordinate fallback.
5. Known landmark geocoordinates registry for Sri Lanka / Colombo.
"""

import os
import math
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple, List
import httpx

logger = logging.getLogger("foodrescue.routing")

# Supported transport modes
SUPPORTED_TRANSPORT_MODES = {"walking", "bicycle", "electric bike", "motorbike", "tuk", "tuk-tuk", "car", "van"}

# Default Transport Reimbursement Rates (LKR per km) - Sri Lanka Market Demo Configuration
DEFAULT_TRANSPORT_RATES = {
    "walking": float(os.environ.get("TRANSPORT_RATE_WALKING", 0.0)),
    "bicycle": float(os.environ.get("TRANSPORT_RATE_BICYCLE", 25.0)),
    "electric bike": float(os.environ.get("TRANSPORT_RATE_ELECTRIC_BIKE", 25.0)),
    "motorbike": float(os.environ.get("TRANSPORT_RATE_MOTORBIKE", 50.0)),
    "tuk": float(os.environ.get("TRANSPORT_RATE_TUK", 90.0)),
    "tuk-tuk": float(os.environ.get("TRANSPORT_RATE_TUKTUK", 90.0)),
    "car": float(os.environ.get("TRANSPORT_RATE_CAR", 80.0)),
    "van": float(os.environ.get("TRANSPORT_RATE_VAN", 120.0)),
}

# Base Fares (LKR)
DEFAULT_BASE_FARES = {
    "walking": 0.0,
    "bicycle": 0.0,
    "electric bike": 0.0,
    "motorbike": float(os.environ.get("BASE_FARE_MOTORBIKE", 50.0)),
    "tuk": float(os.environ.get("BASE_FARE_TUK", 100.0)),
    "tuk-tuk": float(os.environ.get("BASE_FARE_TUKTUK", 100.0)),
    "car": float(os.environ.get("BASE_FARE_CAR", 150.0)),
    "van": float(os.environ.get("BASE_FARE_VAN", 250.0)),
}

# Maximum Meal Portion Capacity by Transport Mode
VEHICLE_MEAL_CAPACITY = {
    "walking": 5,
    "bicycle": 10,
    "electric bike": 10,
    "motorbike": 25,
    "tuk": 60,
    "tuk-tuk": 60,
    "car": 150,
    "van": 500,
}

# Average speeds (km/h) for duration estimates during fallback routing
TRANSPORT_SPEEDS_KMH = {
    "walking": 5.0,
    "bicycle": 15.0,
    "electric bike": 20.0,
    "motorbike": 30.0,
    "tuk": 25.0,
    "tuk-tuk": 25.0,
    "car": 25.0,
    "van": 22.0,
}

# Known Landmark Coordinates (Sri Lanka)
KNOWN_COORDINATES: Dict[str, Tuple[float, float]] = {
    "colombo 1": (6.9344, 79.8428),
    "colombo": (6.9344, 79.8428),
    "colombo 2": (6.9236, 79.8553),
    "colombo 3": (6.9056, 79.8519),
    "kollupitiya": (6.9056, 79.8519),
    "colombo 4": (6.8905, 79.8587),
    "bambalapitiya": (6.8905, 79.8587),
    "colombo 5": (6.8833, 79.8667),
    "havelock town": (6.8833, 79.8667),
    "colombo 6": (6.8744, 79.8603),
    "wellawatte": (6.8744, 79.8603),
    "colombo 7": (6.9069, 79.8708),
    "cinnamon gardens": (6.9069, 79.8708),
    "colombo 8": (6.9167, 79.8833),
    "borella": (6.9167, 79.8833),
    "dehiwala": (6.8389, 79.8736),
    "mount lavinia": (6.8333, 79.8667),
    "nugegoda": (6.8649, 79.8997),
    "kotte": (6.8872, 79.9186),
    "rajagiriya": (6.9083, 79.8917),
    "negombo": (7.2083, 79.8358),
    "kandy": (7.2906, 80.6337),
    "galle": (6.0535, 80.2210),
    "matara": (5.9549, 80.5550),
}


def geocode_location(location_text: str) -> Optional[Tuple[float, float]]:
    """Resolve landmark name, address string, or 'lat, lng' format to (latitude, longitude)."""
    if not location_text:
        return None
    loc_clean = str(location_text).strip().lower()
    
    # Check exact match
    if loc_clean in KNOWN_COORDINATES:
        return KNOWN_COORDINATES[loc_clean]
    
    # Check partial match
    for name, coords in KNOWN_COORDINATES.items():
        if name in loc_clean or loc_clean in name:
            return coords
            
    # Check if raw coordinate format "lat, lng"
    if "," in loc_clean:
        parts = loc_clean.split(",")
        if len(parts) == 2:
            try:
                lat = float(parts[0].strip())
                lng = float(parts[1].strip())
                if -90 <= lat <= 90 and -180 <= lng <= 180:
                    return (lat, lng)
            except ValueError:
                pass
                
    return None


def get_transport_rate(mode: str) -> float:
    """Retrieve the configured per-km reimbursement rate for a transport mode."""
    norm_mode = str(mode).strip().lower() if mode else "motorbike"
    return DEFAULT_TRANSPORT_RATES.get(norm_mode, DEFAULT_TRANSPORT_RATES.get("motorbike", 50.0))


def get_base_fare(mode: str) -> float:
    """Retrieve the base fare for a transport mode."""
    norm_mode = str(mode).strip().lower() if mode else "motorbike"
    return DEFAULT_BASE_FARES.get(norm_mode, 0.0)


def get_vehicle_capacity(mode: str) -> int:
    """Retrieve the maximum meal portion capacity for a transport mode."""
    norm_mode = str(mode).strip().lower() if mode else "motorbike"
    return VEHICLE_MEAL_CAPACITY.get(norm_mode, 25)


def check_vehicle_capacity(mode: str, quantity: float) -> Tuple[bool, int]:
    """Check whether the transport mode has sufficient capacity for the donation quantity."""
    max_cap = get_vehicle_capacity(mode)
    return float(quantity) <= max_cap, max_cap


def generate_map_link(latitude: float, longitude: float, label: Optional[str] = None) -> str:
    """Generate a privacy-safe Google Maps search query link for coordinates."""
    return f"https://www.google.com/maps/search/?api=1&query={latitude:.6f},{longitude:.6f}"


def calculate_transport_cost(distance_km: float, transport_mode: str = "motorbike") -> Dict[str, Any]:
    """Calculate estimated volunteer travel reimbursement for a given distance and vehicle mode.
    
    Returns structured estimate with currency LKR and calculation details.
    """
    try:
        dist = float(distance_km)
    except (ValueError, TypeError):
        return {
            "status": "error",
            "message": "distance_km must be a valid non-negative number."
        }
        
    if dist < 0:
        return {
            "status": "error",
            "message": "distance_km cannot be negative."
        }
        
    norm_mode = str(transport_mode).strip().lower() if transport_mode else "motorbike"
    if norm_mode not in SUPPORTED_TRANSPORT_MODES:
        return {
            "status": "error",
            "message": f"Unsupported transport_mode '{transport_mode}'. Supported modes: {sorted(list(SUPPORTED_TRANSPORT_MODES))}"
        }
        
    rate_per_km = get_transport_rate(norm_mode)
    estimated_cost = round(dist * rate_per_km, 2)
    
    return {
        "status": "success",
        "distance_km": round(dist, 2),
        "transport_mode": norm_mode,
        "rate_per_km": rate_per_km,
        "minimum_charge": 0.0,
        "estimated_cost": estimated_cost,
        "currency": "LKR",
        "notice": "Estimated volunteer travel reimbursement — accounting ledger estimate only, no monetary payment processed."
    }


def calculate_transport_estimate(
    distance_km: float,
    transport_mode: str = "motorbike",
    base_fare: Optional[float] = None,
    reimbursement_pct: float = 1.0,
    waiting_charge: float = 0.0,
    tolls: float = 0.0
) -> Dict[str, Any]:
    """Calculate transparent multi-factor estimated volunteer travel support.
    
    Formula: base_fare + (distance_km * rate_per_km) + waiting_charge + tolls
    Applied with reimbursement_percentage (default 100%).
    """
    try:
        dist = float(distance_km)
    except (ValueError, TypeError):
        return {"status": "error", "message": "distance_km must be a valid non-negative number."}
        
    if dist < 0:
        return {"status": "error", "message": "distance_km cannot be negative."}
        
    norm_mode = str(transport_mode).strip().lower() if transport_mode else "motorbike"
    if norm_mode not in SUPPORTED_TRANSPORT_MODES:
        return {
            "status": "error",
            "message": f"Unsupported transport_mode '{transport_mode}'. Supported modes: {sorted(list(SUPPORTED_TRANSPORT_MODES))}"
        }
        
    rate_per_km = get_transport_rate(norm_mode)
    actual_base = float(base_fare) if base_fare is not None else get_base_fare(norm_mode)
    
    distance_cost = dist * rate_per_km
    gross_cost = actual_base + distance_cost + float(waiting_charge) + float(tolls)
    pct = max(0.0, min(1.0, float(reimbursement_pct)))
    reimbursement_amount = round(gross_cost * pct, 2)
    
    return {
        "status": "success",
        "distance_km": round(dist, 2),
        "transport_mode": norm_mode,
        "base_fare": round(actual_base, 2),
        "rate_per_km": round(rate_per_km, 2),
        "distance_cost": round(distance_cost, 2),
        "waiting_charge": round(waiting_charge, 2),
        "tolls": round(tolls, 2),
        "gross_cost": round(gross_cost, 2),
        "reimbursement_percentage": round(pct * 100, 1),
        "estimated_support_amount": reimbursement_amount,
        "currency": "LKR",
        "display_text": f"Estimated transport support: LKR {int(reimbursement_amount)}",
        "notice": "Estimated volunteer travel reimbursement support (accounting ledger estimate only)."
    }


class RouteProvider(ABC):
    """Abstract Base Class for route computation providers."""

    @abstractmethod
    async def compute_route(
        self,
        origin: str,
        destination: str,
        transport_mode: str = "motorbike"
    ) -> Dict[str, Any]:
        """Compute distance, duration, and geometry between origin and destination."""
        pass


class HaversineRouteProvider(RouteProvider):
    """Local offline route provider using spherical Haversine formula and landmark coordinates."""

    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate great-circle distance between two points in kilometers."""
        R = 6371.0  # Earth's radius in km
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    async def compute_route(
        self,
        origin: str,
        destination: str,
        transport_mode: str = "motorbike"
    ) -> Dict[str, Any]:
        origin_coords = geocode_location(origin)
        dest_coords = geocode_location(destination)
        norm_mode = str(transport_mode).strip().lower() if transport_mode else "motorbike"

        if not origin_coords or not dest_coords:
            return {
                "status": "error",
                "message": f"Route distance cannot be calculated because coordinates for '{origin}' or '{destination}' are unavailable.",
                "origin": origin,
                "destination": destination,
                "provider": "haversine_fallback"
            }

        # Straight-line distance with a 1.25x road-curvature correction factor
        straight_km = self._haversine_distance(
            origin_coords[0], origin_coords[1],
            dest_coords[0], dest_coords[1]
        )
        road_km = round(max(0.5, straight_km * 1.25), 2)
        
        speed = TRANSPORT_SPEEDS_KMH.get(norm_mode, 30.0)
        duration_hours = road_km / speed
        duration_seconds = int(duration_hours * 3600)
        duration_minutes = max(1, round(duration_seconds / 60))
        
        cost_calc = calculate_transport_cost(road_km, norm_mode)

        return {
            "status": "success",
            "origin": origin,
            "origin_coordinates": {"latitude": origin_coords[0], "longitude": origin_coords[1]},
            "destination": destination,
            "destination_coordinates": {"latitude": dest_coords[0], "longitude": dest_coords[1]},
            "distance_km": road_km,
            "duration_seconds": duration_seconds,
            "duration_text": f"{duration_minutes} min",
            "transport_mode": norm_mode,
            "estimated_cost": cost_calc.get("estimated_cost", 0.0),
            "currency": "LKR",
            "geometry": None,  # No fake polyline; straight-line coordinates given
            "provider": "haversine_fallback",
            "is_road_exact": False
        }


class GoogleRoutesProvider(RouteProvider):
    """Real road routing provider using Google Routes API."""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("ROUTING_API_KEY", "").strip()

    def _map_travel_mode(self, mode: str) -> str:
        norm = str(mode).strip().lower()
        if norm in ["bicycle", "electric bike"]:
            return "BICYCLE"
        elif norm == "motorbike":
            return "TWO_WHEELER"
        return "DRIVE"

    async def compute_route(
        self,
        origin: str,
        destination: str,
        transport_mode: str = "motorbike"
    ) -> Dict[str, Any]:
        if not self._api_key:
            logger.info("No ROUTING_API_KEY configured; using HaversineRouteProvider.")
            fallback = HaversineRouteProvider()
            return await fallback.compute_route(origin, destination, transport_mode)

        origin_coords = geocode_location(origin)
        dest_coords = geocode_location(destination)
        norm_mode = str(transport_mode).strip().lower() if transport_mode else "motorbike"

        if not origin_coords or not dest_coords:
            fallback = HaversineRouteProvider()
            return await fallback.compute_route(origin, destination, transport_mode)

        url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline"
        }
        payload = {
            "origin": {
                "location": {
                    "latLng": {
                        "latitude": origin_coords[0],
                        "longitude": origin_coords[1]
                    }
                }
            },
            "destination": {
                "location": {
                    "latLng": {
                        "latitude": dest_coords[0],
                        "longitude": dest_coords[1]
                    }
                }
            },
            "travelMode": self._map_travel_mode(norm_mode),
            "routingPreference": "TRAFFIC_UNAWARE",
            "computeAlternativeRoutes": False,
            "polylineQuality": "OVERVIEW"
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                
            if response.status_code == 200:
                data = response.json()
                routes = data.get("routes", [])
                if routes:
                    route = routes[0]
                    dist_meters = route.get("distanceMeters", 0)
                    dist_km = round(dist_meters / 1000.0, 2)
                    duration_str = route.get("duration", "0s").rstrip("s")
                    try:
                        duration_sec = int(duration_str)
                    except ValueError:
                        duration_sec = 0
                    duration_min = max(1, round(duration_sec / 60))
                    polyline = route.get("polyline", {}).get("encodedPolyline", None)
                    
                    cost_calc = calculate_transport_cost(dist_km, norm_mode)
                    
                    return {
                        "status": "success",
                        "origin": origin,
                        "origin_coordinates": {"latitude": origin_coords[0], "longitude": origin_coords[1]},
                        "destination": destination,
                        "destination_coordinates": {"latitude": dest_coords[0], "longitude": dest_coords[1]},
                        "distance_km": dist_km,
                        "duration_seconds": duration_sec,
                        "duration_text": f"{duration_min} min",
                        "transport_mode": norm_mode,
                        "estimated_cost": cost_calc.get("estimated_cost", 0.0),
                        "currency": "LKR",
                        "geometry": polyline,
                        "provider": "google_routes",
                        "is_road_exact": True
                    }
            logger.warning(f"Google Routes API returned status {response.status_code}. Falling back to Haversine.")
        except Exception as exc:
            logger.warning(f"Google Routes API request exception ({exc}). Falling back to Haversine.")

        # Fallback if request fails
        fallback = HaversineRouteProvider()
        return await fallback.compute_route(origin, destination, transport_mode)


# Global Route Service Dispatcher
def get_route_provider() -> RouteProvider:
    """Instantiate the active route provider based on environment configuration."""
    api_key = os.environ.get("ROUTING_API_KEY", "").strip()
    if api_key:
        return GoogleRoutesProvider(api_key=api_key)
    return HaversineRouteProvider()


async def calculate_route(
    origin: str,
    destination: str,
    transport_mode: str = "motorbike"
) -> Dict[str, Any]:
    """Calculate road route distance, duration, and cost estimation."""
    provider = get_route_provider()
    return await provider.compute_route(origin, destination, transport_mode)


async def compute_two_leg_route(
    volunteer_location: Optional[str],
    pickup_location: str,
    delivery_location: str,
    transport_mode: str = "motorbike"
) -> Dict[str, Any]:
    """Compute two-leg logistics metrics:
    Leg 1: Volunteer / Origin -> Donor Pickup Location
    Leg 2: Donor Pickup Location -> Recipient Destination
    """
    provider = get_route_provider()
    norm_mode = str(transport_mode).strip().lower() if transport_mode else "motorbike"

    # Leg 1: Volunteer/Origin -> Pickup
    leg1_origin = volunteer_location if volunteer_location and str(volunteer_location).strip() else pickup_location
    leg1_res = await provider.compute_route(leg1_origin, pickup_location, norm_mode)
    leg1_dist = leg1_res.get("distance_km", 0.0) if leg1_res.get("status") == "success" else 0.0
    leg1_dur_sec = leg1_res.get("duration_seconds", 0) if leg1_res.get("status") == "success" else 0

    # Leg 2: Pickup -> Delivery
    leg2_res = await provider.compute_route(pickup_location, delivery_location, norm_mode)
    leg2_dist = leg2_res.get("distance_km", 0.0) if leg2_res.get("status") == "success" else 0.0
    leg2_dur_sec = leg2_res.get("duration_seconds", 0) if leg2_res.get("status") == "success" else 0

    total_dist = round(leg1_dist + leg2_dist, 2)
    total_dur_sec = leg1_dur_sec + leg2_dur_sec
    total_dur_min = max(1, round(total_dur_sec / 60))

    cost_est = calculate_transport_estimate(total_dist, norm_mode)

    return {
        "status": "success",
        "transport_mode": norm_mode,
        "leg1_pickup": {
            "origin": leg1_origin,
            "destination": pickup_location,
            "distance_km": leg1_dist,
            "duration_minutes": max(1, round(leg1_dur_sec / 60)) if leg1_dur_sec > 0 else 5,
            "route_status": leg1_res.get("status")
        },
        "leg2_delivery": {
            "origin": pickup_location,
            "destination": delivery_location,
            "distance_km": leg2_dist,
            "duration_minutes": max(1, round(leg2_dur_sec / 60)) if leg2_dur_sec > 0 else 10,
            "route_status": leg2_res.get("status")
        },
        "total_distance_km": total_dist,
        "total_duration_minutes": total_dur_min,
        "total_duration_text": f"{total_dur_min} min",
        "estimated_transport_cost": cost_est.get("estimated_support_amount", 0.0),
        "currency": "LKR",
        "display_text": f"Leg 1: {leg1_dist} km | Leg 2: {leg2_dist} km | Total: {total_dist} km (~{total_dur_min} min) | Support: LKR {int(cost_est.get('estimated_support_amount', 0.0))}"
    }
