"""FoodRescue AI Persistence Delegation Layer.

Dispatches all database operations to the active repository backend
(Supabase PostgreSQL or SQLite) based on the FOODRESCUE_DATABASE environment variable.
"""

import os
import sys
import threading
from typing import List, Dict, Any, Optional
from db_base import BaseRepository

DB_PATH = "foodrescue.db"
_CURRENT_REPO: Optional[BaseRepository] = None
_REPO_LOCK = threading.Lock()


def get_repository() -> BaseRepository:
    """Retrieve the configured repository backend instance (singleton per runtime)."""
    global _CURRENT_REPO
    if _CURRENT_REPO is not None:
        return _CURRENT_REPO

    with _REPO_LOCK:
        if _CURRENT_REPO is not None:
            return _CURRENT_REPO

        backend = (os.environ.get("FOODRESCUE_DATABASE") or os.environ.get("FOODRESCUE_DB_BACKEND", "supabase")).strip().lower()

    if backend in ["mongodb", "mongo"]:
        try:
            from db_mongo import MongoRepository

            mongo_repo = MongoRepository()
            mongo_repo.setup_database()
            _CURRENT_REPO = mongo_repo
            return _CURRENT_REPO
        except Exception as exc:
            import logging

            logging.getLogger("foodrescue.db").warning(f"MongoDB connection notice ({exc}); falling back to local SQLite.")
            from db_sqlite import SQLiteRepository

            _CURRENT_REPO = SQLiteRepository()
            return _CURRENT_REPO

    # Supabase PostgreSQL (Default production backend)
    from db_supabase import SupabaseRepository

    supabase_repo = SupabaseRepository()

    # If Supabase URL is not configured (e.g. offline unit tests without env vars), use local SQLite
    if not supabase_repo._db_url:
        # Prevent silent SQLite fallback in production when Supabase is requested
        if backend == "supabase" and "pytest" not in sys.modules and not os.environ.get("PYTEST_CURRENT_TEST"):
            if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
                raise ValueError("SUPABASE_DB_URL is missing on serverless deployment. Cannot silently fall back to ephemeral SQLite.")

        from db_sqlite import SQLiteRepository

        _CURRENT_REPO = SQLiteRepository()
        return _CURRENT_REPO

    try:
        supabase_repo.setup_database()
    except Exception as exc:
        import logging

        logging.getLogger("foodrescue.db").warning(f"Supabase database setup notice ({exc}); proceeding with Supabase backend.")

    _CURRENT_REPO = supabase_repo
    return _CURRENT_REPO


def set_repository(repo: Optional[BaseRepository]) -> None:
    """Explicitly set or reset the active repository instance (useful for testing)."""
    global _CURRENT_REPO
    _CURRENT_REPO = repo


def reset_repository() -> None:
    """Reset the cached repository singleton so it re-evaluates the environment variable."""
    global _CURRENT_REPO
    with _REPO_LOCK:
        _CURRENT_REPO = None


# Module-level delegation functions


def setup_database() -> None:
    get_repository().setup_database()


def seed_test_data() -> None:
    get_repository().seed_test_data()


def get_donor_record(donor_id: str) -> Optional[Dict[str, Any]]:
    return get_repository().get_donor_record(donor_id)


def get_donor_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    return get_repository().get_donor_by_phone(phone)


def create_donor_record(donor_id: str, name: str, phone: str, location: str, organization_name: Optional[str] = None) -> Dict[str, Any]:
    return get_repository().create_donor_record(donor_id=donor_id, name=name, phone=phone, location=location, organization_name=organization_name)


def get_organization_record(org_id: str) -> Optional[Dict[str, Any]]:
    return get_repository().get_organization_record(org_id)


def get_organization_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    return get_repository().get_organization_by_phone(phone)


def create_organization_record(
    org_id: str,
    name: str,
    phone: str,
    service_area: str,
    accepted_food_types: str,
    capacity: Optional[str] = None,
    availability: Optional[str] = "daytime",
    location: Optional[str] = None,
) -> Dict[str, Any]:
    return get_repository().create_organization_record(
        org_id=org_id,
        name=name,
        phone=phone,
        service_area=service_area,
        accepted_food_types=accepted_food_types,
        capacity=capacity,
        availability=availability,
        location=location,
    )


def update_organization_record(
    org_id: str,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    service_area: Optional[str] = None,
    accepted_food_types: Optional[str] = None,
    capacity: Optional[str] = None,
    availability: Optional[str] = None,
    location: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    return get_repository().update_organization_record(
        org_id=org_id,
        name=name,
        phone=phone,
        service_area=service_area,
        accepted_food_types=accepted_food_types,
        capacity=capacity,
        availability=availability,
        location=location,
    )


def create_volunteer_record(
    volunteer_id: str,
    name: str,
    phone: str,
    service_area: str,
    transport_mode: str = "Motorbike",
    availability: str = "immediate, evenings",
    current_status: str = "available",
    location: Optional[str] = None,
) -> Dict[str, Any]:
    return get_repository().create_volunteer_record(
        volunteer_id=volunteer_id,
        name=name,
        phone=phone,
        service_area=service_area,
        transport_mode=transport_mode,
        availability=availability,
        current_status=current_status,
        location=location,
    )


def get_volunteer_record(volunteer_id: str) -> Optional[Dict[str, Any]]:
    return get_repository().get_volunteer_record(volunteer_id)


def get_volunteer_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    return get_repository().get_volunteer_by_phone(phone)


def update_volunteer_record(
    volunteer_id: str,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    service_area: Optional[str] = None,
    transport_mode: Optional[str] = None,
    availability: Optional[str] = None,
    current_status: Optional[str] = None,
    location: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    return get_repository().update_volunteer_record(
        volunteer_id=volunteer_id,
        name=name,
        phone=phone,
        service_area=service_area,
        transport_mode=transport_mode,
        availability=availability,
        current_status=current_status,
        location=location,
    )


def create_donation_record(
    donation_id: str, donor_id: str, food_type: str, quantity: float, unit: str, dietary_info: str, location: str, available_from: str, deadline: str
) -> Dict[str, Any]:
    return get_repository().create_donation_record(
        donation_id=donation_id,
        donor_id=donor_id,
        food_type=food_type,
        quantity=quantity,
        unit=unit,
        dietary_info=dietary_info,
        location=location,
        available_from=available_from,
        deadline=deadline,
    )


def get_donation_record(donation_id: str) -> Optional[Dict[str, Any]]:
    return get_repository().get_donation_record(donation_id)


def update_donation_status_record(donation_id: str, status: str) -> bool:
    return get_repository().update_donation_status_record(donation_id, status)


def update_donation_details_record(
    donation_id: str,
    food_type: Optional[str] = None,
    quantity: Optional[float] = None,
    unit: Optional[str] = None,
    dietary_info: Optional[str] = None,
    location: Optional[str] = None,
    available_from: Optional[str] = None,
    deadline: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    return get_repository().update_donation_details_record(
        donation_id=donation_id,
        food_type=food_type,
        quantity=quantity,
        unit=unit,
        dietary_info=dietary_info,
        location=location,
        available_from=available_from,
        deadline=deadline,
    )


def find_organizations_by_criteria(food_type: str, location: str) -> List[Dict[str, Any]]:
    return get_repository().find_organizations_by_criteria(food_type, location)


def accept_donation_record(donation_id: str, organization_id: str) -> bool:
    return get_repository().accept_donation_record(donation_id, organization_id)


def find_volunteers_by_criteria(location: str) -> List[Dict[str, Any]]:
    return get_repository().find_volunteers_by_criteria(location)


def create_pickup_task_record(task_id: str, donation_id: str, org_id: str, pickup_loc: str, delivery_loc: str, time: str) -> Dict[str, Any]:
    return get_repository().create_pickup_task_record(
        task_id=task_id, donation_id=donation_id, org_id=org_id, pickup_loc=pickup_loc, delivery_loc=delivery_loc, time=time
    )


def get_pickup_task_record(task_id: str) -> Optional[Dict[str, Any]]:
    return get_repository().get_pickup_task_record(task_id)


def get_pickup_tasks_by_donation_id(donation_id: str) -> List[Dict[str, Any]]:
    return get_repository().get_pickup_tasks_by_donation_id(donation_id)


def get_donations_by_donor_id(donor_id: str) -> List[Dict[str, Any]]:
    return get_repository().get_donations_by_donor_id(donor_id)


def get_pickup_tasks_for_volunteer(volunteer_id: str) -> List[Dict[str, Any]]:
    return get_repository().get_pickup_tasks_for_volunteer(volunteer_id)


def get_pickup_tasks_for_organization(org_id: str) -> List[Dict[str, Any]]:
    return get_repository().get_pickup_tasks_for_organization(org_id)


def assign_volunteer_record(task_id: str, volunteer_id: str, atomic_claim: bool = False) -> bool:
    return get_repository().assign_volunteer_record(task_id, volunteer_id, atomic_claim=atomic_claim)


def update_pickup_status_record(task_id: str, status: str) -> bool:
    return get_repository().update_pickup_status_record(task_id, status)


def create_notification_record(notif_id: str, recipient_type: str, recipient_id: str, message: str, channel: str) -> None:
    get_repository().create_notification_record(
        notif_id=notif_id, recipient_type=recipient_type, recipient_id=recipient_id, message=message, channel=channel
    )


def get_notifications_for_recipient(recipient_id: str) -> List[Dict[str, Any]]:
    return get_repository().get_notifications_for_recipient(recipient_id)


def get_all_donations(status: Optional[str] = None) -> List[Dict[str, Any]]:
    return get_repository().get_all_donations(status)


def get_all_organizations() -> List[Dict[str, Any]]:
    return get_repository().get_all_organizations()


def get_all_volunteers() -> List[Dict[str, Any]]:
    return get_repository().get_all_volunteers()


def create_volunteer_record(
    volunteer_id: str,
    name: str,
    phone: str,
    service_area: str,
    transport_mode: str = "Motorbike",
    availability: str = "immediate, evenings",
    current_status: str = "available",
    location: Optional[str] = None,
) -> Dict[str, Any]:
    return get_repository().create_volunteer_record(
        volunteer_id=volunteer_id,
        name=name,
        phone=phone,
        service_area=service_area,
        transport_mode=transport_mode,
        availability=availability,
        current_status=current_status,
        location=location,
    )


def update_volunteer_record(
    volunteer_id: str,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    service_area: Optional[str] = None,
    transport_mode: Optional[str] = None,
    availability: Optional[str] = None,
    current_status: Optional[str] = None,
    location: Optional[str] = None,
    **kwargs: Any,
) -> Optional[Dict[str, Any]]:
    return get_repository().update_volunteer_record(
        volunteer_id=volunteer_id,
        name=name,
        phone=phone,
        service_area=service_area,
        transport_mode=transport_mode,
        availability=availability,
        current_status=current_status,
        location=location,
    )


def get_all_pickup_tasks() -> List[Dict[str, Any]]:
    return get_repository().get_all_pickup_tasks()


def get_all_notifications(limit: int = 50) -> List[Dict[str, Any]]:
    return get_repository().get_all_notifications(limit)


def get_dashboard_stats() -> Dict[str, Any]:
    return get_repository().get_dashboard_stats()


def reset_database_data(wipe_all: bool = False) -> None:
    get_repository().reset_database_data(wipe_all=wipe_all)


# Reimbursements Delegation
def create_reimbursement_record(
    reimbursement_id: str,
    pickup_task_id: str,
    volunteer_id: str,
    distance_km: float,
    rate_per_km: float,
    transport_mode: str,
    amount: float,
    currency: str = "LKR",
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    return get_repository().create_reimbursement_record(
        reimbursement_id=reimbursement_id,
        pickup_task_id=pickup_task_id,
        volunteer_id=volunteer_id,
        distance_km=distance_km,
        rate_per_km=rate_per_km,
        transport_mode=transport_mode,
        amount=amount,
        currency=currency,
        notes=notes,
    )


def get_reimbursement_record(reimbursement_id: str) -> Optional[Dict[str, Any]]:
    return get_repository().get_reimbursement_record(reimbursement_id)


def get_reimbursement_by_pickup_id(pickup_task_id: str) -> Optional[Dict[str, Any]]:
    return get_repository().get_reimbursement_by_pickup_id(pickup_task_id)


def get_reimbursements_for_volunteer(volunteer_id: str) -> List[Dict[str, Any]]:
    return get_repository().get_reimbursements_for_volunteer(volunteer_id)


def get_all_reimbursements(status: Optional[str] = None) -> List[Dict[str, Any]]:
    return get_repository().get_all_reimbursements(status)


def update_reimbursement_status_record(reimbursement_id: str, status: str, notes: Optional[str] = None) -> bool:
    return get_repository().update_reimbursement_status_record(reimbursement_id, status, notes)


# GPS Location Tracking Delegation
def record_pickup_location(
    location_id: str,
    pickup_task_id: str,
    volunteer_id: str,
    latitude: float,
    longitude: float,
    accuracy_m: Optional[float] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    return get_repository().record_pickup_location(
        location_id=location_id,
        pickup_task_id=pickup_task_id,
        volunteer_id=volunteer_id,
        latitude=latitude,
        longitude=longitude,
        accuracy_m=accuracy_m,
        timestamp=timestamp,
    )


def get_latest_pickup_location(pickup_task_id: str) -> Optional[Dict[str, Any]]:
    return get_repository().get_latest_pickup_location(pickup_task_id)


def get_pickup_location_history(pickup_task_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    return get_repository().get_pickup_location_history(pickup_task_id, limit)


def update_volunteer_availability(
    volunteer_id: str, status: str, current_location: Optional[str] = None, current_coordinates: Optional[Dict[str, Any]] = None
) -> bool:
    return get_repository().update_volunteer_availability(
        volunteer_id=volunteer_id, status=status, current_location=current_location, current_coordinates=current_coordinates
    )


def get_available_volunteers(service_area: Optional[str] = None, min_capacity: Optional[int] = None) -> List[Dict[str, Any]]:
    return get_repository().get_available_volunteers(service_area=service_area, min_capacity=min_capacity)


def update_pickup_task_logistics(
    task_id: str,
    pickup_coordinates: Optional[Dict[str, Any]] = None,
    destination_coordinates: Optional[Dict[str, Any]] = None,
    pickup_distance_km: Optional[float] = None,
    pickup_duration_minutes: Optional[int] = None,
    delivery_distance_km: Optional[float] = None,
    delivery_duration_minutes: Optional[int] = None,
    total_distance_km: Optional[float] = None,
    estimated_transport_cost: Optional[float] = None,
) -> bool:
    return get_repository().update_pickup_task_logistics(
        task_id=task_id,
        pickup_coordinates=pickup_coordinates,
        destination_coordinates=destination_coordinates,
        pickup_distance_km=pickup_distance_km,
        pickup_duration_minutes=pickup_duration_minutes,
        delivery_distance_km=delivery_distance_km,
        delivery_duration_minutes=delivery_duration_minutes,
        total_distance_km=total_distance_km,
        estimated_transport_cost=estimated_transport_cost,
    )


def create_audit_event_record(
    event_id: str, event_type: str, actor: str, related_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    return get_repository().create_audit_event_record(event_id=event_id, event_type=event_type, actor=actor, related_id=related_id, metadata=metadata)


def get_audit_events_for_task(related_id: str) -> List[Dict[str, Any]]:
    return get_repository().get_audit_events_for_task(related_id)


# User Profile & Onboarding Management
def get_user_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    return get_repository().get_user_by_phone(phone)


def create_or_update_user(
    phone: str,
    display_name: Optional[str] = None,
    preferred_language: Optional[str] = None,
    preferred_response_mode: Optional[str] = None,
    user_role: str = "unknown",
    onboarding_completed: bool = False,
    default_location: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return get_repository().create_or_update_user(
        phone=phone,
        display_name=display_name,
        preferred_language=preferred_language,
        preferred_response_mode=preferred_response_mode,
        user_role=user_role,
        onboarding_completed=onboarding_completed,
        default_location=default_location,
        metadata=metadata,
    )


def set_user_language(phone: str, language: str) -> bool:
    return get_repository().set_user_language(phone=phone, language=language)


def set_user_response_mode(phone: str, mode: str) -> bool:
    return get_repository().set_user_response_mode(phone=phone, mode=mode)


def set_onboarding_completed(phone: str, completed: bool = True) -> bool:
    return get_repository().set_onboarding_completed(phone=phone, completed=completed)


def update_user_profile(
    phone: str,
    display_name: Optional[str] = None,
    preferred_language: Optional[str] = None,
    preferred_response_mode: Optional[str] = None,
    user_role: Optional[str] = None,
    default_location: Optional[str] = None,
    active_donation_id: Optional[str] = None,
    active_task_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return get_repository().update_user_profile(
        phone=phone,
        display_name=display_name,
        preferred_language=preferred_language,
        preferred_response_mode=preferred_response_mode,
        user_role=user_role,
        default_location=default_location,
        active_donation_id=active_donation_id,
        active_task_id=active_task_id,
        metadata=metadata,
    )


def get_user_conversation_state(phone: str) -> Dict[str, Any]:
    return get_repository().get_user_conversation_state(phone=phone)


def set_user_conversation_state(phone: str, state: Dict[str, Any]) -> bool:
    return get_repository().set_user_conversation_state(phone=phone, state=state)


def clear_user_conversation_state(phone: str) -> bool:
    return get_repository().clear_user_conversation_state(phone=phone)


def save_draft_donation(phone: str, draft_data: Dict[str, Any]) -> Dict[str, Any]:
    return get_repository().save_draft_donation(phone=phone, draft_data=draft_data)


def get_draft_donation(phone: str) -> Optional[Dict[str, Any]]:
    return get_repository().get_draft_donation(phone=phone)


def clear_draft_donation(phone: str) -> bool:
    return get_repository().clear_draft_donation(phone=phone)


def get_all_users() -> List[Dict[str, Any]]:
    return get_repository().get_all_users()


def get_all_donors() -> List[Dict[str, Any]]:
    return get_repository().get_all_donors()


def record_message(
    phone: str, sender: str, text: str, is_voice: bool = False, transcript: Optional[str] = None, timestamp: Optional[str] = None
) -> Dict[str, Any]:
    return get_repository().record_message(phone=phone, sender=sender, text=text, is_voice=is_voice, transcript=transcript, timestamp=timestamp)


def claim_whatsapp_message_id(message_id: str) -> bool:
    """Atomically claim a WhatsApp message ID to prevent duplicate processing across serverless instances."""
    if not message_id:
        return True
    try:
        return get_repository().claim_whatsapp_message_id(message_id)
    except Exception as e:
        logger.warning(f"Error claiming message ID {message_id}: {e}")
        return True


def get_all_conversations() -> List[Dict[str, Any]]:
    return get_repository().get_all_conversations()


def get_conversation_messages(phone: str, limit: int = 100) -> List[Dict[str, Any]]:
    return get_repository().get_conversation_messages(phone=phone, limit=limit)


def get_all_audit_events(limit: int = 100) -> List[Dict[str, Any]]:
    return get_repository().get_all_audit_events(limit=limit)


def get_transport_settings() -> Dict[str, Any]:
    return get_repository().get_transport_settings()


def update_transport_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    return get_repository().update_transport_settings(settings=settings)


# QR Code Handover Verification Persistence
def create_qr_code_record(
    qr_id: str,
    task_id: str,
    donation_id: str,
    qr_type: str,
    token: str,
    token_hash: str,
    donor_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    assigned_volunteer_id: Optional[str] = None,
    status: str = "ACTIVE",
    created_at: Optional[str] = None,
    expires_at: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return get_repository().create_qr_code_record(
        qr_id=qr_id,
        task_id=task_id,
        donation_id=donation_id,
        qr_type=qr_type,
        token=token,
        token_hash=token_hash,
        donor_id=donor_id,
        organization_id=organization_id,
        assigned_volunteer_id=assigned_volunteer_id,
        status=status,
        created_at=created_at,
        expires_at=expires_at,
        metadata=metadata,
    )


def get_qr_code_by_token(token: str) -> Optional[Dict[str, Any]]:
    return get_repository().get_qr_code_by_token(token=token)


def get_qr_codes_for_task(task_id: str) -> List[Dict[str, Any]]:
    return get_repository().get_qr_codes_for_task(task_id=task_id)


def get_qr_code_by_id(qr_id: str) -> Optional[Dict[str, Any]]:
    return get_repository().get_qr_code_by_id(qr_id=qr_id)


def verify_qr_code_record(token: str, volunteer_id: Optional[str] = None, gps_coords: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_repository().verify_qr_code_record(token=token, volunteer_id=volunteer_id, gps_coords=gps_coords)


def get_all_qr_codes(status: Optional[str] = None, qr_type: Optional[str] = None) -> List[Dict[str, Any]]:
    return get_repository().get_all_qr_codes(status=status, qr_type=qr_type)


# SQLite backwards-compatibility helpers
def get_db_path() -> str:
    from db_sqlite import DB_PATH

    return os.environ.get("FOODRESCUE_DB_PATH", DB_PATH)


def get_connection():
    repo = get_repository()
    if hasattr(repo, "_get_connection"):
        return repo._get_connection()
    from db_sqlite import SQLiteRepository

    return SQLiteRepository()._get_connection()


# Sri Lanka Timezone Utilities (Asia/Colombo / UTC+5:30)
import datetime

SL_TIMEZONE = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="Asia/Colombo")


def get_sri_lanka_tz() -> datetime.timezone:
    """Return the Sri Lanka standard timezone (+05:30)."""
    return SL_TIMEZONE


def get_sri_lanka_now() -> datetime.datetime:
    """Return the current datetime in Sri Lanka Standard Time."""
    return datetime.datetime.now(SL_TIMEZONE)


def format_sri_lanka_time(dt_or_str: Optional[Any] = None) -> str:
    """Format a datetime or ISO string into human-readable Sri Lanka Time (e.g. 2026-08-26 07:43 PM (+05:30))."""
    if dt_or_str is None:
        dt = get_sri_lanka_now()
    elif isinstance(dt_or_str, datetime.datetime):
        if dt_or_str.tzinfo is None:
            dt = dt_or_str.replace(tzinfo=datetime.timezone.utc).astimezone(SL_TIMEZONE)
        else:
            dt = dt_or_str.astimezone(SL_TIMEZONE)
    elif isinstance(dt_or_str, str):
        try:
            parsed = datetime.datetime.fromisoformat(dt_or_str.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            dt = parsed.astimezone(SL_TIMEZONE)
        except Exception:
            return dt_or_str
    else:
        return str(dt_or_str)

    return dt.strftime("%Y-%m-%d %I:%M %p (+05:30)")


# Record Deletion Helpers
def delete_donation_record(donation_id: str) -> bool:
    return get_repository().delete_donation_record(donation_id)


def delete_donor_record(donor_id: str) -> bool:
    return get_repository().delete_donor_record(donor_id)


def delete_organization_record(org_id: str) -> bool:
    return get_repository().delete_organization_record(org_id)


def delete_volunteer_record(volunteer_id: str) -> bool:
    return get_repository().delete_volunteer_record(volunteer_id)


def delete_user_record(phone: str) -> bool:
    return get_repository().delete_user_record(phone)


def delete_pickup_task_record(task_id: str) -> bool:
    return get_repository().delete_pickup_task_record(task_id)


def delete_organization_by_phone(phone: str) -> bool:
    return get_repository().delete_organization_by_phone(phone)


def delete_volunteer_by_phone(phone: str) -> bool:
    return get_repository().delete_volunteer_by_phone(phone)


def delete_donor_by_phone(phone: str) -> bool:
    return get_repository().delete_donor_by_phone(phone)


def cancel_active_donation_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    return get_repository().cancel_active_donation_by_phone(phone)


def get_user_full_context(phone: str) -> Dict[str, Any]:
    return get_repository().get_user_full_context(phone)
