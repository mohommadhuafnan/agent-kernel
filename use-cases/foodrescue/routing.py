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
SUPPORTED_TRANSPORT_MODES = {"walking", "bicycle", "electric bike", "motorbike", "tuk", "tuk-tuk", "three-wheeler", "car", "van"}

# Default Transport Reimbursement Rates (LKR per km) - Sri Lanka Market Demo Configuration
DEFAULT_TRANSPORT_RATES = {
    "walking": float(os.environ.get("TRANSPORT_RATE_WALKING", 0.0)),
    "bicycle": float(os.environ.get("TRANSPORT_RATE_BICYCLE", 25.0)),
    "electric bike": float(os.environ.get("TRANSPORT_RATE_ELECTRIC_BIKE", 25.0)),
    "motorbike": float(os.environ.get("TRANSPORT_RATE_MOTORBIKE", 50.0)),
    "tuk": float(os.environ.get("TRANSPORT_RATE_TUK", 90.0)),
    "tuk-tuk": float(os.environ.get("TRANSPORT_RATE_TUKTUK", 90.0)),
    "three-wheeler": float(os.environ.get("TRANSPORT_RATE_TUK", 90.0)),
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
    "three-wheeler": float(os.environ.get("BASE_FARE_TUK", 100.0)),
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
    "three-wheeler": 60,
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
    "three-wheeler": 25.0,
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
    "kitulgala": "Kegalle",
    "aluthnuwara": "Kegalle",
    "ambepussa": "Kegalle",
    "kotiyakumbura": "Kegalle",
    "undugoda": "Kegalle",
    "hettimulla": "Kegalle",
    "pinnawala": "Kegalle",
    "nelundeniya": "Kegalle",
    "hinguloya": "Kegalle",
    "zahira rd": "Kegalle",
    "zahira": "Kegalle",
    "71500": "Kegalle",
    "sabaragamuwa": "Kegalle",
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
    "pilimathalawa": "Kandy",
    "menikhinna": "Kandy",
    "teldeniya": "Kandy",
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
    "delgoda": "Gampaha",
    "biyagama": "Gampaha",
    # Kalutara District
    "kalutara": "Kalutara",
    "panadura": "Kalutara",
    "horana": "Kalutara",
    "beruwala": "Kalutara",
    "matugama": "Kalutara",
    "wadduwa": "Kalutara",
    "bandaragama": "Kalutara",
    "aluthgama": "Kalutara",
    "ingiriya": "Kalutara",
    # Galle District
    "galle": "Galle",
    "hikkaduwa": "Galle",
    "karapitiya": "Galle",
    "ambalangoda": "Galle",
    "bentota": "Galle",
    "elpitiya": "Galle",
    "baddegama": "Galle",
    "ahungalla": "Galle",
    "unawatuna": "Galle",
    # Matara District
    "matara": "Matara",
    "weligama": "Matara",
    "dikwella": "Matara",
    "akuressa": "Matara",
    "mirissa": "Matara",
    "deniyaya": "Matara",
    # Kurunegala District
    "kurunegala": "Kurunegala",
    "kuliyapitiya": "Kurunegala",
    "narammala": "Kurunegala",
    "wariyapola": "Kurunegala",
    "pannala": "Kurunegala",
    "polgahawela": "Kurunegala",
    "alawwa": "Kurunegala",
    "maho": "Kurunegala",
    "giriulla": "Kurunegala",
    "ibbagamuwa": "Kurunegala",
    # Matale District
    "matale": "Matale",
    "dambulla": "Matale",
    "sigiriya": "Matale",
    "galewela": "Matale",
    "naula": "Matale",
    # Nuwara Eliya District
    "nuwara eliya": "Nuwara Eliya",
    "hatton": "Nuwara Eliya",
    "talawakele": "Nuwara Eliya",
    "ragala": "Nuwara Eliya",
    "gampola": "Kandy",
    # Ratnapura District
    "ratnapura": "Ratnapura",
    "embilipitiya": "Ratnapura",
    "balangoda": "Ratnapura",
    "pelmadulla": "Ratnapura",
    "kuruwita": "Ratnapura",
    "eheliyagoda": "Ratnapura",
    # Badulla District
    "badulla": "Badulla",
    "bandarawela": "Badulla",
    "haputale": "Badulla",
    "ella": "Badulla",
    "w強limada": "Badulla",
    "welimada": "Badulla",
    "mahiyanganaya": "Badulla",
    # Anuradhapura District
    "anuradhapura": "Anuradhapura",
    "kekirawa": "Anuradhapura",
    "tambuttegama": "Anuradhapura",
    "medawachchiya": "Anuradhapura",
    "eppawala": "Anuradhapura",
    "habarana": "Anuradhapura",
    # Polonnaruwa District
    "polonnaruwa": "Polonnaruwa",
    "kaduruwela": "Polonnaruwa",
    "hingurakgoda": "Polonnaruwa",
    "medirigiriya": "Polonnaruwa",
    # Jaffna District
    "jaffna": "Jaffna",
    "nallur": "Jaffna",
    "chavakachcheri": "Jaffna",
    "point pedro": "Jaffna",
    "chunnakam": "Jaffna",
    "karainagar": "Jaffna",
    # Batticaloa District
    "batticaloa": "Batticaloa",
    "kattankudy": "Batticaloa",
    "eravur": "Batticaloa",
    "valachchenai": "Batticaloa",
    # Trincomalee District
    "trincomalee": "Trincomalee",
    "kinniya": "Trincomalee",
    "mutur": "Trincomalee",
    "kantale": "Trincomalee",
    # Ampara District
    "ampara": "Ampara",
    "kalmunai": "Ampara",
    "sainthamaruthu": "Ampara",
    "sammanthurai": "Ampara",
    "akkaraipattu": "Ampara",
    # Puttalam District
    "puttalam": "Puttalam",
    "chilaw": "Puttalam",
    "marawila": "Puttalam",
    "dankotuwa": "Puttalam",
    "wennappuwa": "Puttalam",
    "an無いamaduwa": "Puttalam",
    "anamaduwa": "Puttalam",
    # Hambantota District
    "hambantota": "Hambantota",
    "tangalle": "Hambantota",
    "beliatta": "Hambantota",
    "ambalantota": "Hambantota",
    "tissamaharama": "Hambantota",
    # Monaragala District
    "monaragala": "Monaragala",
    "wellawaya": "Monaragala",
    "buttala": "Monaragala",
    "bibile": "Monaragala",
    "kataragama": "Monaragala",
    # Mannar District
    "mannar": "Mannar",
    "nanattan": "Mannar",
    # Vavuniya District
    "vavuniya": "Vavuniya",
    "cheddekulam": "Vavuniya",
    # Kilinochchi District
    "kilinochchi": "Kilinochchi",
    "pallai": "Kilinochchi",
    # Mullaitivu District
    "mullaitivu": "Mullaitivu",
    "pudukuduirippu": "Mullaitivu",
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
    # Kegalle District Localities & Towns
    "kegalle": (7.2520, 80.3464),
    "mawanella": (7.2513, 80.4432),
    "rambukkana": (7.3197, 80.3953),
    "ruwanwella": (7.0422, 80.2528),
    "warakapola": (7.2244, 80.1983),
    "yatiyantota": (6.9833, 80.3167),
    "dehiowita": (6.9667, 80.2667),
    "deraniyagala": (6.9250, 80.3417),
    "galigamuwa": (7.2286, 80.2864),
    "aranayaka": (7.1472, 80.4861),
    "bulathkohupitiya": (7.1167, 80.3833),
    "kitulgala": (6.9944, 80.4167),
    "aluthnuwara": (7.2217, 80.4828),
    "ambepussa": (7.2500, 80.2000),
    "kotiyakumbura": (7.1500, 80.3167),
    "undugoda": (7.1833, 80.4000),
    "hettimulla": (7.2167, 80.3667),
    "pinnawala": (7.3014, 80.3853),
    "nelundeniya": (7.2167, 80.2167),
    "hinguloya": (7.2405, 80.4639),
    "zahira rd": (7.2405, 80.4639),
    "zahira": (7.2405, 80.4639),
    "sabaragamuwa": (7.2520, 80.3464),
    # Kandy District
    "kandy": (7.2906, 80.6337),
    "peradeniya": (7.2660, 80.5970),
    "katugastota": (7.3167, 80.6167),
    "gampola": (7.1647, 80.5750),
    "nawalapitiya": (7.0500, 80.5333),
    "kundasale": (7.2833, 80.6833),
    "digana": (7.3000, 80.7333),
    "akurana": (7.3667, 80.6167),
    "wattegama": (7.3500, 80.6833),
    "gelioya": (7.2167, 80.5833),
    "kadugannawa": (7.2547, 80.5211),
    "pilimathalawa": (7.2667, 80.5500),
    "menikhinna": (7.3000, 80.6833),
    "teldeniya": (7.3167, 80.7667),
    # Colombo District
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
    "colombo 9": (6.9333, 79.8833),
    "colombo 10": (6.9250, 79.8700),
    "colombo 11": (6.9400, 79.8500),
    "colombo 12": (6.9400, 79.8600),
    "colombo 13": (6.9500, 79.8600),
    "colombo 14": (6.9550, 79.8700),
    "colombo 15": (6.9700, 79.8750),
    "dehiwala": (6.8389, 79.8736),
    "mount lavinia": (6.8333, 79.8667),
    "nugegoda": (6.8649, 79.8997),
    "kotte": (6.8872, 79.9186),
    "rajagiriya": (6.9083, 79.8917),
    "battaramulla": (6.8996, 79.9197),
    "malabe": (6.9042, 79.9542),
    "kaduwela": (6.9333, 79.9833),
    "maharagama": (6.8481, 79.9267),
    "homagama": (6.8417, 80.0000),
    "kolonnawa": (6.9333, 79.8833),
    "moratuwa": (6.7730, 79.8816),
    "ratmalana": (6.8219, 79.8789),
    "piliyandala": (6.8000, 79.9167),
    "kesbewa": (6.7833, 79.9500),
    "boralesgamuwa": (6.8433, 79.9017),
    "fort": (6.9344, 79.8428),
    # Gampaha District
    "gampaha": (7.0917, 79.9997),
    "negombo": (7.2083, 79.8358),
    "katunayake": (7.1695, 79.8906),
    "wattala": (6.9895, 79.8913),
    "kelaniya": (6.9553, 79.9194),
    "ja-ela": (7.0750, 79.8917),
    "ja ela": (7.0750, 79.8917),
    "kiribathgoda": (6.9806, 79.9319),
    "kadawatha": (7.0000, 79.9500),
    "minuwangoda": (7.1667, 79.9500),
    "divulapitiya": (7.2167, 80.0167),
    "mirigama": (7.2417, 80.1333),
    "veyangoda": (7.1500, 80.0583),
    "ragama": (7.0250, 79.9167),
    "kandana": (7.0472, 79.8972),
    "seeduwa": (7.1250, 79.8750),
    # Kalutara District
    "kalutara": (6.5854, 79.9607),
    "panadura": (6.7132, 79.9074),
    "horana": (6.7167, 80.0667),
    "beruwala": (6.4781, 79.9828),
    "matugama": (6.5222, 80.1167),
    "wadduwa": (6.6667, 79.9333),
    "bandaragama": (6.7167, 79.9833),
    "aluthgama": (6.4333, 80.0000),
    # Galle & Matara & Southern District
    "galle": (6.0535, 80.2210),
    "hikkaduwa": (6.1394, 80.1064),
    "karapitiya": (6.0667, 80.2333),
    "ambalangoda": (6.2356, 80.0539),
    "bentota": (6.4256, 79.9972),
    "elpitiya": (6.2583, 80.1417),
    "matara": (5.9549, 80.5550),
    "weligama": (5.9750, 80.4250),
    "dikwella": (5.9667, 80.7000),
    "akuressa": (6.1000, 80.4667),
    "mirissa": (5.9481, 80.4578),
    "hambantota": (6.1429, 81.1212),
    "tangalle": (6.0244, 80.7942),
    "tissamaharama": (6.2794, 81.2881),
    # Kurunegala & North Western District
    "kurunegala": (7.4863, 80.3623),
    "kuliyapitiya": (7.4689, 80.0406),
    "narammala": (7.4333, 80.2167),
    "wariyapola": (7.6167, 80.2667),
    "pannala": (7.3333, 79.9833),
    "polgahawela": (7.3333, 80.3000),
    "alawwa": (7.3000, 80.2500),
    "puttalam": (8.0362, 79.8283),
    "chilaw": (7.5758, 79.7953),
    "marawila": (7.4167, 79.8167),
    # Central & Uva & Sabaragamuwa District
    "matale": (7.4675, 80.6234),
    "dambulla": (7.8731, 80.6517),
    "nuwara eliya": (6.9497, 80.7891),
    "hatton": (6.8833, 80.6000),
    "badulla": (6.9934, 81.0550),
    "bandarawela": (6.8333, 80.9833),
    "haputale": (6.7667, 80.9500),
    "ella": (6.8667, 81.0467),
    "welimada": (6.9000, 80.9000),
    "monaragala": (6.8728, 81.3507),
    "ratnapura": (6.6828, 80.4037),
    "embilipitiya": (6.3400, 80.8500),
    "balangoda": (6.6500, 80.7000),
    # North & Eastern Districts
    "anuradhapura": (8.3114, 80.4037),
    "polonnaruwa": (7.9403, 81.0188),
    "jaffna": (9.6615, 80.0255),
    "kilinochchi": (9.3803, 80.3770),
    "vavuniya": (8.7542, 80.4982),
    "mannar": (8.9810, 79.9044),
    "mullaitivu": (9.2671, 80.8142),
    "trincomalee": (8.5874, 81.2152),
    "batticaloa": (7.7310, 81.6747),
    "ampara": (7.2912, 81.6724),
    "kalmunai": (7.4167, 81.8333),
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

    # Check individual words or comma-separated segments exact match first (e.g. "Galigamuwa, Kegalle" -> "galigamuwa")
    import re
    segments = [s.strip() for s in re.split(r"[,/|\-]+", loc_clean) if s.strip()]
    for seg in segments:
        if seg in KNOWN_COORDINATES:
            return KNOWN_COORDINATES[seg]

    # Check partial match on segments
    for seg in segments:
        for name, coords in KNOWN_COORDINATES.items():
            if name == seg or name in seg or seg in name:
                return coords
        if seg in TOWN_TO_DISTRICT_MAP:
            dist = TOWN_TO_DISTRICT_MAP[seg].lower()
            if dist in KNOWN_COORDINATES:
                return KNOWN_COORDINATES[dist]

    # Check partial match on full string
    for name, coords in KNOWN_COORDINATES.items():
        if name == loc_clean or name in loc_clean or loc_clean in name:
            return coords

    # Check district resolution fallback
    dist_resolved = resolve_district(location_text)
    if dist_resolved and dist_resolved.lower() in KNOWN_COORDINATES:
        return KNOWN_COORDINATES[dist_resolved.lower()]

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


def generate_map_link(*args, **kwargs) -> str:
    """Generate a map search link for coordinates or a location query string."""
    import urllib.parse
    if len(args) == 2:
        lat, lng = args
        return f"https://www.google.com/maps/search/?api=1&query={float(lat):.6f},{float(lng):.6f}"
    if len(args) == 1:
        loc = args[0]
        if isinstance(loc, (tuple, list)) and len(loc) >= 2:
            return f"https://www.google.com/maps/search/?api=1&query={float(loc[0]):.6f},{float(loc[1]):.6f}"
        if isinstance(loc, dict) and (loc.get("latitude") or loc.get("lat")):
            lat = loc.get("latitude", loc.get("lat"))
            lng = loc.get("longitude", loc.get("lng"))
            return f"https://www.google.com/maps/search/?api=1&query={float(lat):.6f},{float(lng):.6f}"
        coords = geocode_location(str(loc))
        if coords:
            return f"https://www.google.com/maps/search/?api=1&query={coords[0]:.6f},{coords[1]:.6f}"
        return f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(str(loc).strip())}"
    lat = kwargs.get("latitude") or kwargs.get("lat")
    lng = kwargs.get("longitude") or kwargs.get("lng")
    if lat is not None and lng is not None:
        return f"https://www.google.com/maps/search/?api=1&query={float(lat):.6f},{float(lng):.6f}"
    return "https://maps.google.com"


def generate_directions_link(*args, **kwargs) -> str:
    """Generate a turn-by-turn Google Maps directions URL between two locations.
    
    Supports:
    - 4 floats: generate_directions_link(origin_lat, origin_lng, dest_lat, dest_lng)
    - 2 arguments (strings/coords/dicts): generate_directions_link(origin, destination)
    """
    import urllib.parse

    if len(args) == 4:
        o_lat, o_lng, d_lat, d_lng = args
        return f"https://www.google.com/maps/dir/?api=1&origin={float(o_lat):.6f},{float(o_lng):.6f}&destination={float(d_lat):.6f},{float(d_lng):.6f}"
    
    if len(args) == 2:
        orig, dest = args
        # Check if orig/dest are coords
        o_coords = None
        d_coords = None
        if isinstance(orig, (tuple, list)) and len(orig) >= 2:
            o_coords = (float(orig[0]), float(orig[1]))
        elif isinstance(orig, dict) and (orig.get("latitude") or orig.get("lat")):
            lat = orig.get("latitude", orig.get("lat"))
            lng = orig.get("longitude", orig.get("lng"))
            o_coords = (float(lat), float(lng))
        elif isinstance(orig, str):
            o_coords = geocode_location(orig)

        if isinstance(dest, (tuple, list)) and len(dest) >= 2:
            d_coords = (float(dest[0]), float(dest[1]))
        elif isinstance(dest, dict) and (dest.get("latitude") or dest.get("lat")):
            lat = dest.get("latitude", dest.get("lat"))
            lng = dest.get("longitude", dest.get("lng"))
            d_coords = (float(lat), float(lng))
        elif isinstance(dest, str):
            d_coords = geocode_location(dest)

        if o_coords and d_coords:
            return f"https://www.google.com/maps/dir/?api=1&origin={o_coords[0]:.6f},{o_coords[1]:.6f}&destination={d_coords[0]:.6f},{d_coords[1]:.6f}"
        
        orig_str = urllib.parse.quote(str(orig).strip(), safe="")
        dest_str = urllib.parse.quote(str(dest).strip(), safe="")
        return f"https://www.google.com/maps/dir/?api=1&origin={orig_str}&destination={dest_str}"

    # Fallback to kwargs
    o_lat = kwargs.get("origin_lat") or kwargs.get("origin_latitude")
    o_lng = kwargs.get("origin_lng") or kwargs.get("origin_longitude")
    d_lat = kwargs.get("dest_lat") or kwargs.get("dest_latitude")
    d_lng = kwargs.get("dest_lng") or kwargs.get("dest_longitude")
    if o_lat is not None and o_lng is not None and d_lat is not None and d_lng is not None:
        return f"https://www.google.com/maps/dir/?api=1&origin={float(o_lat):.6f},{float(o_lng):.6f}&destination={float(d_lat):.6f},{float(d_lng):.6f}"

    return "https://maps.google.com"
