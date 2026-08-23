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

# 25 Administrative Districts of Sri Lanka
SRI_LANKA_DISTRICTS = [
    "Colombo",
    "Gampaha",
    "Kalutara",
    "Kandy",
    "Matale",
    "Nuwara Eliya",
    "Galle",
    "Matara",
    "Hambantota",
    "Jaffna",
    "Kilinochchi",
    "Mannar",
    "Vavuniya",
    "Mullaitivu",
    "Batticaloa",
    "Ampara",
    "Trincomalee",
    "Kurunegala",
    "Puttalam",
    "Anuradhapura",
    "Polonnaruwa",
    "Badulla",
    "Monaragala",
    "Ratnapura",
    "Kegalle",
]

# Mapping Sri Lankan towns/suburbs to their primary district
TOWN_TO_DISTRICT_MAP: Dict[str, str] = {
    # Kegalle District
    "kegalle": "Kegalle",
    "mawanella": "Kegalle",
    "rambukkana": "Kegalle",
    "ruwanwella": "Kegalle",
    "warakapola": "Kegalle",
    "yatiyantota": "Kegalle",
    "dehiowita": "Kegalle",
    "deraniyagala": "Kegalle",
    "galigamuwa": "Kegalle",
    "aranayaka": "Kegalle",
    "bulathkohupitiya": "Kegalle",
    # Kandy District
    "kandy": "Kandy",
    "peradeniya": "Kandy",
    "katugastota": "Kandy",
    "gampola": "Kandy",
    "nawalapitiya": "Kandy",
    "kundasale": "Kandy",
    "digana": "Kandy",
    "akurana": "Kandy",
    "wattegama": "Kandy",
    "gelioya": "Kandy",
    "kadugannawa": "Kandy",
    # Colombo District
    "colombo": "Colombo",
    "colombo 1": "Colombo",
    "colombo 2": "Colombo",
    "colombo 3": "Colombo",
    "colombo 4": "Colombo",
    "colombo 5": "Colombo",
    "colombo 6": "Colombo",
    "colombo 7": "Colombo",
    "colombo 8": "Colombo",
    "colombo 9": "Colombo",
    "colombo 10": "Colombo",
    "colombo 11": "Colombo",
    "colombo 12": "Colombo",
    "colombo 13": "Colombo",
    "colombo 14": "Colombo",
    "colombo 15": "Colombo",
    "kollupitiya": "Colombo",
    "bambalapitiya": "Colombo",
    "wellawatte": "Colombo",
    "cinnamon gardens": "Colombo",
    "borella": "Colombo",
    "havelock town": "Colombo",
    "dehiwala": "Colombo",
    "mount lavinia": "Colombo",
    "nugegoda": "Colombo",
    "kotte": "Colombo",
    "rajagiriya": "Colombo",
    "battaramulla": "Colombo",
    "moratuwa": "Colombo",
    "maharagama": "Colombo",
    "homagama": "Colombo",
    "kolonnawa": "Colombo",
    "malabe": "Colombo",
    "kaduwela": "Colombo",
    "piliyandala": "Colombo",
    "kesbewa": "Colombo",
    "boralesgamuwa": "Colombo",
    "ratmalana": "Colombo",
    "fort": "Colombo",
    # Gampaha District
    "gampaha": "Gampaha",
    "negombo": "Gampaha",
    "katunayake": "Gampaha",
    "wattala": "Gampaha",
    "kelaniya": "Gampaha",
    "ja-ela": "Gampaha",
    "ja ela": "Gampaha",
    "kiribathgoda": "Gampaha",
    "kadawatha": "Gampaha",
    "minuwangoda": "Gampaha",
    "divulapitiya": "Gampaha",
    "mirigama": "Gampaha",
    "veyangoda": "Gampaha",
    "ragama": "Gampaha",
    "kandana": "Gampaha",
    "seeduwa": "Gampaha",
    # Kalutara District
    "kalutara": "Kalutara",
    "panadura": "Kalutara",
    "horana": "Kalutara",
    "beruwala": "Kalutara",
    "matugama": "Kalutara",
    "wadduwa": "Kalutara",
    "bandaragama": "Kalutara",
    "aluthgama": "Kalutara",
    # Galle District
    "galle": "Galle",
    "hikkaduwa": "Galle",
    "karapitiya": "Galle",
    "ambalangoda": "Galle",
    "bentota": "Galle",
    "elpitiya": "Galle",
    "baddegama": "Galle",
    "ahungalla": "Galle",
    # Matara District
    "matara": "Matara",
    "weligama": "Matara",
    "akuressa": "Matara",
    "dickwella": "Matara",
    "hakmana": "Matara",
    "kamburupitiya": "Matara",
    "deniyaya": "Matara",
    # Hambantota District
    "hambantota": "Hambantota",
    "tangalle": "Hambantota",
    "beliatta": "Hambantota",
    "tissamaharama": "Hambantota",
    "ambalantota": "Hambantota",
    "kataragama": "Hambantota",
    # Kurunegala District
    "kurunegala": "Kurunegala",
    "kuliyapitiya": "Kurunegala",
    "narammala": "Kurunegala",
    "wariyapola": "Kurunegala",
    "pannala": "Kurunegala",
    "polgahawela": "Kurunegala",
    "giriulla": "Kurunegala",
    "alawwa": "Kurunegala",
    "ibbagamuwa": "Kurunegala",
    "nikaweratiya": "Kurunegala",
    # Puttalam District
    "puttalam": "Puttalam",
    "chilaw": "Puttalam",
    "wennappuwa": "Puttalam",
    "marawila": "Puttalam",
    "dankotuwa": "Puttalam",
    "anamaduwa": "Puttalam",
    "nattandiya": "Puttalam",
    # Jaffna District
    "jaffna": "Jaffna",
    "chavakachcheri": "Jaffna",
    "point pedro": "Jaffna",
    "nallur": "Jaffna",
    "chunnakam": "Jaffna",
    "valvettithurai": "Jaffna",
    # Kilinochchi, Mannar, Vavuniya, Mullaitivu
    "kilinochchi": "Kilinochchi",
    "mannar": "Mannar",
    "vavuniya": "Vavuniya",
    "mullaitivu": "Mullaitivu",
    # Anuradhapura District
    "anuradhapura": "Anuradhapura",
    "kekirawa": "Anuradhapura",
    "medawachchiya": "Anuradhapura",
    "tambuttegama": "Anuradhapura",
    "eppawala": "Anuradhapura",
    "habarana": "Anuradhapura",
    # Polonnaruwa District
    "polonnaruwa": "Polonnaruwa",
    "kaduruwela": "Polonnaruwa",
    "hingurakgoda": "Polonnaruwa",
    "medirigiriya": "Polonnaruwa",
    # Badulla District
    "badulla": "Badulla",
    "bandarawela": "Badulla",
    "ella": "Badulla",
    "welimada": "Badulla",
    "haputale": "Badulla",
    "mahiyanganaya": "Badulla",
    "hali-ela": "Badulla",
    # Monaragala District
    "monaragala": "Monaragala",
    "wellawaya": "Monaragala",
    "buttala": "Monaragala",
    "bibile": "Monaragala",
    # Ratnapura District
    "ratnapura": "Ratnapura",
    "embilipitiya": "Ratnapura",
    "balangoda": "Ratnapura",
    "pelmadulla": "Ratnapura",
    "kuruwita": "Ratnapura",
    "eheliyagoda": "Ratnapura",
    # Matale District
    "matale": "Matale",
    "dambulla": "Matale",
    "sigiriya": "Matale",
    "ukuwela": "Matale",
    "rattota": "Matale",
    # Nuwara Eliya District
    "nuwara eliya": "Nuwara Eliya",
    "hatton": "Nuwara Eliya",
    "talawakele": "Nuwara Eliya",
    "maskeliya": "Nuwara Eliya",
    "ginigathena": "Nuwara Eliya",
    "kotagala": "Nuwara Eliya",
    # Trincomalee District
    "trincomalee": "Trincomalee",
    "kinniya": "Trincomalee",
    "mutur": "Trincomalee",
    "kantale": "Trincomalee",
    # Batticaloa District
    "batticaloa": "Batticaloa",
    "eravur": "Batticaloa",
    "kattankudy": "Batticaloa",
    "valachchenai": "Batticaloa",
    "kaluwanchikudy": "Batticaloa",
    # Ampara District
    "ampara": "Ampara",
    "kalmunai": "Ampara",
    "sammanthurai": "Ampara",
    "akkaraipattu": "Ampara",
    "pottuvil": "Ampara",
    "sainthamaruthu": "Ampara",
}


def resolve_district(location_or_town_text: Optional[str], fallback_to_raw: bool = False) -> Optional[str]:
    """Resolve a town, city, landmark, or district string to its canonical Sri Lanka District name.
    Examples:
        'Mawanella' -> 'Kegalle'
        'Kegalle' -> 'Kegalle'
        'Peradeniya' -> 'Kandy'
        'Colombo 03' -> 'Colombo'
        'Unknown Area' -> 'Unknown Area' (fallback)
    """
    if not location_or_town_text or not isinstance(location_or_town_text, str):
        return None
    raw = location_or_town_text.strip()
    if not raw:
        return None
    clean = raw.lower()

    # Check direct district match
    for dist in SRI_LANKA_DISTRICTS:
        if dist.lower() == clean or dist.lower() in clean.split() or f"{dist.lower()} district" in clean:
            return dist

    # Check known town mapping (exact, then token match)
    if clean in TOWN_TO_DISTRICT_MAP:
        return TOWN_TO_DISTRICT_MAP[clean]

    import re

    words = re.findall(r"\b[a-zA-Z]{3,}\b", clean)
    for w in words:
        if w in TOWN_TO_DISTRICT_MAP:
            return TOWN_TO_DISTRICT_MAP[w]

    for town, dist in TOWN_TO_DISTRICT_MAP.items():
        if len(town) >= 4 and re.search(r"\b" + re.escape(town) + r"\b", clean):
            return dist

    # Check if text contains coordinates or map URL (e.g. 7.222, 80.474 -> Kegalle)
    coords = extract_coordinates_from_text(raw)
    if coords:
        lat, lng = coords
        # Find nearest known landmark in KNOWN_COORDINATES
        best_dist = float("inf")
        best_name = None
        for name, (k_lat, k_lng) in KNOWN_COORDINATES.items():
            dist_sq = (lat - k_lat) ** 2 + (lng - k_lng) ** 2
            if dist_sq < best_dist:
                best_dist = dist_sq
                best_name = name
        if best_name:
            for dist in SRI_LANKA_DISTRICTS:
                if dist.lower() == best_name.lower() or dist.lower() in best_name.split():
                    return dist
            if best_name in TOWN_TO_DISTRICT_MAP:
                return TOWN_TO_DISTRICT_MAP[best_name]

    if fallback_to_raw:
        return raw.title()
    return None


def resolve_task_district(task: Dict[str, Any]) -> Optional[str]:
    """Resolve the canonical Sri Lanka District for a pickup task from its metadata or donation record."""
    if not task or not isinstance(task, dict):
        return None
    # 1. Direct task district
    if task.get("district"):
        res = resolve_district(task["district"])
        if res:
            return res
    # 2. Check task donation
    don_id = task.get("donation_id")
    if don_id:
        try:
            import database

            don = database.get_donation_record(don_id)
            if don:
                res = resolve_district(don.get("district") or don.get("pickup_location") or don.get("location"))
                if res:
                    return res
        except Exception:
            pass
    # 3. Check pickup_location
    if task.get("pickup_location"):
        res = resolve_district(task["pickup_location"])
        if res:
            return res
    # 4. Check delivery_location
    if task.get("delivery_location"):
        res = resolve_district(task["delivery_location"])
        if res:
            return res
    return None


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
    "peradeniya": (7.2660, 80.5970),
    "matale": (7.4675, 80.6234),
    "dambulla": (7.8731, 80.6517),
    "galle": (6.0535, 80.2210),
    "matara": (5.9549, 80.5550),
    "mawanella": (7.2513, 80.4432),
    "kegalle": (7.2520, 80.3464),
    "kurunegala": (7.4863, 80.3623),
    "jaffna": (9.6615, 80.0255),
    "kilinochchi": (9.3803, 80.3770),
    "vavuniya": (8.7542, 80.4982),
    "mannar": (8.9810, 79.9044),
    "mullaitivu": (9.2671, 80.8142),
    "anuradhapura": (8.3114, 80.4037),
    "polonnaruwa": (7.9403, 81.0188),
    "trincomalee": (8.5874, 81.2152),
    "batticaloa": (7.7310, 81.6747),
    "ampara": (7.2912, 81.6724),
    "badulla": (6.9934, 81.0550),
    "bandarawela": (6.8333, 80.9833),
    "monaragala": (6.8728, 81.3507),
    "nuwara eliya": (6.9497, 80.7891),
    "ratnapura": (6.6828, 80.4037),
    "hambantota": (6.1429, 81.1212),
    "puttalam": (8.0362, 79.8283),
    "chilaw": (7.5758, 79.7953),
    "katunayake": (7.1695, 79.8906),
    "gampaha": (7.0917, 79.9997),
    "wattala": (6.9895, 79.8913),
    "kelaniya": (6.9553, 79.9194),
    "battaramulla": (6.8996, 79.9197),
    "moratuwa": (6.7730, 79.8816),
    "panadura": (6.7132, 79.9074),
    "kalutara": (6.5854, 79.9607),
}


def extract_coordinates_from_text(text: str) -> Optional[Tuple[float, float]]:
    """Extract latitude and longitude from Google Maps URLs, query strings, or raw coordinate text.
    Examples:
        'https://maps.google.com/maps?q=7.2222819328308105%2C80.47478485107422&z=17&hl=en' -> (7.22228, 80.47478)
        'https://maps.google.com/maps/search/Mawanella/@7.221711158752441,80.4827651977539,17z?hl=en' -> (7.22171, 80.48277)
        '7.2221811, 80.4749281' -> (7.22218, 80.47493)
    """
    if not text or not isinstance(text, str):
        return None
    import re
    import urllib.parse

    decoded = urllib.parse.unquote(text)

    # 1. Check Google Maps @lat,lng pattern (e.g. @7.2217111,80.4827652)
    at_match = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", decoded)
    if at_match:
        try:
            lat = float(at_match.group(1))
            lng = float(at_match.group(2))
            if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
                return (lat, lng)
        except (ValueError, TypeError):
            pass

    # 2. Check q=lat,lng or query=lat,lng or ll=lat,lng pattern
    q_match = re.search(r"(?:q|query|ll)=(-?\d+\.\d+)(?:%2C|,)(-?\d+\.\d+)", decoded)
    if q_match:
        try:
            lat = float(q_match.group(1))
            lng = float(q_match.group(2))
            if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
                return (lat, lng)
        except (ValueError, TypeError):
            pass

    # 3. Check raw lat, lng coordinates in text (e.g. 7.2221811, 80.4749281)
    coord_match = re.search(r"(-?\d{1,2}\.\d{3,})\s*,\s*(-?\d{1,3}\.\d{3,})", decoded)
    if coord_match:
        try:
            lat = float(coord_match.group(1))
            lng = float(coord_match.group(2))
            if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
                return (lat, lng)
        except (ValueError, TypeError):
            pass

    return None


def geocode_location(location_text: str) -> Optional[Tuple[float, float]]:
    """Resolve landmark name, address string, or 'lat, lng' format to (latitude, longitude)."""
    if not location_text:
        return None

    # Check URL or raw coordinate extraction first
    extracted = extract_coordinates_from_text(location_text)
    if extracted:
        return extracted

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
    try:
        import database

        cfg = database.get_transport_settings()
        rates = cfg.get("rates_by_vehicle") or {}
        for k, v in rates.items():
            if k.lower() == norm_mode:
                return float(v)
            if k.lower() in ["three-wheeler", "tuk", "tuk-tuk"] and norm_mode in ["three-wheeler", "tuk", "tuk-tuk"]:
                return float(v)
    except Exception:
        pass
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


def calculate_haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two points in kilometers using Haversine formula."""
    R = 6371.0  # Earth's radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)


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
        return {"status": "error", "message": "distance_km must be a valid non-negative number."}

    if dist < 0:
        return {"status": "error", "message": "distance_km cannot be negative."}

    norm_mode = str(transport_mode).strip().lower() if transport_mode else "motorbike"
    if norm_mode not in SUPPORTED_TRANSPORT_MODES:
        return {
            "status": "error",
            "message": f"Unsupported transport_mode '{transport_mode}'. Supported modes: {sorted(list(SUPPORTED_TRANSPORT_MODES))}",
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
        "notice": "Estimated volunteer travel reimbursement — accounting ledger estimate only, no monetary payment processed.",
    }


def calculate_transport_estimate(
    distance_km: float,
    transport_mode: str = "motorbike",
    base_fare: Optional[float] = None,
    reimbursement_pct: float = 1.0,
    waiting_charge: float = 0.0,
    tolls: float = 0.0,
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
            "message": f"Unsupported transport_mode '{transport_mode}'. Supported modes: {sorted(list(SUPPORTED_TRANSPORT_MODES))}",
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
        "notice": "Estimated volunteer travel reimbursement support (accounting ledger estimate only).",
    }


class RouteProvider(ABC):
    """Abstract Base Class for route computation providers."""

    @abstractmethod
    async def compute_route(self, origin: str, destination: str, transport_mode: str = "motorbike") -> Dict[str, Any]:
        """Compute distance, duration, and geometry between origin and destination."""
        pass


class HaversineRouteProvider(RouteProvider):
    """Local offline route provider using spherical Haversine formula and landmark coordinates."""

    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate great-circle distance between two points in kilometers."""
        R = 6371.0  # Earth's radius in km
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    async def compute_route(self, origin: str, destination: str, transport_mode: str = "motorbike") -> Dict[str, Any]:
        origin_coords = geocode_location(origin)
        dest_coords = geocode_location(destination)
        norm_mode = str(transport_mode).strip().lower() if transport_mode else "motorbike"

        if not origin_coords or not dest_coords:
            return {
                "status": "error",
                "message": f"Route distance cannot be calculated because coordinates for '{origin}' or '{destination}' are unavailable.",
                "origin": origin,
                "destination": destination,
                "provider": "haversine_fallback",
            }

        # Straight-line distance with a 1.25x road-curvature correction factor
        straight_km = self._haversine_distance(origin_coords[0], origin_coords[1], dest_coords[0], dest_coords[1])
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
            "is_road_exact": False,
        }


class GraphHopperRouteProvider(RouteProvider):
    """Real road routing provider using GraphHopper Routing API."""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("GRAPHHOPPER_API_KEY", "").strip() or os.environ.get("GRAPH_HOPPER_API_KEY", "").strip()

    async def compute_route(self, origin: str, destination: str, transport_mode: str = "motorbike") -> Dict[str, Any]:
        import routing_service

        res = await routing_service.calculate_route(origin, destination, transport_mode, api_key=self._api_key)
        if res.get("success"):
            dist_km = res.get("distance_km", 0.0) or 0.0
            cost_calc = calculate_transport_cost(dist_km, transport_mode)
            res["estimated_cost"] = cost_calc.get("estimated_cost", 0.0)
            res["currency"] = "LKR"
            return res

        fallback = HaversineRouteProvider()
        return await fallback.compute_route(origin, destination, transport_mode)


# Global Route Service Dispatcher
def get_route_provider() -> RouteProvider:
    """Instantiate the active route provider based on environment configuration."""
    api_key = os.environ.get("GRAPHHOPPER_API_KEY", "").strip() or os.environ.get("GRAPH_HOPPER_API_KEY", "").strip()
    if api_key:
        return GraphHopperRouteProvider(api_key=api_key)
    return HaversineRouteProvider()


async def calculate_route(origin: str, destination: str, transport_mode: str = "motorbike") -> Dict[str, Any]:
    """Calculate road route distance, duration, and cost estimation."""
    provider = get_route_provider()
    return await provider.compute_route(origin, destination, transport_mode)


async def compute_two_leg_route(
    volunteer_location: Optional[str], pickup_location: str, delivery_location: str, transport_mode: str = "motorbike"
) -> Dict[str, Any]:
    """Compute two-leg logistics metrics:
    Leg 1: Volunteer / Origin -> Donor Pickup Location
    Leg 2: Donor Pickup Location -> Recipient Destination
    """
    import routing_service

    norm_mode = str(transport_mode).strip().lower() if transport_mode else "motorbike"
    v_loc = volunteer_location if volunteer_location and str(volunteer_location).strip() else pickup_location

    pickup_res = await routing_service.calculate_pickup_route(v_loc, pickup_location, delivery_location, norm_mode)

    total_dist = pickup_res.get("total_distance_km", 0.0) or 0.0
    total_dur_min = pickup_res.get("total_duration_minutes", 0) or 0
    leg1 = pickup_res.get("volunteer_to_donation", {})
    leg2 = pickup_res.get("donation_to_organization", {})

    cost_est = calculate_transport_estimate(total_dist, norm_mode)

    return {
        "status": "success",
        "transport_mode": norm_mode,
        "leg1_pickup": {
            "origin": v_loc,
            "destination": pickup_location,
            "distance_km": leg1.get("distance_km", 0.0),
            "duration_minutes": leg1.get("duration_minutes", 5),
            "route_status": "success",
        },
        "leg2_delivery": {
            "origin": pickup_location,
            "destination": delivery_location,
            "distance_km": leg2.get("distance_km", 0.0),
            "duration_minutes": leg2.get("duration_minutes", 10),
            "route_status": "success",
        },
        "total_distance_km": total_dist,
        "total_duration_minutes": total_dur_min,
        "total_duration_text": f"{total_dur_min} min",
        "estimated_transport_cost": cost_est.get("estimated_support_amount", 0.0),
        "currency": "LKR",
        "route_geometry": pickup_res.get("route_geometry"),
        "coordinates": pickup_res.get("coordinates"),
        "provider": pickup_res.get("provider", "graphhopper"),
        "display_text": f"Leg 1: {leg1.get('distance_km', 0.0)} km | Leg 2: {leg2.get('distance_km', 0.0)} km | Total: {total_dist} km (~{total_dur_min} min) | Support: LKR {int(cost_est.get('estimated_support_amount', 0.0))}",
    }


# Backward compatibility alias
GoogleRoutesProvider = GraphHopperRouteProvider


def generate_map_link(latitude: float, longitude: float) -> str:
    """Generate a map search link for a single coordinate pin."""
    return f"https://www.google.com/maps/search/?api=1&query={latitude:.6f},{longitude:.6f}"


def generate_directions_link(origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float) -> str:
    """Generate a turn-by-turn directions URL between two coordinates."""
    return f"https://www.google.com/maps/dir/?api=1&origin={origin_lat:.6f},{origin_lng:.6f}&destination={dest_lat:.6f},{dest_lng:.6f}"
