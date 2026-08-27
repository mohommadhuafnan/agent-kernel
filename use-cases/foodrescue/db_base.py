"""Base Repository Interface for FoodRescue AI.

Defines the contract for business persistence across Supabase PostgreSQL and SQLite backends.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class BaseRepository(ABC):
    """Abstract Base Class defining the FoodRescue persistence interface."""

    @abstractmethod
    def setup_database(self) -> None:
        """Initialize database schema, tables, collections, or indexes."""
        pass

    @abstractmethod
    def seed_test_data(self) -> None:
        """Seed initial test master data (donors, organizations, volunteers) if empty."""
        pass

    @abstractmethod
    def get_donor_record(self, donor_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a donor record by donor ID."""
        pass

    @abstractmethod
    def get_donor_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Retrieve a donor record by phone number."""
        pass

    @abstractmethod
    def create_donor_record(
        self,
        donor_id: str,
        name: str,
        phone: str,
        location: str,
        organization_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a registered food donor record."""
        pass

    @abstractmethod
    def get_organization_record(self, org_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve an organization record by organization ID."""
        pass

    @abstractmethod
    def get_organization_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Retrieve an organization record by phone number."""
        pass

    @abstractmethod
    def create_organization_record(
        self,
        org_id: str,
        name: str,
        phone: str,
        service_area: str,
        accepted_food_types: str,
        capacity: Optional[str] = None,
        availability: Optional[str] = "daytime",
        location: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a registered recipient organization record."""
        pass

    @abstractmethod
    def update_organization_record(
        self,
        org_id: str,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        service_area: Optional[str] = None,
        accepted_food_types: Optional[str] = None,
        capacity: Optional[str] = None,
        availability: Optional[str] = None,
        location: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Update an existing organization record."""
        pass

    @abstractmethod
    def get_volunteer_record(self, volunteer_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a volunteer record by volunteer ID."""
        pass

    @abstractmethod
    def get_volunteer_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Retrieve a volunteer record by phone number."""
        pass

    @abstractmethod
    def create_volunteer_record(
        self,
        volunteer_id: str,
        name: str,
        phone: str,
        service_area: str,
        transport_mode: str = "Motorbike",
        availability: str = "immediate, evenings",
        current_status: str = "available",
        location: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a registered volunteer courier record."""
        pass

    @abstractmethod
    def update_volunteer_record(
        self,
        volunteer_id: str,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        service_area: Optional[str] = None,
        transport_mode: Optional[str] = None,
        availability: Optional[str] = None,
        current_status: Optional[str] = None,
        location: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Update an existing volunteer courier record."""
        pass


    @abstractmethod
    def create_donation_record(
        self,
        donation_id: str,
        donor_id: str,
        food_type: str,
        quantity: float,
        unit: str,
        dietary_info: str,
        location: str,
        available_from: str,
        deadline: str
    ) -> Dict[str, Any]:
        """Create a new food donation record with status AVAILABLE."""
        pass

    @abstractmethod
    def get_donation_record(self, donation_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single donation record by donation ID."""
        pass

    @abstractmethod
    def update_donation_status_record(self, donation_id: str, status: str) -> bool:
        """Update the lifecycle status of a donation."""
        pass

    @abstractmethod
    def update_donation_details_record(
        self,
        donation_id: str,
        food_type: Optional[str] = None,
        quantity: Optional[float] = None,
        unit: Optional[str] = None,
        dietary_info: Optional[str] = None,
        location: Optional[str] = None,
        available_from: Optional[str] = None,
        deadline: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Update editable details of an existing donation."""
        pass

    @abstractmethod
    def find_organizations_by_criteria(self, food_type: str, location: str) -> List[Dict[str, Any]]:
        """Search and rank eligible organizations by location and accepted food types."""
        pass

    @abstractmethod
    def accept_donation_record(self, donation_id: str, organization_id: str) -> bool:
        """Mark a donation as MATCHED when accepted by an organization."""
        pass

    @abstractmethod
    def find_volunteers_by_criteria(self, location: str) -> List[Dict[str, Any]]:
        """Search and rank available volunteers in proximity to a location."""
        pass

    @abstractmethod
    def create_pickup_task_record(
        self,
        task_id: str,
        donation_id: str,
        org_id: str,
        pickup_loc: str,
        delivery_loc: str,
        time: str
    ) -> Dict[str, Any]:
        """Create a pickup task linking donation, donor location, and delivery location."""
        pass

    @abstractmethod
    def get_pickup_task_record(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a pickup task by task ID."""
        pass

    @abstractmethod
    def get_pickup_tasks_by_donation_id(self, donation_id: str) -> List[Dict[str, Any]]:
        """Retrieve all pickup tasks associated with a donation ID."""
        pass

    @abstractmethod
    def get_donations_by_donor_id(self, donor_id: str) -> List[Dict[str, Any]]:
        """Retrieve all food donations created by a specific donor."""
        pass

    @abstractmethod
    def get_pickup_tasks_for_volunteer(self, volunteer_id: str) -> List[Dict[str, Any]]:
        """Retrieve all pickup tasks assigned to a specific volunteer."""
        pass

    @abstractmethod
    def get_pickup_tasks_for_organization(self, org_id: str) -> List[Dict[str, Any]]:
        """Retrieve all pickup tasks delivering to a specific organization."""
        pass

    @abstractmethod
    def assign_volunteer_record(self, task_id: str, volunteer_id: str, atomic_claim: bool = False) -> bool:
        """Assign an available volunteer to a pickup task. If atomic_claim is True, only assign if unassigned."""
        pass

    @abstractmethod
    def update_pickup_status_record(self, task_id: str, status: str) -> bool:
        """Update the operational status of a pickup task."""
        pass

    @abstractmethod
    def create_notification_record(
        self,
        notif_id: str,
        recipient_type: str,
        recipient_id: str,
        message: str,
        channel: str
    ) -> None:
        """Create an audit notification record for donor, org, or volunteer."""
        pass

    @abstractmethod
    def get_notifications_for_recipient(self, recipient_id: str) -> List[Dict[str, Any]]:
        """Retrieve recent notifications for a specific recipient."""
        pass

    @abstractmethod
    def get_all_donations(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve all donations with optional status filtering."""
        pass

    @abstractmethod
    def get_all_organizations(self) -> List[Dict[str, Any]]:
        """Retrieve all registered recipient organizations."""
        pass

    @abstractmethod
    def get_all_volunteers(self) -> List[Dict[str, Any]]:
        """Retrieve all registered volunteers."""
        pass

    @abstractmethod
    def get_all_pickup_tasks(self) -> List[Dict[str, Any]]:
        """Retrieve all pickup tasks with linked org and volunteer names."""
        pass

    @abstractmethod
    def get_all_notifications(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent system notifications feed."""
        pass

    @abstractmethod
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Calculate real-time aggregated dashboard KPIs."""
        pass

    @abstractmethod
    def reset_database_data(self, wipe_all: bool = False) -> None:
        """Reset donations, pickup tasks, users, and dynamic records. If wipe_all=True, wipe all entities."""
        pass

    # Reimbursements (Accounting Ledger)
    @abstractmethod
    def create_reimbursement_record(
        self,
        reimbursement_id: str,
        pickup_task_id: str,
        volunteer_id: str,
        distance_km: float,
        rate_per_km: float,
        transport_mode: str,
        amount: float,
        currency: str = "LKR",
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a volunteer travel reimbursement record with status PENDING."""
        pass

    @abstractmethod
    def get_reimbursement_record(self, reimbursement_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a reimbursement record by its ID."""
        pass

    @abstractmethod
    def get_reimbursement_by_pickup_id(self, pickup_task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the reimbursement record linked to a specific pickup task."""
        pass

    @abstractmethod
    def get_reimbursements_for_volunteer(self, volunteer_id: str) -> List[Dict[str, Any]]:
        """Retrieve all reimbursement records for a specific volunteer."""
        pass

    @abstractmethod
    def get_all_reimbursements(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve all reimbursement records, optionally filtered by status."""
        pass

    @abstractmethod
    def update_reimbursement_status_record(
        self,
        reimbursement_id: str,
        status: str,
        notes: Optional[str] = None
    ) -> bool:
        """Update reimbursement lifecycle status (PENDING, APPROVED, PAID, CANCELLED)."""
        pass

    # GPS Location Tracking
    @abstractmethod
    def record_pickup_location(
        self,
        location_id: str,
        pickup_task_id: str,
        volunteer_id: str,
        latitude: float,
        longitude: float,
        accuracy_m: Optional[float] = None,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        """Record a live GPS coordinate point for an active pickup task."""
        pass

    @abstractmethod
    def get_latest_pickup_location(self, pickup_task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the most recent GPS location for a pickup task."""
        pass

    @abstractmethod
    def get_pickup_location_history(self, pickup_task_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve the historical breadcrumb GPS points for a pickup task."""
        pass

    # Volunteer Availability & Location Coordination
    @abstractmethod
    def update_volunteer_availability(
        self,
        volunteer_id: str,
        status: str,
        current_location: Optional[str] = None,
        current_coordinates: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Update volunteer availability state (AVAILABLE, BUSY, OFFLINE, ON_PICKUP, ON_DELIVERY) and location."""
        pass

    @abstractmethod
    def get_available_volunteers(
        self,
        service_area: Optional[str] = None,
        min_capacity: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve volunteers currently marked as AVAILABLE, filtered by service area and capacity."""
        pass

    @abstractmethod
    def update_pickup_task_logistics(
        self,
        task_id: str,
        pickup_coordinates: Optional[Dict[str, Any]] = None,
        destination_coordinates: Optional[Dict[str, Any]] = None,
        pickup_distance_km: Optional[float] = None,
        pickup_duration_minutes: Optional[int] = None,
        delivery_distance_km: Optional[float] = None,
        delivery_duration_minutes: Optional[int] = None,
        total_distance_km: Optional[float] = None,
        estimated_transport_cost: Optional[float] = None
    ) -> bool:
        """Update logistics coordinates, two-leg routing metrics, and estimated transport cost on a pickup task."""
        pass

    # Audit Trail Event Logging
    @abstractmethod
    def create_audit_event_record(
        self,
        event_id: str,
        event_type: str,
        actor: str,
        related_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Record an operational audit event for system state transitions."""
        pass

    @abstractmethod
    def get_audit_events_for_task(self, related_id: str) -> List[Dict[str, Any]]:
        """Retrieve operational audit trail events associated with a donation or pickup task."""
        pass

    # User Profile & Onboarding Management
    @abstractmethod
    def get_user_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Retrieve a user profile record by normalized phone number."""
        pass

    @abstractmethod
    def create_or_update_user(
        self,
        phone: str,
        display_name: Optional[str] = None,
        preferred_language: Optional[str] = None,
        preferred_response_mode: Optional[str] = None,
        user_role: str = "unknown",
        onboarding_completed: bool = False,
        default_location: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create or update a user profile record with language preference, response mode, and onboarding status."""
        pass

    @abstractmethod
    def set_user_language(self, phone: str, language: str) -> bool:
        """Update a user's persistent preferred language."""
        pass

    @abstractmethod
    def set_onboarding_completed(self, phone: str, completed: bool = True) -> bool:
        """Mark a user's onboarding as completed or pending."""
        pass

    @abstractmethod
    def set_user_response_mode(self, phone: str, mode: str) -> bool:
        """Update a user's persistent preferred response mode ('text' or 'voice')."""
        pass

    @abstractmethod
    def update_user_profile(
        self,
        phone: str,
        display_name: Optional[str] = None,
        preferred_language: Optional[str] = None,
        preferred_response_mode: Optional[str] = None,
        user_role: Optional[str] = None,
        default_location: Optional[str] = None,
        active_donation_id: Optional[str] = None,
        active_task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Update fields on a persistent user profile."""
        pass

    @abstractmethod
    def get_user_conversation_state(self, phone: str) -> Dict[str, Any]:
        """Retrieve the active conversation workflow state and slot tracking for a user."""
        pass

    @abstractmethod
    def set_user_conversation_state(self, phone: str, state: Dict[str, Any]) -> bool:
        """Persist the active conversation workflow state and slot tracking for a user."""
        pass

    @abstractmethod
    def clear_user_conversation_state(self, phone: str) -> bool:
        """Clear active conversation workflow state back to IDLE."""
        pass

    @abstractmethod
    def save_draft_donation(self, phone: str, draft_data: Dict[str, Any]) -> Dict[str, Any]:
        """Save or merge in-progress donation draft slot data."""
        pass

    @abstractmethod
    def get_draft_donation(self, phone: str) -> Optional[Dict[str, Any]]:
        """Retrieve active in-progress donation draft slot data."""
        pass

    @abstractmethod
    def clear_draft_donation(self, phone: str) -> bool:
        """Clear in-progress donation draft slot data."""
        pass

    @abstractmethod
    def get_all_users(self) -> List[Dict[str, Any]]:
        """Retrieve all registered user records."""
        pass

    @abstractmethod
    def get_all_donors(self) -> List[Dict[str, Any]]:
        """Retrieve all registered food donor records."""
        pass

    @abstractmethod
    def record_message(
        self,
        phone: str,
        sender: str,
        text: str,
        is_voice: bool = False,
        transcript: Optional[str] = None,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        """Record an incoming or outgoing chat message for conversation history tracking."""
        pass

    @abstractmethod
    def get_all_conversations(self) -> List[Dict[str, Any]]:
        """Retrieve all active conversation threads with latest message and metadata."""
        pass

    @abstractmethod
    def get_conversation_messages(self, phone: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve full chronological chat message history for a phone number."""
        pass

    @abstractmethod
    def get_all_audit_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve all operational audit events across the platform."""
        pass

    @abstractmethod
    def get_transport_settings(self) -> Dict[str, Any]:
        """Retrieve dynamic transport reimbursement cost configuration."""
        pass

    @abstractmethod
    def update_transport_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Update dynamic transport reimbursement cost configuration."""
        pass

    # QR Code Handover Verification Persistence
    @abstractmethod
    def create_qr_code_record(
        self,
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
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new secure handover verification QR code record."""
        pass

    @abstractmethod
    def get_qr_code_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Retrieve a QR code record by its raw verification token."""
        pass

    @abstractmethod
    def get_qr_codes_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        """Retrieve all QR code records associated with a pickup task."""
        pass

    @abstractmethod
    def get_qr_code_by_id(self, qr_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a QR code record by its primary ID."""
        pass

    @abstractmethod
    def verify_qr_code_record(
        self,
        token: str,
        volunteer_id: Optional[str] = None,
        gps_coords: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Atomically verify a physical handover QR code and advance task lifecycle status."""
        pass

    @abstractmethod
    def get_all_qr_codes(
        self,
        status: Optional[str] = None,
        qr_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve all QR codes with optional status or type filtering."""
        pass

    # Record Deletion Interface
    @abstractmethod
    def delete_donation_record(self, donation_id: str) -> bool:
        """Delete a food donation record and its linked tasks/QR codes."""
        pass

    @abstractmethod
    def delete_donor_record(self, donor_id: str) -> bool:
        """Delete a donor record."""
        pass

    @abstractmethod
    def delete_organization_record(self, org_id: str) -> bool:
        """Delete an organization record."""
        pass

    @abstractmethod
    def delete_volunteer_record(self, volunteer_id: str) -> bool:
        """Delete a volunteer record."""
        pass

    @abstractmethod
    def delete_user_record(self, phone: str) -> bool:
        """Delete a user profile and active state."""
        pass

    @abstractmethod
    def delete_pickup_task_record(self, task_id: str) -> bool:
        """Delete a pickup task record."""
        pass




